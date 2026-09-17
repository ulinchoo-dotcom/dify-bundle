"""把 bundle 重建到目标环境。

流程硬约束：先 check，再还原密钥，最后才写目标。
- check 有 error 且没 --force → 直接拒绝（退出码 1），不产生任何副作用；
- 密钥还原优先级：--secrets 映射文件 > 环境变量 SECRET_<8hex> > 留占位符并报错；
- --dry-run 只打印计划，一个文件都不写。

LocalTarget 把应用重建为一个目录（每应用一个 DSL YAML）——
这条通路可以离线演示「一键重建」的完整语义；
真实 Dify 实例的写入留待 DifyApiTarget（同 source.py 的备注：Console API 未验证）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .checker import check_bundle
from .dsl import dump_dsl
from .models import Bundle
from .secrets import PLACEHOLDER_RE, SecretMap, restore_tree


@dataclass
class ImportPlan:
    apps_to_write: list[str] = field(default_factory=list)   # slug
    unresolved: list[str] = field(default_factory=list)      # 没还原掉的占位符
    blocked_reasons: list[str] = field(default_factory=list)  # check error 摘要


class ImportBlocked(Exception):
    def __init__(self, plan: ImportPlan):
        self.plan = plan
        super().__init__("; ".join(plan.blocked_reasons))


def _env_var_fallback() -> dict[str, str]:
    """环境变量里的 SECRET_<8hex> 也可以供给真实值（CI 场景）。"""
    prefix = "SECRET_"
    out: dict[str, str] = {}
    for k, v in os.environ.items():
        if k.startswith(prefix) and PLACEHOLDER_RE.fullmatch(f"${{{k}}}"):
            out[f"${{{k}}}"] = v
    return out


def import_bundle(
    bundle: Bundle,
    target_dir: Path,
    *,
    smap: SecretMap | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> ImportPlan:
    smap = smap or SecretMap()
    # 环境变量兜底：映射文件里没有的，从 SECRET_<8hex> 里补
    merged = SecretMap(entries={**_env_var_fallback(), **smap.entries})

    plan = ImportPlan()
    findings = check_bundle(bundle, merged)
    errors = [f for f in findings if f.level == "error"]
    if errors and not force:
        plan.blocked_reasons = [f"[{f.rule}] {f.message} ({f.location})" for f in errors]
        raise ImportBlocked(plan)

    for app in bundle.apps:
        restored, unresolved = restore_tree(app.dsl, merged)
        plan.unresolved.extend(unresolved)
        plan.apps_to_write.append(app.slug)
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / f"{app.slug}.yaml").write_text(dump_dsl(restored), encoding="utf-8")

    # env 里没还原的 secret 值也算
    for v in bundle.env:
        if v.secret and PLACEHOLDER_RE.fullmatch(v.value) and merged.resolve(v.value) is None:
            plan.unresolved.append(v.value)
    plan.unresolved = sorted(set(plan.unresolved))
    return plan
