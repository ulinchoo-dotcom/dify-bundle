"""两个 bundle 的差异对比。

回答 FDE 现场最常见的问题：「客户环境现在跑的，和我仓库里这版，差在哪？」

对比三个层面：
1. 应用集合：谁多了、谁少了
2. 应用内部：DSL 扁平化后逐字段比（added / removed / changed）
3. 环境与插件：env 变量、插件版本的增改删

脱敏值天然可比：同一个真实值 → 同一个占位符，变了 → 占位符也变。
所以「密钥换了」能被 diff 看见，但 diff 里永远看不见密钥本身。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Bundle


@dataclass
class FieldChange:
    path: str
    kind: str  # "added" | "removed" | "changed"
    old: Any = None
    new: Any = None


@dataclass
class BundleDiff:
    name_a: str
    name_b: str
    apps_added: list[str] = field(default_factory=list)
    apps_removed: list[str] = field(default_factory=list)
    apps_changed: dict[str, list[FieldChange]] = field(default_factory=dict)
    env_changes: list[FieldChange] = field(default_factory=list)
    plugin_changes: list[FieldChange] = field(default_factory=list)

    @property
    def has_differences(self) -> bool:
        return bool(self.apps_added or self.apps_removed or self.apps_changed
                    or self.env_changes or self.plugin_changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "a": self.name_a, "b": self.name_b,
            "apps_added": self.apps_added,
            "apps_removed": self.apps_removed,
            "apps_changed": {
                slug: [vars(c) for c in changes] for slug, changes in self.apps_changed.items()
            },
            "env_changes": [vars(c) for c in self.env_changes],
            "plugin_changes": [vars(c) for c in self.plugin_changes],
            "has_differences": self.has_differences,
        }


def _flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    """把嵌套结构拍平成 {点分路径: 标量}。列表按下标展开。"""
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = node
    return out


def diff_flat(a: dict[str, Any], b: dict[str, Any]) -> list[FieldChange]:
    changes: list[FieldChange] = []
    for path in sorted(a.keys() - b.keys()):
        changes.append(FieldChange(path, "removed", old=a[path]))
    for path in sorted(b.keys() - a.keys()):
        changes.append(FieldChange(path, "added", new=b[path]))
    for path in sorted(a.keys() & b.keys()):
        if a[path] != b[path]:
            changes.append(FieldChange(path, "changed", old=a[path], new=b[path]))
    return changes


def diff_bundles(a: Bundle, b: Bundle) -> BundleDiff:
    diff = BundleDiff(name_a=a.name, name_b=b.name)

    slugs_a = {app.slug for app in a.apps}
    slugs_b = {app.slug for app in b.apps}
    diff.apps_added = sorted(slugs_b - slugs_a)
    diff.apps_removed = sorted(slugs_a - slugs_b)

    for slug in sorted(slugs_a & slugs_b):
        app_a, app_b = a.app_by_slug(slug), b.app_by_slug(slug)
        changes = diff_flat(_flatten(app_a.dsl), _flatten(app_b.dsl))
        if changes:
            diff.apps_changed[slug] = changes

    env_a = {v.name: v.value for v in a.env}
    env_b = {v.name: v.value for v in b.env}
    diff.env_changes = diff_flat(env_a, env_b)

    plg_a = {p.plugin_id: p.version for p in a.plugins}
    plg_b = {p.plugin_id: p.version for p in b.plugins}
    diff.plugin_changes = diff_flat(plg_a, plg_b)

    return diff
