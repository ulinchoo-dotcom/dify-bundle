"""行业模板：把一次交付沉淀成下次能复用的资产。

方向 D 的「产品视角」落点：bundle 是「这一个客户的配置」，
template 是「这一类客户的配置」——把客户特定值抽成变量：

- app.name / app.description      → {{ <slug>.app_name }} / {{ <slug>.app_description }}
- 独立 URL 标量                   → {{ <slug>.url_1 }} …
- 非 secret 的环境变量值          → {{ env.<NAME> }}
- secret 值保持占位符不动（模板里也不该有真实密钥）

template.yaml 记录每个变量的默认值（= 抽取时的原值）和说明。
instantiate 反向填充：缺值报错、多出未用的 --set 报警告。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .dsl import dump_dsl
from .exporter import load_bundle, save_bundle
from .models import APPS_DIR, ENV_FILE, MANIFEST_FILE, Bundle
from .secrets import is_placeholder

TEMPLATE_FILE = "template.yaml"
_URL_RE = re.compile(r"^https?://\S+$")
_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


class TemplateError(Exception):
    """模板损坏或实例化缺变量。"""


@dataclass
class TemplateVar:
    name: str
    default: str = ""
    description: str = ""


@dataclass
class Template:
    name: str
    vars: list[TemplateVar] = field(default_factory=list)
    description: str = ""


def _variabilize(node: Any, variables: dict[str, TemplateVar], *, slug: str) -> Any:
    """递归处理 DSL：命中规则的值换成 {{ 变量 }}，原值登记为默认值。"""
    if isinstance(node, dict):
        return {k: _variabilize(v, variables, slug=slug) for k, v in node.items()}
    if isinstance(node, list):
        return [_variabilize(v, variables, slug=slug) for v in node]
    if isinstance(node, str) and node and not is_placeholder(node) and _URL_RE.match(node):
        i = 1
        while f"{slug}.url_{i}" in variables:
            i += 1
        name = f"{slug}.url_{i}"
        variables[name] = TemplateVar(name=name, default=node, description=f"{slug} 引用的外部地址")
        return "{{ " + name + " }}"
    return node


def extract_template(bundle_dir: Path, out_dir: Path, *, name: str = "", description: str = "") -> Template:
    """把一个 bundle 抽象成模板目录（与 bundle 同构，值是 {{变量}}）。"""
    bundle = load_bundle(bundle_dir)
    variables: dict[str, TemplateVar] = {}

    for app in bundle.apps:
        app_info = app.dsl.get("app") or {}
        for field_key, var_suffix, desc in (
            ("name", "app_name", "应用显示名"),
            ("description", "app_description", "应用简介"),
        ):
            value = str(app_info.get(field_key) or "")
            if value:
                var = f"{app.slug}.{var_suffix}"
                variables[var] = TemplateVar(name=var, default=value, description=f"{app.slug} 的{desc}")
                app_info[field_key] = "{{ " + var + " }}"
        app.dsl = _variabilize(app.dsl, variables, slug=app.slug)

    for v in bundle.env:
        if v.value and not v.secret and not is_placeholder(v.value):
            var = f"env.{v.name}"
            variables[var] = TemplateVar(name=var, default=v.value, description=f"环境变量 {v.name}")
            v.value = "{{ " + var + " }}"

    tpl = Template(
        name=name or f"{bundle.name}-template",
        vars=sorted(variables.values(), key=lambda x: x.name),
        description=description,
    )

    # 落盘：先按 bundle 写，再补 template.yaml
    save_bundle(bundle, out_dir)
    tpl_doc = {
        "name": tpl.name,
        "description": tpl.description,
        "variables": [
            {"name": v.name, "default": v.default, "description": v.description} for v in tpl.vars
        ],
    }
    (out_dir / TEMPLATE_FILE).write_text(yaml.safe_dump(tpl_doc, allow_unicode=True, sort_keys=True), encoding="utf-8")
    return tpl


def load_template(tpl_dir: Path) -> Template:
    path = tpl_dir / TEMPLATE_FILE
    if not path.exists():
        raise TemplateError(f"{tpl_dir} 不是模板目录（缺 {TEMPLATE_FILE}）")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Template(
        name=str(data.get("name", tpl_dir.name)),
        description=str(data.get("description", "")),
        vars=[
            TemplateVar(name=str(v.get("name", "")), default=str(v.get("default", "")),
                        description=str(v.get("description", "")))
            for v in (data.get("variables") or []) if isinstance(v, dict) and v.get("name")
        ],
    )


def instantiate_template(
    tpl_dir: Path,
    out_dir: Path,
    overrides: dict[str, str],
) -> tuple[Bundle, list[str]]:
    """把模板填回成 bundle。返回 (bundle, 未用到的 override 键)。"""
    tpl = load_template(tpl_dir)
    values = {v.name: v.default for v in tpl.vars}
    known = set(values)
    unused = sorted(set(overrides) - known)
    missing = [k for k, v in values.items() if v == "" and k not in overrides]
    if missing:
        raise TemplateError(f"以下变量没有默认值也没有提供: {missing}")
    values.update({k: v for k, v in overrides.items() if k in known})

    def sub(text: str) -> str:
        return _VAR_RE.sub(lambda m: values.get(m.group(1), m.group(0)), text)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(tpl_dir, out_dir, ignore=shutil.ignore_patterns(TEMPLATE_FILE, "secrets.local.yaml"))

    for path in out_dir.rglob("*.y*ml"):
        path.write_text(sub(path.read_text(encoding="utf-8")), encoding="utf-8")

    return load_bundle(out_dir), unused
