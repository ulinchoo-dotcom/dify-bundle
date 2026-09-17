"""脱敏是卖点，测得最狠：识别规则、幂等、占位符稳定性、还原。"""

from dify_bundle.secrets import (
    SecretMap,
    is_placeholder,
    looks_secret_key,
    looks_secret_value,
    placeholder_of,
    redact_tree,
    restore_tree,
)


def test_key_name_detection():
    assert looks_secret_key("api_key")
    assert looks_secret_key("OPENAI_API_KEY")
    assert looks_secret_key("access-token")
    assert looks_secret_key("dbPassword")
    assert not looks_secret_key("name")
    assert not looks_secret_key("keyboard")  # 子串 "key" 在词尾，不应命中 api_key 模式…
    # keyboard 命中了 key?——用例固定下来：当前实现 keyboard 不命中（要求 key 前缀或分隔符）
    # 若未来改规则，这里会红，提醒别误伤正常字段


def test_value_pattern_detection():
    assert looks_secret_value("sk-a1b2c3d4e5f6g7h8i9j0")
    assert looks_secret_value("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c")
    assert looks_secret_value("AKIAIOSFODNN7EXAMPLE")
    assert looks_secret_value("9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c")
    assert looks_secret_value("ghp_" + "Ab3" * 12)  # 拼接构造，避免仓库里出现真实形态的 token
    assert not looks_secret_value("https://example.com")
    assert not looks_secret_value("普通中文文本")
    assert not looks_secret_value(12345)


def test_placeholder_is_deterministic():
    a = placeholder_of("sk-same-value-000000000000")
    b = placeholder_of("sk-same-value-000000000000")
    assert a == b
    assert is_placeholder(a)
    # 不同值 → 不同占位符
    assert placeholder_of("sk-other-11111111111111") != a


def test_redact_tree_by_key_name():
    smap = SecretMap()
    tree = {"config": {"api_key": "not-matching-any-pattern-but-key-name", "title": "正常"}}
    out = redact_tree(tree, smap)
    assert is_placeholder(out["config"]["api_key"])
    assert out["config"]["title"] == "正常"
    assert smap.resolve(out["config"]["api_key"]) == "not-matching-any-pattern-but-key-name"


def test_redact_tree_by_value_pattern():
    smap = SecretMap()
    tree = {"headers": ["Authorization", "sk-abcdef1234567890abcdef"]}
    out = redact_tree(tree, smap)
    assert out["headers"][0] == "Authorization"
    assert is_placeholder(out["headers"][1])


def test_redact_is_idempotent():
    smap = SecretMap()
    tree = {"token": "sk-abcdef1234567890abcdef"}
    once = redact_tree(tree, smap)
    twice = redact_tree(once, smap)
    assert once == twice
    assert len(smap.entries) == 1


def test_restore_roundtrip():
    smap = SecretMap()
    tree = {"a": {"api_key": "sk-real-value-0000000000"}, "b": [1, "x", None]}
    redacted = redact_tree(tree, smap)
    restored, unresolved = restore_tree(redacted, smap)
    assert restored == tree
    assert unresolved == []


def test_restore_unresolved():
    out, unresolved = restore_tree({"k": "${SECRET_deadbeef}"}, SecretMap())
    assert out == {"k": "${SECRET_deadbeef}"}
    assert unresolved == ["${SECRET_deadbeef}"]


def test_secret_map_save_load(tmp_path):
    smap = SecretMap()
    ph = smap.remember("sk-persist-me-000000000000")
    path = tmp_path / "secrets.local.yaml"
    smap.save(path)
    text = path.read_text(encoding="utf-8")
    assert "绝不要提交" in text  # 文件头有警告
    loaded = SecretMap.load(path)
    assert loaded.resolve(ph) == "sk-persist-me-000000000000"
