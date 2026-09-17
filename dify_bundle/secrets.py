"""敏感值脱敏与还原——本工具存在的核心理由。

规则：真实密钥**永远不进 bundle**。导出时替换成占位符，映射关系写进
secrets.local.yaml（自动 gitignore）；导入时凭映射或环境变量还原。

识别两条路，只信「键名」和「值形态」，不做语义猜测：
1. 键名命中：key / secret / token / password / credential（大小写不敏感）
2. 值形态命中：sk-xxx、JWT（eyJ 开头三段）、32 位以上纯 hex、AWS AKIA 前缀
占位符形如 ${SECRET_a1b2c3d4}，后缀是值的 sha1 前 8 位——
同一个值永远得到同一个占位符，diff 两个 bundle 时占位符可比、不会误报。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PLACEHOLDER_RE = re.compile(r"\$\{SECRET_([0-9a-f]{8})\}")
_KEY_NAME_RE = re.compile(r"(?i)(api[_-]?key|secret|token|password|credential|private[_-]?key)")
_VALUE_PATTERNS = (
    re.compile(r"^sk-[A-Za-z0-9_-]{16,}$"),                 # OpenAI 风格
    re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"),  # JWT
    re.compile(r"^AKIA[0-9A-Z]{16}$"),                       # AWS AccessKey
    re.compile(r"^[0-9a-f]{32,}$"),                          # 长 hex（md5/sha1/私钥片段）
    re.compile(r"^ghp_[A-Za-z0-9]{20,}$"),                   # GitHub PAT
)


def placeholder_of(value: str) -> str:
    return f"${{SECRET_{hashlib.sha1(value.encode('utf-8')).hexdigest()[:8]}}}"


def is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and PLACEHOLDER_RE.fullmatch(value) is not None


def looks_secret_key(key: str) -> bool:
    return bool(_KEY_NAME_RE.search(key))


def looks_secret_value(value: Any) -> bool:
    return isinstance(value, str) and any(p.match(value) for p in _VALUE_PATTERNS)


@dataclass
class SecretMap:
    """占位符 → 真实值。只存本地，不进 bundle、不进 git。"""

    entries: dict[str, str] = field(default_factory=dict)  # placeholder -> real value

    def remember(self, value: str) -> str:
        """登记一个真实值，返回它的占位符。"""
        ph = placeholder_of(value)
        self.entries[ph] = value
        return ph

    def resolve(self, placeholder: str) -> str | None:
        return self.entries.get(placeholder)

    def save(self, path: Path) -> None:
        path.write_text(
            "# 本文件含真实密钥，已被 .gitignore 排除，绝不要提交\n"
            + yaml.safe_dump(self.entries, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "SecretMap":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(entries=dict(data))


def redact_tree(node: Any, smap: SecretMap, *, key_hint: str = "") -> Any:
    """递归脱敏：命中键名或值形态的字符串替换为占位符，其余原样返回。"""
    if isinstance(node, dict):
        return {k: redact_tree(v, smap, key_hint=str(k)) for k, v in node.items()}
    if isinstance(node, list):
        return [redact_tree(item, smap, key_hint=key_hint) for item in node]
    if isinstance(node, str) and (looks_secret_key(key_hint) or looks_secret_value(node)):
        # 已经是占位符就不要再脱敏一次（幂等）
        return node if is_placeholder(node) else smap.remember(node)
    return node


def restore_tree(node: Any, smap: SecretMap) -> tuple[Any, list[str]]:
    """递归还原：占位符 → 真实值。返回 (还原后的树, 未解析的占位符列表)。"""
    unresolved: list[str] = []

    def walk(n: Any) -> Any:
        if isinstance(n, dict):
            return {k: walk(v) for k, v in n.items()}
        if isinstance(n, list):
            return [walk(i) for i in n]
        if is_placeholder(n):
            real = smap.resolve(n)
            if real is None:
                unresolved.append(n)
                return n
            return real
        return n

    return walk(node), unresolved
