"""bundle 的产出与读取。

bundle 目录格式（全部 YAML，可直接进 git）：

    my-bundle/
    ├── bundle.yaml          # 清单：格式版本、名字、来源、创建时间、应用列表
    ├── apps/<slug>.yaml     # 每个应用的 DSL（已脱敏，键序固定）
    ├── env.yaml             # 环境变量声明（secret 的值是占位符）
    ├── plugins.yaml         # 插件依赖（id + version）
    ├── secrets.local.yaml   # 占位符→真实值（.gitignore，绝不进 git）
    └── .gitignore           # 自动写入，排除 secrets.local.yaml

导出时所有 DSL 和 env 值都过一遍 secrets.redact_tree；
读取（load_bundle）只读磁盘，不做任何还原。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from .dsl import app_entry_of, dump_dsl, env_vars_of, load_dsl, slugify
from .models import (
    APPS_DIR,
    BUNDLE_FORMAT_VERSION,
    ENV_FILE,
    MANIFEST_FILE,
    PLUGINS_FILE,
    SECRET_MAP_FILE,
    AppEntry,
    Bundle,
    EnvVar,
    PluginDep,
)
from .secrets import SecretMap, is_placeholder, redact_tree
from .source import Source

GITIGNORE = "# 真实密钥映射，绝不提交\nsecrets.local.yaml\n"


class BundleError(Exception):
    """bundle 目录损坏或缺文件。"""


def export_bundle(source: Source, out_dir: Path, *, name: str = "") -> tuple[Bundle, SecretMap]:
    """从 source 导出一份 bundle 到 out_dir。返回 (bundle, 密钥映射)。"""
    smap = SecretMap()
    raw = source.list_dsl()

    apps: list[AppEntry] = []
    used_slugs: set[str] = set()
    for hint, text in raw.items():
        dsl = load_dsl(text, source=hint)
        dsl = redact_tree(dsl, smap)
        entry = app_entry_of(dsl, slug_hint=slugify(hint))
        if entry.slug in used_slugs:  # 同名应用 → 加序号，不覆盖
            i = 2
            while f"{entry.slug}-{i}" in used_slugs:
                i += 1
            entry.slug = f"{entry.slug}-{i}"
        used_slugs.add(entry.slug)
        apps.append(entry)

    # 环境变量：DSL 里声明的 + 来源补充的，按名字去重，值脱敏
    env: dict[str, EnvVar] = {}
    for entry in apps:
        for v in env_vars_of(entry.dsl):
            env.setdefault(v.name, v)
    for v in source.extra_env():
        env.setdefault(v.name, v)
    env_list: list[EnvVar] = []
    for v in sorted(env.values(), key=lambda x: x.name):
        if v.value:
            ph = redact_tree(v.value, smap, key_hint=v.name)
            # 值是占位符 = 原来是敏感值（DSL 里已脱敏的也算）
            env_list.append(EnvVar(name=v.name, value=ph, secret=is_placeholder(ph), description=v.description))
        else:
            env_list.append(v)

    bundle = Bundle(
        name=name or f"bundle-{datetime.now(timezone.utc):%Y%m%d}",
        apps=apps,
        env=env_list,
        plugins=source.extra_plugins(),
        source=source.describe(),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    save_bundle(bundle, out_dir)
    if smap.entries:
        smap.save(out_dir / SECRET_MAP_FILE)
    return bundle, smap


def save_bundle(bundle: Bundle, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / APPS_DIR).mkdir(exist_ok=True)

    manifest = {
        "format_version": BUNDLE_FORMAT_VERSION,
        "name": bundle.name,
        "source": bundle.source,
        "created_at": bundle.created_at,
        "apps": [{"slug": a.slug, "name": a.name, "mode": a.mode, "dsl_version": a.dsl_version} for a in bundle.apps],
    }
    (out_dir / MANIFEST_FILE).write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=True), encoding="utf-8")

    for app in bundle.apps:
        (out_dir / APPS_DIR / f"{app.slug}.yaml").write_text(dump_dsl(app.dsl), encoding="utf-8")

    env_doc = {
        "variables": {
            v.name: {"value": v.value, "secret": v.secret, "description": v.description}
            for v in bundle.env
        }
    }
    (out_dir / ENV_FILE).write_text(yaml.safe_dump(env_doc, allow_unicode=True, sort_keys=True), encoding="utf-8")

    plugins_doc = {"plugins": [{"id": p.plugin_id, "version": p.version} for p in bundle.plugins]}
    (out_dir / PLUGINS_FILE).write_text(yaml.safe_dump(plugins_doc, allow_unicode=True, sort_keys=True), encoding="utf-8")

    (out_dir / ".gitignore").write_text(GITIGNORE, encoding="utf-8")


def load_bundle(bundle_dir: Path) -> Bundle:
    manifest_path = bundle_dir / MANIFEST_FILE
    if not manifest_path.exists():
        raise BundleError(f"{bundle_dir} 不是 bundle 目录（缺 {MANIFEST_FILE}）")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if str(manifest.get("format_version", "")) != BUNDLE_FORMAT_VERSION:
        raise BundleError(f"不支持的 bundle 格式版本: {manifest.get('format_version')!r}")

    apps: list[AppEntry] = []
    apps_dir = bundle_dir / APPS_DIR
    for path in sorted(apps_dir.glob("*.y*ml")) if apps_dir.exists() else []:
        dsl = load_dsl(path.read_text(encoding="utf-8"), source=str(path))
        apps.append(app_entry_of(dsl, slug_hint=path.stem))

    env_doc = yaml.safe_load((bundle_dir / ENV_FILE).read_text(encoding="utf-8")) if (bundle_dir / ENV_FILE).exists() else {}
    env = [
        EnvVar(
            name=str(k),
            value=str((v or {}).get("value", "")),
            secret=bool((v or {}).get("secret", False)),
            description=str((v or {}).get("description", "")),
        )
        for k, v in ((env_doc or {}).get("variables") or {}).items()
    ]

    plugins_doc = yaml.safe_load((bundle_dir / PLUGINS_FILE).read_text(encoding="utf-8")) if (bundle_dir / PLUGINS_FILE).exists() else {}
    plugins = [
        PluginDep(plugin_id=str(p.get("id", "")), version=str(p.get("version", "")))
        for p in ((plugins_doc or {}).get("plugins") or [])
        if isinstance(p, dict)
    ]

    return Bundle(
        name=str(manifest.get("name", bundle_dir.name)),
        apps=apps,
        env=env,
        plugins=plugins,
        source=str(manifest.get("source", "")),
        created_at=str(manifest.get("created_at", "")),
    )
