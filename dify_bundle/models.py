"""核心数据结构。

设计原则：bundle 是「文件系统里的一堆 YAML」，模型只是它们的内存视图。
- 磁盘格式是唯一事实来源，模型不藏任何磁盘上没有的状态；
- 所有模型都能 round-trip：load → dump 之后字节级一致（脱敏值除外）；
- 敏感值在磁盘上永远以占位符存在，真实值只活在 secrets.local.yaml（被 gitignore）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BUNDLE_FORMAT_VERSION = "1"
MANIFEST_FILE = "bundle.yaml"
ENV_FILE = "env.yaml"
PLUGINS_FILE = "plugins.yaml"
SECRET_MAP_FILE = "secrets.local.yaml"
APPS_DIR = "apps"

SUPPORTED_DSL_VERSIONS = ("0.1.5", "0.2.0", "0.3.0", "0.4.0")


@dataclass
class EnvVar:
    """一个环境变量声明。secret=True 时 value 存的是占位符。"""

    name: str
    value: str = ""
    secret: bool = False
    description: str = ""


@dataclass
class PluginDep:
    """一个插件依赖。version 为空表示未钉版本——check 会拦。"""

    plugin_id: str
    version: str = ""


@dataclass
class AppEntry:
    """一个 Dify 应用：slug 是文件名，dsl 是脱敏后的完整 DSL 字典。"""

    slug: str
    name: str
    mode: str = ""
    dsl_version: str = ""
    dsl: dict[str, Any] = field(default_factory=dict)


@dataclass
class Bundle:
    """一套交付配置：若干应用 + 环境变量 + 插件依赖。"""

    name: str
    apps: list[AppEntry] = field(default_factory=list)
    env: list[EnvVar] = field(default_factory=list)
    plugins: list[PluginDep] = field(default_factory=list)
    source: str = ""
    created_at: str = ""
    format_version: str = BUNDLE_FORMAT_VERSION

    def app_by_slug(self, slug: str) -> AppEntry | None:
        for app in self.apps:
            if app.slug == slug:
                return app
        return None
