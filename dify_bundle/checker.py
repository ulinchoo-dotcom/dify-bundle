"""导入前校验——在客户环境翻车之前，先在本地翻车。

每条规则是一个纯函数：Bundle + 可选 SecretMap → list[Finding]。
error 会让 check 以退出码 1 结束；warning 只提示。

规则清单（rule id 稳定，可在 CI 里按 id 忽略）：
- dsl-version-unsupported   DSL 版本不在支持列表
- env-referenced-undeclared DSL 里 {{#env.X#}} 引用了未声明的变量
- secret-placeholder-unresolved  占位符在密钥映射里找不到真实值（导入必炸）
- plugin-unpinned           插件依赖没钉版本
- app-name-duplicate        两个应用同名（导入 Dify 会互相覆盖）
"""

from __future__ import annotations

from dataclasses import dataclass

from .dsl import referenced_env_names
from .models import SUPPORTED_DSL_VERSIONS, Bundle
from .secrets import PLACEHOLDER_RE, SecretMap


@dataclass
class Finding:
    level: str  # "error" | "warning"
    rule: str
    message: str
    location: str = ""


def check_bundle(bundle: Bundle, smap: SecretMap | None = None) -> list[Finding]:
    findings: list[Finding] = []
    declared = {v.name for v in bundle.env}
    seen_names: dict[str, str] = {}  # app name -> slug

    for app in bundle.apps:
        loc = f"apps/{app.slug}.yaml"

        if app.dsl_version and app.dsl_version not in SUPPORTED_DSL_VERSIONS:
            findings.append(Finding(
                "error", "dsl-version-unsupported",
                f"DSL 版本 {app.dsl_version} 不在支持列表 {list(SUPPORTED_DSL_VERSIONS)}", loc))

        for name in sorted(referenced_env_names(app.dsl) - declared):
            findings.append(Finding(
                "error", "env-referenced-undeclared",
                f"DSL 引用了环境变量 {name}，但 env.yaml 没有声明", loc))

        if app.name in seen_names:
            findings.append(Finding(
                "error", "app-name-duplicate",
                f"应用名 {app.name!r} 与 {seen_names[app.name]} 重复，导入会互相覆盖", loc))
        else:
            seen_names[app.name] = app.slug

        if smap is not None:
            for ph in sorted(_placeholders_in(app.dsl)):
                if smap.resolve(ph) is None:
                    findings.append(Finding(
                        "error", "secret-placeholder-unresolved",
                        f"占位符 {ph} 在密钥映射里没有对应的真实值", loc))

    if smap is not None:
        for v in bundle.env:
            if v.secret and PLACEHOLDER_RE.fullmatch(v.value) and smap.resolve(v.value) is None:
                findings.append(Finding(
                    "error", "secret-placeholder-unresolved",
                    f"环境变量 {v.name} 的占位符 {v.value} 没有对应的真实值", "env.yaml"))

    for p in bundle.plugins:
        if not p.version:
            findings.append(Finding(
                "warning", "plugin-unpinned",
                f"插件 {p.plugin_id} 没有钉版本，客户环境可能装到不兼容的新版", "plugins.yaml"))

    return findings


def _placeholders_in(node: object) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        for v in node.values():
            out |= _placeholders_in(v)
    elif isinstance(node, list):
        for v in node:
            out |= _placeholders_in(v)
    elif isinstance(node, str):
        out.update(m.group(0) for m in PLACEHOLDER_RE.finditer(node))
    return out
