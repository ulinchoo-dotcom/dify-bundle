"""命令行入口。

与 dify-eval 同一套契约：
- 退出码可信：0 正常；1 校验不过 / 有差异 / 导入被拦；2 用法或文件错误；
- 报告落文件，终端只打摘要；
- 密钥不进命令行：API token 走 DIFY_CONSOLE_TOKEN 环境变量。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .checker import check_bundle
from .differ import diff_bundles
from .dsl import DslError
from .exporter import BundleError, export_bundle, load_bundle
from .importer import ImportBlocked, import_bundle
from .models import SECRET_MAP_FILE
from .report import write_check_report, write_diff_report
from .secrets import SecretMap
from .source import DifyApiSource, LocalSource
from .templater import TemplateError, extract_template, instantiate_template


def _fail(msg: str, code: int = 2) -> int:
    print(f"错误: {msg}", file=sys.stderr)
    return code


def _load_secret_map(bundle_dir: Path, explicit: str) -> SecretMap | None:
    if explicit:
        return SecretMap.load(Path(explicit))
    default = bundle_dir / SECRET_MAP_FILE
    return SecretMap.load(default) if default.exists() else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dify-bundle",
        description="把 Dify 应用打成可版本化的交付包",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ex = sub.add_parser("export", help="从 Dify 实例或 DSL 目录导出交付包")
    ex.add_argument("--source", required=True, help="DSL 文件目录；或以 https:// 开头的 Dify 实例地址")
    ex.add_argument("--out", required=True, help="bundle 输出目录")
    ex.add_argument("--name", default="", help="bundle 名称（默认 bundle-YYYYMMDD）")

    ck = sub.add_parser("check", help="导入前校验：在客户环境翻车之前先本地翻车")
    ck.add_argument("bundle", help="bundle 目录")
    ck.add_argument("--secrets", default="", help="密钥映射文件（默认读 bundle 里的 secrets.local.yaml）")
    ck.add_argument("--html", default="", help="HTML 校验报告输出路径")

    df = sub.add_parser("diff", help="对比两份交付包（有差异时退出码 1，可挂 CI）")
    df.add_argument("a", help="bundle 目录 A")
    df.add_argument("b", help="bundle 目录 B")
    df.add_argument("--html", default="", help="HTML 差异报告输出路径")
    df.add_argument("--json-out", default="", help="差异结果 JSON 输出路径")

    im = sub.add_parser("import", help="把交付包重建到目标目录（先校验，再还原密钥）")
    im.add_argument("bundle", help="bundle 目录")
    im.add_argument("--target", required=True, help="重建输出目录")
    im.add_argument("--secrets", default="", help="密钥映射文件（默认读 bundle 里的 secrets.local.yaml）")
    im.add_argument("--dry-run", action="store_true", help="只打印计划，不写任何文件")
    im.add_argument("--force", action="store_true", help="校验有错误也强制执行")

    tp = sub.add_parser("template", help="把交付包抽象成行业模板（客户特定值 → 变量）")
    tp.add_argument("bundle", help="bundle 目录")
    tp.add_argument("--out", required=True, help="模板输出目录")
    tp.add_argument("--name", default="", help="模板名称")
    tp.add_argument("--description", default="", help="模板说明")

    it = sub.add_parser("instantiate", help="用模板生成一份新的交付包")
    it.add_argument("template", help="模板目录")
    it.add_argument("--out", required=True, help="bundle 输出目录")
    it.add_argument("--set", dest="overrides", action="append", default=[],
                    help="变量赋值 key=value，可重复；不提供的用默认值")

    return parser


def _export_command(args: argparse.Namespace) -> int:
    if args.source.startswith("https://") or args.source.startswith("http://"):
        token = os.environ.get("DIFY_CONSOLE_TOKEN", "")
        if not token:
            return _fail("直连实例需要 DIFY_CONSOLE_TOKEN 环境变量（Console access token）")
        source = DifyApiSource(base_url=args.source, api_key=token)
    else:
        root = Path(args.source)
        if not root.is_dir():
            return _fail(f"来源目录不存在: {root}")
        source = LocalSource(root=root)
    try:
        bundle, smap = export_bundle(source, Path(args.out), name=args.name)
    except DslError as e:
        return _fail(str(e))
    print(f"导出完成: {args.out}")
    print(f"  应用 {len(bundle.apps)} 个: {', '.join(a.slug for a in bundle.apps)}")
    print(f"  环境变量 {len(bundle.env)} 个（secret {sum(1 for v in bundle.env if v.secret)} 个）")
    if smap.entries:
        print(f"  已脱敏 {len(smap.entries)} 个敏感值 → secrets.local.yaml（已 gitignore，勿提交）")
    return 0


def _check_command(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle)
    try:
        bundle = load_bundle(bundle_dir)
    except (BundleError, DslError) as e:
        return _fail(str(e))
    try:
        smap = _load_secret_map(bundle_dir, args.secrets)
    except Exception as e:
        return _fail(f"密钥映射读取失败: {e}")
    findings = check_bundle(bundle, smap)
    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]
    for f in findings:
        tag = "ERROR" if f.level == "error" else "WARN "
        print(f"  {tag} [{f.rule}] {f.message}" + (f" ({f.location})" if f.location else ""))
    if args.html:
        write_check_report(bundle, findings, Path(args.html))
        print(f"报告: {args.html}")
    print(f"校验: {len(errors)} 错误 / {len(warnings)} 警告 → {'可交付' if not errors else '不可交付'}")
    return 1 if errors else 0


def _diff_command(args: argparse.Namespace) -> int:
    try:
        a, b = load_bundle(Path(args.a)), load_bundle(Path(args.b))
    except (BundleError, DslError) as e:
        return _fail(str(e))
    diff = diff_bundles(a, b)
    print(f"{diff.name_a} vs {diff.name_b}:")
    print(f"  应用 +{len(diff.apps_added)} / -{len(diff.apps_removed)} / 变更 {len(diff.apps_changed)}")
    print(f"  环境变量变更 {len(diff.env_changes)}，插件变更 {len(diff.plugin_changes)}")
    for slug, changes in diff.apps_changed.items():
        print(f"  [{slug}] {len(changes)} 处字段变更")
    if args.html:
        write_diff_report(diff, Path(args.html))
        print(f"报告: {args.html}")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(diff.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON: {args.json_out}")
    if not diff.has_differences:
        print("两份交付包完全一致")
        return 0
    return 1


def _import_command(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle)
    try:
        bundle = load_bundle(bundle_dir)
    except (BundleError, DslError) as e:
        return _fail(str(e))
    try:
        smap = _load_secret_map(bundle_dir, args.secrets)
    except Exception as e:
        return _fail(f"密钥映射读取失败: {e}")
    try:
        plan = import_bundle(
            bundle, Path(args.target),
            smap=smap, dry_run=args.dry_run, force=args.force,
        )
    except ImportBlocked as e:
        print("导入被拦（先用 check 看详情，或 --force 强行导入）:", file=sys.stderr)
        for reason in e.plan.blocked_reasons:
            print(f"  {reason}", file=sys.stderr)
        return 1
    verb = "计划重建" if args.dry_run else "已重建"
    print(f"{verb} {len(plan.apps_to_write)} 个应用 → {args.target}: {', '.join(plan.apps_to_write)}")
    if plan.unresolved:
        print(f"警告: {len(plan.unresolved)} 个占位符没有还原（缺密钥映射或环境变量）", file=sys.stderr)
        return 1
    return 0


def _template_command(args: argparse.Namespace) -> int:
    try:
        tpl = extract_template(
            Path(args.bundle), Path(args.out),
            name=args.name, description=args.description,
        )
    except (BundleError, DslError, TemplateError) as e:
        return _fail(str(e))
    print(f"模板已生成: {args.out}（{tpl.name}）")
    print(f"  抽出 {len(tpl.vars)} 个变量:")
    for v in tpl.vars:
        print(f"    {v.name} = {v.default!r}  # {v.description}")
    return 0


def _instantiate_command(args: argparse.Namespace) -> int:
    overrides: dict[str, str] = {}
    for item in args.overrides:
        if "=" not in item:
            return _fail(f"--set 需要 key=value 形式，收到: {item!r}")
        k, v = item.split("=", 1)
        overrides[k] = v
    try:
        bundle, unused = instantiate_template(Path(args.template), Path(args.out), overrides)
    except TemplateError as e:
        return _fail(str(e))
    for k in unused:
        print(f"警告: --set {k} 不是模板里的变量，已忽略", file=sys.stderr)
    print(f"已生成: {args.out}（{bundle.name}，{len(bundle.apps)} 个应用）")
    return 0


_HANDLERS = {
    "export": _export_command,
    "check": _check_command,
    "diff": _diff_command,
    "import": _import_command,
    "template": _template_command,
    "instantiate": _instantiate_command,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
