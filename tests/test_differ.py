"""diff：字段级对比、增删改、占位符可比性。"""

from pathlib import Path

from dify_bundle.differ import diff_bundles, diff_flat, _flatten
from dify_bundle.exporter import export_bundle, load_bundle
from dify_bundle.source import LocalSource

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_flatten_nested():
    flat = _flatten({"a": {"b": [1, {"c": 2}]}, "d": "x"})
    assert flat == {"a.b[0]": 1, "a.b[1].c": 2, "d": "x"}


def test_diff_flat_kinds():
    changes = diff_flat({"x": 1, "y": 2}, {"y": 3, "z": 4})
    by_path = {c.path: c for c in changes}
    assert by_path["x"].kind == "removed" and by_path["x"].old == 1
    assert by_path["z"].kind == "added" and by_path["z"].new == 4
    assert by_path["y"].kind == "changed" and by_path["y"].old == 2 and by_path["y"].new == 3


def test_identical_bundles_no_diff(tmp_path):
    export_bundle(LocalSource(EXAMPLES / "site-a"), tmp_path / "a")
    export_bundle(LocalSource(EXAMPLES / "site-a"), tmp_path / "b")
    diff = diff_bundles(load_bundle(tmp_path / "a"), load_bundle(tmp_path / "b"))
    assert not diff.has_differences


def test_site_a_vs_site_b(tmp_path):
    """site-b：order-query 删除、faq-bot 新增、customer-service 换了模型和 KB 地址。"""
    export_bundle(LocalSource(EXAMPLES / "site-a"), tmp_path / "a")
    export_bundle(LocalSource(EXAMPLES / "site-b"), tmp_path / "b")
    diff = diff_bundles(load_bundle(tmp_path / "a"), load_bundle(tmp_path / "b"))
    assert diff.apps_added == ["faq-bot"]
    assert diff.apps_removed == ["order-query"]
    assert "customer-service" in diff.apps_changed
    paths = {c.path for c in diff.apps_changed["customer-service"]}
    # 模型从 gpt-4o-mini 换成 gpt-4o 必须被看见
    model_paths = [p for p in paths if "model" in p and "name" in p]
    assert model_paths, f"模型变更没被发现: {paths}"
    # KB_ENDPOINT 变了 → env 层面有变更
    env_paths = {c.path for c in diff.env_changes}
    assert "KB_ENDPOINT" in env_paths


def test_secret_change_visible_but_not_value(tmp_path):
    """密钥换了 diff 能发现（占位符变了），但报告里不出现真实值。"""
    src = tmp_path / "src"
    src.mkdir()
    body = (EXAMPLES / "site-a" / "order-query.yaml").read_text(encoding="utf-8")
    (src / "order-query.yaml").write_text(body, encoding="utf-8")
    export_bundle(LocalSource(src), tmp_path / "a")
    (src / "order-query.yaml").write_text(
        body.replace("9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c", "0123456789abcdef0123456789abcdef"),
        encoding="utf-8")
    export_bundle(LocalSource(src), tmp_path / "b")
    diff = diff_bundles(load_bundle(tmp_path / "a"), load_bundle(tmp_path / "b"))
    assert diff.has_differences
    blob = str(diff.to_dict())
    assert "9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c" not in blob
    assert "0123456789abcdef0123456789abcdef" not in blob
    assert "SECRET_" in blob  # 看到的是占位符


def test_plugin_change(tmp_path):
    export_bundle(LocalSource(EXAMPLES / "site-a"), tmp_path / "a")
    export_bundle(LocalSource(EXAMPLES / "site-b"), tmp_path / "b")
    diff = diff_bundles(load_bundle(tmp_path / "a"), load_bundle(tmp_path / "b"))
    # site-b 没有 plugins.yaml → 插件全 removed
    assert {c.path for c in diff.plugin_changes} == {"langgenius/openai", "langgenius/tavily"}
    assert all(c.kind == "removed" for c in diff.plugin_changes)


def test_to_dict_roundtrip(tmp_path):
    export_bundle(LocalSource(EXAMPLES / "site-a"), tmp_path / "a")
    export_bundle(LocalSource(EXAMPLES / "site-b"), tmp_path / "b")
    d = diff_bundles(load_bundle(tmp_path / "a"), load_bundle(tmp_path / "b")).to_dict()
    assert d["has_differences"] is True
    assert d["apps_added"] == ["faq-bot"]
