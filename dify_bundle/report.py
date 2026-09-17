"""HTML 报告渲染（Jinja2）。报告落文件，终端只打摘要。"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .checker import Finding
from .differ import BundleDiff
from .models import Bundle

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def write_check_report(bundle: Bundle, findings: list[Finding], out: Path) -> None:
    html = _env.get_template("check.html.j2").render(
        bundle=bundle,
        errors=[f for f in findings if f.level == "error"],
        warnings=[f for f in findings if f.level == "warning"],
    )
    out.write_text(html, encoding="utf-8")


def write_diff_report(diff: BundleDiff, out: Path) -> None:
    html = _env.get_template("diff.html.j2").render(diff=diff)
    out.write_text(html, encoding="utf-8")
