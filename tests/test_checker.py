"""校验规则逐条测。"""

from pathlib import Path

from dify_bundle.checker import check_bundle
from dify_bundle.exporter import export_bundle, load_bundle
from dify_bundle.models import AppEntry, Bundle, EnvVar, PluginDep
from dify_bundle.secrets import SecretMap, placeholder_of
from dify_bundle.source import LocalSource

SITE_A = Path(__file__).parent.parent / "examples" / "site-a"


def _rules(findings):
    return {f.rule for f in findings}


def test_clean_bundle_passes():
    bundle = Bundle(
        name="ok",
        apps=[AppEntry(slug="x", name="应用", mode="workflow", dsl_version="0.1.5",
                       dsl={"kind": "app", "app": {"name": "应用"}, "version": "0.1.5"})],
        env=[EnvVar(name="A", value="1")],
        plugins=[PluginDep(plugin_id="p/x", version="1.0")],
    )
    assert check_bundle(bundle) == []


def test_unsupported_dsl_version():
    bundle = Bundle(name="b", apps=[AppEntry(slug="x", name="n", dsl_version="9.9.9", dsl={})])
    findings = check_bundle(bundle)
    assert "dsl-version-unsupported" in _rules(findings)
    assert all(f.level == "error" for f in findings)


def test_env_referenced_undeclared():
    dsl = {"kind": "app", "app": {"name": "n"}, "version": "0.1.5",
           "workflow": {"graph": {"nodes": [{"text": "用 {{#env.MISSING_VAR#}} 这里"}]}}}
    bundle = Bundle(name="b", apps=[AppEntry(slug="x", name="n", dsl_version="0.1.5", dsl=dsl)])
    findings = check_bundle(bundle)
    assert "env-referenced-undeclared" in _rules(findings)
    msg = [f for f in findings if f.rule == "env-referenced-undeclared"][0]
    assert "MISSING_VAR" in msg.message


def test_duplicate_app_name():
    apps = [
        AppEntry(slug="a", name="同名", dsl_version="0.1.5", dsl={}),
        AppEntry(slug="b", name="同名", dsl_version="0.1.5", dsl={}),
    ]
    findings = check_bundle(Bundle(name="b", apps=apps))
    assert "app-name-duplicate" in _rules(findings)


def test_plugin_unpinned_is_warning():
    bundle = Bundle(name="b", plugins=[PluginDep(plugin_id="langgenius/tavily", version="")])
    findings = check_bundle(bundle)
    assert "plugin-unpinned" in _rules(findings)
    assert [f for f in findings if f.rule == "plugin-unpinned"][0].level == "warning"


def test_secret_unresolved_with_map():
    ph = placeholder_of("sk-real-000000000000000000")
    dsl = {"kind": "app", "app": {"name": "n"}, "version": "0.1.5", "config": {"api_key": ph}}
    bundle = Bundle(name="b", apps=[AppEntry(slug="x", name="n", dsl_version="0.1.5", dsl=dsl)])
    # 空映射 → 报错
    findings = check_bundle(bundle, SecretMap())
    assert "secret-placeholder-unresolved" in _rules(findings)
    # 有映射 → 通过
    smap = SecretMap(entries={ph: "sk-real-000000000000000000"})
    assert check_bundle(bundle, smap) == []


def test_env_secret_unresolved():
    ph = placeholder_of("sk-env-0000000000000000000")
    bundle = Bundle(name="b", env=[EnvVar(name="K", value=ph, secret=True)])
    assert "secret-placeholder-unresolved" in _rules(check_bundle(bundle, SecretMap()))
    assert check_bundle(bundle, SecretMap(entries={ph: "sk-env-0000000000000000000"})) == []


def test_real_site_a_bundle_only_warns(tmp_path):
    """site-a 导出后：插件 tavily 未钉版本 → 只有 warning，没有 error。"""
    bundle, smap = export_bundle(LocalSource(SITE_A), tmp_path / "b")
    findings = check_bundle(load_bundle(tmp_path / "b"), smap)
    assert not [f for f in findings if f.level == "error"]
    assert "plugin-unpinned" in _rules(findings)
