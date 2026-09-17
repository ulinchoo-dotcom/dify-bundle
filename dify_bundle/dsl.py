"""Dify 应用 DSL 的解析与归一化。

Dify 导出的 DSL 是单个 YAML，顶层固定有 app / kind / version / workflow（或 model_config）。
归一化做三件事：
1. 键序固定（dump 时 sort_keys=True），保证 diff 不受字段顺序干扰；
2. 提取 slug：app.name → 小写连字符，非 ASCII 字符按字符落掉，空了就退回 app-N；
3. 抽出 environment_variables 供 env.yaml 汇总。
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from .models import AppEntry, EnvVar


class DslError(Exception):
    """DSL 文件缺关键字段或不是合法的 Dify 导出。"""


def load_dsl(text: str, *, source: str = "") -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise DslError(f"YAML 解析失败 {source}: {e}") from e
    if not isinstance(data, dict) or data.get("kind") != "app" or not isinstance(data.get("app"), dict):
        raise DslError(f"不是合法的 Dify 应用导出 {source}（缺 kind: app 或 app 块）")
    return data


def dump_dsl(dsl: dict[str, Any]) -> str:
    return yaml.safe_dump(dsl, allow_unicode=True, sort_keys=True, width=120)


def slugify(name: str, *, fallback: str = "app") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or fallback


def app_entry_of(dsl: dict[str, Any], *, slug_hint: str = "") -> AppEntry:
    app = dsl["app"]
    name = str(app.get("name", ""))
    return AppEntry(
        slug=slug_hint or slugify(name),
        name=name,
        mode=str(app.get("mode", "")),
        dsl_version=str(dsl.get("version", "")),
        dsl=dsl,
    )


def env_vars_of(dsl: dict[str, Any]) -> list[EnvVar]:
    """从 workflow.environment_variables 抽出变量声明。"""
    workflow = dsl.get("workflow") or {}
    raw = workflow.get("environment_variables") or []
    out: list[EnvVar] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        out.append(
            EnvVar(
                name=str(item["name"]),
                value="" if item.get("value") is None else str(item.get("value")),
                description=str(item.get("description", "")),
            )
        )
    return out


def referenced_env_names(dsl: dict[str, Any]) -> set[str]:
    """DSL 里以 {{#env.XXX#}} 形式引用到的环境变量名。"""
    names: set[str] = set()

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
        elif isinstance(n, str):
            names.update(re.findall(r"\{\{#env\.([A-Za-z0-9_]+)#\}\}", n))

    walk(dsl)
    return names
