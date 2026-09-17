"""import：先拦后建、密钥还原、dry-run 无副作用。"""

import os
from pathlib import Path

import pytest

from dify_bundle.exporter import export_bundle, load_bundle
from dify_bundle.importer import ImportBlocked, import_bundle
from dify_bundle.secrets import SecretMap
from dify_bundle.source import LocalSource

SITE_A = Path(__file__).parent.parent / "examples" / "site-a"


def _make_bundle(tmp_path):
    out = tmp_path / "bundle"
    bundle, smap = export_bundle(LocalSource(SITE_A), out)
    return load_bundle(out), smap


def test_import_restores_secrets(tmp_path):
    bundle, smap = _make_bundle(tmp_path)
    target = tmp_path / "target"
    plan = import_bundle(bundle, target, smap=smap)
    assert plan.unresolved == []
    text = (target / "customer-service.yaml").read_text(encoding="utf-8")
    assert "sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6" in text  # 真实值回来了


def test_dry_run_writes_nothing(tmp_path):
    bundle, smap = _make_bundle(tmp_path)
    target = tmp_path / "target"
    plan = import_bundle(bundle, target, smap=smap, dry_run=True)
    assert plan.apps_to_write == ["customer-service", "order-query"]
    assert not target.exists()


def test_import_without_map_reports_unresolved(tmp_path):
    bundle, _ = _make_bundle(tmp_path)
    # 把 bundle 拷到一个没有 secrets.local.yaml 的位置
    import shutil
    bare = tmp_path / "bare"
    shutil.copytree(tmp_path / "bundle", bare, ignore=shutil.ignore_patterns("secrets.local.yaml"))
    bundle = load_bundle(bare)
    plan = import_bundle(bundle, tmp_path / "t", smap=SecretMap(), force=True)
    assert plan.unresolved  # 有占位符没还原


def test_env_var_fallback(tmp_path, monkeypatch):
    """CI 场景：映射文件没有，但环境变量 SECRET_<8hex> 供给了真实值。"""
    bundle, smap = _make_bundle(tmp_path)
    for ph, real in smap.entries.items():
        env_name = ph.strip("${}")  # SECRET_xxxxxxxx
        monkeypatch.setenv(env_name, real)
    plan = import_bundle(bundle, tmp_path / "t", smap=SecretMap())
    assert plan.unresolved == []


def test_blocked_by_broken_bundle(tmp_path):
    """check 有 error（占位符未解析）且没 --force → ImportBlocked，不写文件。"""
    import shutil
    _make_bundle(tmp_path)
    bare = tmp_path / "bare"
    shutil.copytree(tmp_path / "bundle", bare, ignore=shutil.ignore_patterns("secrets.local.yaml"))
    bundle = load_bundle(bare)
    with pytest.raises(ImportBlocked):
        import_bundle(bundle, tmp_path / "t2", smap=SecretMap())
    assert not (tmp_path / "t2").exists()
