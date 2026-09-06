# 战壕发现与证据观察 — Grok发布包 v1.0.0

可交给Grok执行每日实时X发现任务的完整观察方案。保留“人→一跳→对象”，提供证据、未知项和可证伪检查；不下单，不输出份数、加仓、退出或目标价。

**使用入口：[Grok交接说明](docs/GROK_HANDOFF.md) · [完整任务提示词](dist/GROK_TASK_PROMPT.txt)**

默认调度：每天08:00 Asia/Hong_Kong。实际调度在Grok平台设置，仓库没有创建任何定时任务。实时X能力由用户确认，平台工具、配额、提示词长度和首次运行仍需在Grok中实测。

## 这次修复了什么

- 统一B时间窗口、fo规则、A首次证据与缺失处理，已知否决终止，不重新分类兜底。
- A/B只能输出OBSERVE/UNKNOWN/FAIL；C/D关闭，完整数据也不能输出交易通过。
- 数字绑定资产、来源、观测时点、方法和证据；失败不写0，不从X帖子猜链上字段。
- 正式JSON Schema、离线一致性校验、合成回归与自包含提示词，避免跨文档规则漂移。
- 不把同轮复搜当5分钟复核，不用随后数据满足历史案例，不把采集失败当quiet。

## 文件导航

| 文件 | 用途 |
|---|---|
| [01-PRD](01-PRD-产品方案.md) | 产品边界与观察状态 |
| [02-TECH](02-TECH-实现方案.md) | Grok运行、证据和本地验证 |
| [03-AUDIT](03-AUDIT-审计清单.md) | 修复闭合与验收范围 |
| [04-PROMPT](04-PROMPT-v2.md) | 生成的提示词预览，文件名保留兼容 |
| [规则说明](docs/RULES.md) | 统一规则语义及D未来设计 |
| [policy](config/policy.json)、[seeds](config/seeds.json)、[metrics](config/metrics.json) | 唯一机器配置 |
| [Schema](schemas/report.schema.json) | 完整输出结构 |
| [发布检查单](docs/RELEASE_CHECKLIST.md) | 本地检查与Grok首跑分别验收 |
| [原五卡](fixtures/historical-cards.json) | 有限事实回放，不是认证行情 |
| [变更记录](CHANGELOG.md) | v0.9到1.0.0改动 |
| [v0归档](archive/prompt-v0.md) | 历史原文，不直接当现网快照 |

## 本地复验

Python 3.10+，只用于开发与人工复验；Grok不必安装Python才能运行观察提示词。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/check_release.py
```

配置或模板改动后，先运行 `python scripts/build_release.py`，再复验。只编辑生成的dist或04文件会被一致性检查拒绝。

所有examples均为REPLAY合成数据，不能作为实际市场报告。验证器不会认证外部来源，不是已接入Grok的发布网关；没有外部网关时仍需人工抽查。更改仓库不是启用Grok任务，实际启用请按交接说明完成一次真实首跑。

## 来源与发布边界

基于 [xydkd/trenches-gate-audit](https://github.com/xydkd/trenches-gate-audit/tree/615db59d7aa33ae3d2a2c72a64b413fea8688a0f) 的公开送审稿。保留作者来源和v0历史；未为上游文本另附新许可证。发布时以GitHub commit和dist/manifest.json锁定版本，不以可变main链接代表已测试版本。
