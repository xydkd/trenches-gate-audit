# 实现方案 v1.0.0

## 1. 两个执行边界

Grok平台负责调度、实时X/公开网页工具和观察报告生成；本仓库提供可复制完整prompt。Python工具仅负责构建和离线复验，不是已部署的采集后端，不具备实际下单、调度或来源认证能力。

用户确认Grok能实时检索X。工具名、分页能力、运行时长和输入/输出上限必须运行时探测，不固定假想API。公开量化页面是否可访问独立判断；没有链节点、供应商方法或历史点时输出UNKNOWN。

## 2. 构建链

`config/policy.json + config/seeds.json + config/metrics.json + prompts/grok-observation.template.md` → `scripts/build_release.py` → `dist/GROK_TASK_PROMPT.txt`、`schemas/report.schema.json`、`04-PROMPT-v2.md`、`dist/manifest.json`。

实际任务只需要dist提示词全文；它内嵌全部配置和schema，不使用“详见另一个文档”的隐含依赖。生成内容逐字校验，hash记录确定版本。04文件名沿用原链接，内容版本为1.0.0。

## 3. 采集与时间

固定运行开始时的过去24h窗口；from账号不带对象词，分页或二分时间窗，原帖ID去重。搜索预算40次、一跳8人、对象8行；预算不足标PARTIAL并保留缺口，不扩大关键词范围凑数。账号handle要核实，身份疑似变化记UNKNOWN。

实时X为发现证据。量化证据须验证来源方法、时间、单位、资产和字段支持，普通帖子/截图不能当链上已核数据。数值观测时间与抓取时间分别保存；给旧数据换新的抓取时间不能续期。指标定义/源冲突/过期均不能标VERIFIED。

报告evaluated_at记录完成判定时点。所有引用必须在该时点已知，未来帖子和后来数据不能倒灌回放。permission_age由原官方事件到evaluated_at复算。

## 4. 结构与校验

采用正式Draft2020-12 JSON Schema。顶层run版本/窗口/健康/覆盖、全局evidence、候选objects；每对象含身份引用、来源路径、语法、中文覆盖、分类、metrics、状态/原因/缺失与证伪检查。所有非VERIFIED值为null，未知不是0/false；字段可省略，但必须出现在必要字段missing列表。

验证器检查：schema、LIVE/REPLAY、窗口、未来数据、TTL、来源种类、身份与跨资产引用、分类、状态及原因一致性。A/B完整数据只能OBSERVE。存在明确共同否决先返回，不让后续类型覆盖。完整顺序见 [规则说明](docs/RULES.md) 和 `scripts/validate_report.py`。

验证器不认证链接真实性、不替模型判定语法/独立主体、不核对DNS与重定向后的真实网络、不保证自然语言完全无交易诱导。源内容真实性与运行期请求边界由Grok实际工具和人工抽查承担。JSON一致性也不证明中文正文语义一致；正文仍需人工对照。

## 5. D与其他未实现能力

D运行态关闭。测试包含D数值区间、OR三值逻辑和300–600秒同身份/版本的时间原语，仅验证未来设计边界。没有实现真实延迟采集、持久化快照、崩溃恢复或最终D门。不得将单原语测试结果描述为复核系统通过验收。

## 6. 本地命令

按 [Grok交接说明](docs/GROK_HANDOFF.md) 安装dev依赖后：

```bash
.venv/bin/python scripts/build_release.py
.venv/bin/python scripts/check_release.py
.venv/bin/python scripts/validate_report.py examples/replay-missing.json --runtime REPLAY
```

开发配置改变后必须重建；不能单改dist。输出校验失败就修正有证据的字段或降级，不能删校验条件。平台不接受完整prompt时不能静默截断，先调整发布包再重测。

## 7. 发布与回滚

用户已授权修复和发布仓库；不再沿用旧稿“不得修订”的冻结状态。本次仓库操作不创建Grok任务。操作者先读出实际目标任务、备份配置，完成真实首跑，再启用；记录固定commit与prompt hash。回滚使用实际导出的旧文本，v0归档只证明历史送审内容。
