"""template / instantiate：抽象与回填的 round-trip。"""

from pathlib import Path

import pytest
import yaml

from dify_bundle.exporter import export_bundle, load_bundle
from dify_bundle.source import LocalSource
from dify_bundle.templater import (
    TemplateError,
    extract_template,
    instantiate_template,
    load_template,
)

SITE_A = Path(__file__).parent.parent / "examples" / "site-a"


def _make_bundle(tmp_path):
    out = tmp_path / "bundle"
    export_bundle(LocalSource(SITE_A), out, name="客服套件")
    return out


def test_extract_creates_variables(tmp_path):
    bundle_dir = _make_bundle(tmp_path)
    tpl_dir = tmp_path / "tpl"
    tpl = extract_template(bundle_dir, tpl_dir, name="制造业客服模板")
    names = {v.name for v in tpl.vars}
    assert "customer-service.app_name" in names
    assert "customer-service.app_description" in names
    assert "env.KB_ENDPOINT" in names
    assert (tpl_dir / "template.yaml").exists()
    # 模板里的 DSL 不该再有客户名字
    text = (tpl_dir / "apps" / "customer-service.yaml").read_text(encoding="utf-8")
    assert "智能客服助手" not in text
    assert "{{ customer-service.app_name }}" in text


def test_extract_keeps_secret_placeholders(tmp_path):
    bundle_dir = _make_bundle(tmp_path)
    tpl_dir = tmp_path / "tpl"
    extract_template(bundle_dir, tpl_dir)
    text = (tpl_dir / "env.yaml").read_text(encoding="utf-8")
    assert "SECRET_" in text  # secret 占位符原样保留，不变成模板变量


def test_instantiate_roundtrip_defaults(tmp_path):
    """不提供任何 --set：全部用默认值 → 回到原 bundle。"""
    bundle_dir = _make_bundle(tmp_path)
    tpl_dir = tmp_path / "tpl"
    extract_template(bundle_dir, tpl_dir)
    out_dir = tmp_path / "out"
    bundle, unused = instantiate_template(tpl_dir, out_dir, {})
    assert unused == []
    original = load_bundle(bundle_dir)
    for app in original.apps:
        assert bundle.app_by_slug(app.slug).dsl == app.dsl


def test_instantiate_with_overrides(tmp_path):
    bundle_dir = _make_bundle(tmp_path)
    tpl_dir = tmp_path / "tpl"
    extract_template(bundle_dir, tpl_dir)
    out_dir = tmp_path / "out"
    bundle, unused = instantiate_template(tpl_dir, out_dir, {
        "customer-service.app_name": "和顺塑业客服",
        "env.KB_ENDPOINT": "https://kb.heshun.example.com",
    })
    assert unused == []
    app = bundle.app_by_slug("customer-service")
    assert app.dsl["app"]["name"] == "和顺塑业客服"


def test_instantiate_unused_override_warns(tmp_path):
    bundle_dir = _make_bundle(tmp_path)
    tpl_dir = tmp_path / "tpl"
    extract_template(bundle_dir, tpl_dir)
    _, unused = instantiate_template(tpl_dir, tmp_path / "out", {"no.such.var": "x"})
    assert unused == ["no.such.var"]


def test_load_template_rejects_non_template(tmp_path):
    with pytest.raises(TemplateError):
        load_template(tmp_path)
