# dify-bundle

把 Dify 应用打成**可版本化的交付包**：导出 / 校验 / 差异对比 / 一键重建 / 行业模板。

## 解决什么问题

FDE 现场交付时要带走的是「**应用 DSL + 环境变量 + 插件依赖 + 密钥**」，
但 Dify 只能导出应用 DSL，其余全靠手工重建。客户环境一多就崩：

- 上周给客户 A 装的那版，和仓库里这版，**差在哪**？——没有 diff 工具，答不上来
- DSL 里明文写着客户的 API Key，**导出即泄密**
- 交付十家制造业客户，每家都从零配一遍——**没有「行业模板」这一层**

dify-bundle 补的就是这三块。

## bundle 是什么

一个纯 YAML 目录，可以直接进 git：

```
site-a交付包/
├── bundle.yaml          # 清单：格式版本、来源、创建时间、应用列表
├── apps/<slug>.yaml     # 每个应用的 DSL（已脱敏，键序固定）
├── env.yaml             # 环境变量声明（敏感值是占位符）
├── plugins.yaml         # 插件依赖（id + version）
├── secrets.local.yaml   # 占位符→真实值（自动 gitignore，绝不进 git）
└── .gitignore
```

## 命令

```bash
pip install -e .

# 导出：从 DSL 目录（或 Dify 实例）打成 bundle，敏感值自动脱敏
dify-bundle export --source ./dsl-exports --out ./site-a交付包

# 校验：导入前在本地先翻车——DSL 版本、env 引用、密钥缺口、插件未钉版本
dify-bundle check ./site-a交付包 --html check.html

# 差异：客户现场跑的 vs 仓库里的，字段级对比；有差异退出码 1，可挂 CI
dify-bundle diff ./site-a交付包 ./site-b交付包 --html diff.html

# 重建：先校验、再还原密钥、最后写目标；--dry-run 只看计划
dify-bundle import ./site-a交付包 --target ./rebuilt

# 模板：把一次交付沉淀成行业资产——客户特定值抽成变量
dify-bundle template ./site-a交付包 --out ./制造业客服模板

# 实例化：新客户只填变量，十秒出一份新交付包
dify-bundle instantiate ./制造业客服模板 --out ./和顺塑业交付包 \
  --set customer-service.app_name=和顺塑业客服
```

退出码契约（与 [dify-eval](https://github.com/ulinchoo-dotcom/dify-eval) 一致）：
`0` 正常 · `1` 校验不过 / 有差异 / 导入被拦 · `2` 用法或文件错误。

## 设计决策（为什么这么做）

**1. 真实密钥永远不进 bundle。**
导出时按「键名 + 值形态」双规则识别敏感值（`api_key`/`token`/`password` 命名，
`sk-`/JWT/AWS AKIA/长 hex/`ghp_` 值），替换成占位符 `${SECRET_<sha1前8位>}`。
同一个值永远得到同一个占位符——所以 **diff 能看见「密钥换了」，但永远看不见密钥本身**。
映射表写进 `secrets.local.yaml`，自动 gitignore。

**2. 先拦后建。**
`import` 的流程是硬编码的：check → 还原密钥 → 写目标。
check 有 error 且没 `--force`，一个文件都不会写。
密钥还原优先级：`--secrets` 映射文件 > 环境变量 `SECRET_<8hex>`（CI 场景）> 报错。

**3. 模板是产品资产，不是技术副产物。**
`template` 把客户特定值（应用名、简介、外部 URL、非敏感环境变量）抽成带默认值的变量，
secret 占位符原样保留——模板可以安全地公开分享，像 Helm Chart 一样被实例化。

**4. diff 免疫字段顺序。**
DSL 落盘前键序固定，对比时扁平化成点分路径逐字段比——
不会因为 YAML 里字段换了个位置就报假差异。

## 诚实声明

- `export --source https://...`（直连 Dify Console API）按社区通行的端点实现，
  **未对真实实例验证过**；经过完整测试的是 DSL 文件目录这条通路——
  这也是现场最常见的起点（客户给你一个 U 盘 / 一个压缩包）。
- 知识库的实体内容（文档、分段）不在 bundle 范围内——那是数据迁移，不是配置交付。
  bundle 只管「配置能不能一键重建」。

## 测试

```bash
pip install -e ".[dev]"
pytest -q    # 55 个测试：脱敏规则 / round-trip / 校验规则 / diff / 模板 / CLI 契约
```

`examples/` 下有两个示例站点：site-b 相对 site-a 换模型、删应用、加应用、改环境变量，
`dify-bundle diff` 一遍就能看到全部四类差异。

## 路线图

- [ ] DifyApiSource / DifyApiTarget 对真实实例联调
- [ ] `check --baseline`：把上次的校验结果存成基线，新增 error 才拦
- [ ] 模板变量支持类型与正则约束（如 `env.KB_ENDPOINT` 必须是 https URL）

## License

MIT
