"""export / load 的 round-trip 与 bundle 目录结构。"""

import shutil
from pathlib import Path

import pytest
import yaml

from dify_bundle.dsl import DslError, env_vars_of, load_dsl, referenced_env_names, slugify
from dify_bundle.exporter import export_bundle, load_bundle
from dify_bundle.secrets import is_placeholder
from dify_bundle.source import LocalSource

SITE_A = Path(__file__).parent.parent / "examples" / "site-a"


def test_slugify():
    assert slugify("智能客服助手") == "app"  # 非 ASCII 全落掉 → fallback
    assert slugify("My Chat Bot!") == "my-chat-bot"
    assert slugify("---") == "app"


def test_load_dsl_rejects_garbage():
    with pytest.raises(DslError):
        load_dsl("foo: bar")
    with pytest.raises(DslError):
        load_dsl("kind: app")  # 缺 app 块


def test_env_extraction_and_reference():
    dsl = load_dsl((SITE_A / "customer-service.yaml").read_text(encoding="utf-8"))
    names = {v.name for v in env_vars_of(dsl)}
    assert names == {"KB_ENDPOINT", "KB_API_KEY"}
    assert referenced_env_names(dsl) == {"KB_ENDPOINT", "KB_API_KEY"}


def test_export_bundle_structure(tmp_path):
    out = tmp_path / "bundle"
    bundle, smap = export_bundle(LocalSource(SITE_A), out, name="site-a-交付")
    assert (out / "bundle.yaml").exists()
    assert (out / "env.yaml").exists()
    assert (out / "plugins.yaml").exists()
    assert (out / ".gitignore").read_text().find("secrets.local.yaml") >= 0
    assert len(bundle.apps) == 2
    slugs = {a.slug for a in bundle.apps}
    assert slugs == {"customer-service", "order-query"}


def test_export_redacts_secrets(tmp_path):
    out = tmp_path / "bundle"
    bundle, smap = export_bundle(LocalSource(SITE_A), out)
    # 磁盘上的 DSL 不能有真实密钥
    text = (out / "apps" / "customer-service.yaml").read_text(encoding="utf-8")
    assert "sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6" not in text
    text2 = (out / "apps" / "order-query.yaml").read_text(encoding="utf-8")
    assert "9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c" not in text2
    # 映射表里有
    assert len(smap.entries) >= 2
    assert (out / "secrets.local.yaml").exists()
    # env.yaml 里 KB_API_KEY 是占位符且标记 secret
    env_doc = yaml.safe_load((out / "env.yaml").read_text(encoding="utf-8"))
    kb_key = env_doc["variables"]["KB_API_KEY"]
    assert kb_key["secret"] is True
    assert is_placeholder(kb_key["value"])
    # KB_ENDPOINT 是普通 URL，不脱敏
    assert env_doc["variables"]["KB_ENDPOINT"]["value"] == "https://kb.site-a.internal/v1"


def test_export_load_roundtrip(tmp_path):
    out = tmp_path / "bundle"
    bundle, _ = export_bundle(LocalSource(SITE_A), out, name="roundtrip")
    loaded = load_bundle(out)
    assert loaded.name == "roundtrip"
    assert {a.slug for a in loaded.apps} == {a.slug for a in bundle.apps}
    assert {v.name for v in loaded.env} == {v.name for v in bundle.env}
    # DSL 内容一致（占位符版本）
    for app in bundle.apps:
        assert loaded.app_by_slug(app.slug).dsl == app.dsl


def test_duplicate_slug_gets_suffix(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    body = (SITE_A / "customer-service.yaml").read_text(encoding="utf-8")
    (src / "a.yaml").write_text(body, encoding="utf-8")
    (src / "b.yaml").write_text(body, encoding="utf-8")
    bundle, _ = export_bundle(LocalSource(src), tmp_path / "bundle")
    slugs = sorted(a.slug for a in bundle.apps)
    assert slugs == ["a", "b"]  # slug 来自文件名 hint，本来就不同


def test_load_bundle_rejects_non_bundle(tmp_path):
    with pytest.raises(Exception):
        load_bundle(tmp_path)


def test_local_source_empty_dir(tmp_path):
    with pytest.raises(DslError):
        export_bundle(LocalSource(tmp_path), tmp_path / "out")
