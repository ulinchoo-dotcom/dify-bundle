"""CLI 契约：退出码 0/1/2、报告产物、环境变量密钥。"""

import json
import shutil
from pathlib import Path

import pytest

from dify_bundle.cli import main

EXAMPLES = Path(__file__).parent.parent / "examples"


def _export(tmp_path, site="site-a", name="b"):
    out = tmp_path / name
    assert main(["export", "--source", str(EXAMPLES / site), "--out", str(out)]) == 0
    return out


def test_export_exit_codes(tmp_path):
    assert _export(tmp_path)  # 0 在 _export 里断言过了
    # 来源不存在 → 2
    assert main(["export", "--source", str(tmp_path / "nope"), "--out", str(tmp_path / "x")]) == 2


def test_check_clean_exit_0(tmp_path, capsys):
    bundle = _export(tmp_path)
    assert main(["check", str(bundle)]) == 0
    out = capsys.readouterr().out
    assert "可交付" in out
    assert "plugin-unpinned" in out  # tavily 未钉版本 → warning 可见


def test_check_html_report(tmp_path):
    bundle = _export(tmp_path)
    html = tmp_path / "check.html"
    assert main(["check", str(bundle), "--html", str(html)]) == 0
    text = html.read_text(encoding="utf-8")
    assert "交付包校验报告" in text


def test_check_missing_bundle_exit_2(tmp_path):
    assert main(["check", str(tmp_path / "nope")]) == 2


def test_diff_identical_exit_0(tmp_path):
    a = _export(tmp_path, "site-a", "a")
    b = _export(tmp_path, "site-a", "b")
    assert main(["diff", str(a), str(b)]) == 0


def test_diff_different_exit_1_and_reports(tmp_path):
    a = _export(tmp_path, "site-a", "a")
    b = _export(tmp_path, "site-b", "b")
    html, js = tmp_path / "d.html", tmp_path / "d.json"
    assert main(["diff", str(a), str(b), "--html", str(html), "--json-out", str(js)]) == 1
    assert "交付包差异对比" in html.read_text(encoding="utf-8")
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["apps_added"] == ["faq-bot"]
    assert data["has_differences"] is True


def test_import_end_to_end(tmp_path):
    bundle = _export(tmp_path)
    target = tmp_path / "target"
    assert main(["import", str(bundle), "--target", str(target)]) == 0
    assert (target / "customer-service.yaml").exists()


def test_import_blocked_without_secrets(tmp_path, capsys):
    bundle = _export(tmp_path)
    bare = tmp_path / "bare"
    shutil.copytree(bundle, bare, ignore=shutil.ignore_patterns("secrets.local.yaml"))
    assert main(["import", str(bare), "--target", str(tmp_path / "t")]) == 1
    assert "导入被拦" in capsys.readouterr().err


def test_import_dry_run(tmp_path):
    bundle = _export(tmp_path)
    target = tmp_path / "t"
    assert main(["import", str(bundle), "--target", str(target), "--dry-run"]) == 0
    assert not target.exists()


def test_template_and_instantiate(tmp_path, capsys):
    bundle = _export(tmp_path)
    tpl = tmp_path / "tpl"
    assert main(["template", str(bundle), "--out", str(tpl), "--name", "客服模板"]) == 0
    out = tmp_path / "out"
    assert main(["instantiate", str(tpl), "--out", str(out),
                 "--set", "customer-service.app_name=新客服"]) == 0
    assert (out / "bundle.yaml").exists()
    # --set 缺等号 → 2
    assert main(["instantiate", str(tpl), "--out", str(tmp_path / "o2"), "--set", "bad"]) == 2


def test_export_remote_without_token_exit_2(monkeypatch, tmp_path):
    monkeypatch.delenv("DIFY_CONSOLE_TOKEN", raising=False)
    assert main(["export", "--source", "https://dify.example.com",
                 "--out", str(tmp_path / "x")]) == 2
