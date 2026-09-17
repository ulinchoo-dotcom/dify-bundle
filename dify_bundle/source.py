"""配置来源：bundle 从哪来、到哪去。

LocalSource / LocalTarget：文件系统——一个目录里放着 Dify 导出的若干 DSL YAML，
这是离线可测、可演示的通路，也是 FDE 现场最常见的起点（客户给你一个 U 盘）。

DifyApiSource：直连 Dify 实例的 Console API。
注意：Dify 的 Console API 未完全公开文档化，端点按社区通行版本实现，
**未对真实实例做过验证**——用前先 --help 看参数，连不上就用 DSL 文件导出那条路。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import yaml

from .dsl import DslError, load_dsl
from .models import EnvVar, PluginDep


class Source(Protocol):
    def list_dsl(self) -> dict[str, str]: ...      # slug_hint -> DSL YAML 文本
    def extra_env(self) -> list[EnvVar]: ...        # 来源自带的额外环境变量声明
    def extra_plugins(self) -> list[PluginDep]: ...  # 来源自带的插件依赖
    def describe(self) -> str: ...


@dataclass
class LocalSource:
    """读一个目录：*.yaml/*.yml 里 kind: app 的当 DSL，env.yaml / plugins.yaml 当补充声明。"""

    root: Path

    def list_dsl(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for path in sorted(self.root.glob("*.y*ml")):
            if path.name in ("env.yaml", "plugins.yaml", "bundle.yaml", "secrets.local.yaml"):
                continue
            text = path.read_text(encoding="utf-8")
            try:
                load_dsl(text, source=str(path))
            except DslError:
                continue  # 不是应用导出的 YAML 就跳过，不当错误
            out[path.stem] = text
        if not out:
            raise DslError(f"{self.root} 下没有找到任何 Dify 应用导出（kind: app 的 YAML）")
        return out

    def extra_env(self) -> list[EnvVar]:
        path = self.root / "env.yaml"
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return [
            EnvVar(
                name=str(k),
                value="" if v is None else str(v),
                secret=False,
                description="",
            )
            for k, v in (data.get("variables") or {}).items()
        ]

    def extra_plugins(self) -> list[PluginDep]:
        path = self.root / "plugins.yaml"
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return [
            PluginDep(plugin_id=str(p.get("id", "")), version=str(p.get("version", "")))
            for p in (data.get("plugins") or [])
            if isinstance(p, dict) and p.get("id")
        ]

    def describe(self) -> str:
        return f"local:{self.root}"


@dataclass
class DifyApiSource:
    """直连 Dify Console API 拉应用 DSL。⚠️ 未对真实实例验证过。"""

    base_url: str
    api_key: str  # Console 的 access token（不是应用的 API Key）

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,
        )

    def list_dsl(self) -> dict[str, str]:
        with self._client() as c:
            r = c.get("/console/api/apps", params={"limit": 100})
            r.raise_for_status()
            apps = r.json().get("data", [])
            out: dict[str, str] = {}
            for app in apps:
                app_id = app.get("id")
                if not app_id:
                    continue
                r = c.get(f"/console/api/apps/{app_id}/export")
                r.raise_for_status()
                out[str(app_id)] = r.text
            if not out:
                raise DslError("实例上没有可导出的应用")
            return out

    def extra_env(self) -> list[EnvVar]:
        return []

    def extra_plugins(self) -> list[PluginDep]:
        return []

    def describe(self) -> str:
        return f"dify:{self.base_url}"
