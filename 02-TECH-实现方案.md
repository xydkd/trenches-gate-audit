# 战壕发现与交易门系统 — 实现方案（送审稿）

- 版本：v0.9（审计前冻结）
- 配套：[01-PRD-产品方案.md](./01-PRD-产品方案.md)
- 状态：文档草稿。审计通过前 **不得** `automation_update` 现网任务。

---

## 1. 现网与目标态

| 项 | 现网 v0 | 目标 v1（本方案） |
|---|---|---|
| 任务 ID | `a58ed308-06f3-4c7d-9f9d-0975c707ac72` | 同一 ID，只改 prompt |
| 名称 | `trenches-discovery-am` | 可改为 `trenches-gate-am`（可选） |
| 调度 | 每日 08:00 `Asia/Hong_Kong` | 不变 |
| 通知 | DEFAULT（App + 邮件） | 不变 |
| 能力 | 发现层 + FOMO 灯 + 滞后 | + 交易门记分卡；C 默认关 |
| 执行 | Grok Automations 跑 prompt，模型自己调 X/网页工具 | 同左，prompt 增补采集顺序与输出 schema |

**不新建任务、不接 Debot、不写跟单 bot。** v2（二次监控最多 3 条 D 候选）不在本次改 prompt 的必做范围，见 §9。

另有无关任务 `每日新闻`（`79328f0e-…`）：不要合并、不要改。

---

## 2. 运行时约束（实现必须接受）

Grok Automations 单次运行的能力边界：

- 可用：X 关键词/语义/用户搜索、帖线程、网页抓取、联网搜索
- 不可用（除非用户另接）：fomoapi 密钥、GMGN 私有 API、登录态 985monitor、链上节点、自动下单
- X 单次搜索约 **10 条**。必须按 `from:账号` + 时间窗切片，禁止一张大网捞 ticker
- 网页工具对 X.com 常不可用，查帖必须走 X 工具
- 第三方看板（windvane / GMGN / Stalkchain）可能 JS 渲染不全 → **读不到就写 `未填`，未填在门槛里 = 否**，禁止估算编造
- 单次输出要短。对象表最多 8 行；交易门只打入表对象

这些约束意味着 v1 是「模型按 runbook 采集并填表」，不是独立微服务。审计若要求 SLA/重试队列，标为 v3。

---

## 3. 逻辑架构

```
                    ├─ 种子 from:（无关键词）
定时 08:00 ──► 发现循环 ─ 一跳（引用/转/回的作者）
                    └─ 仅当点名新对象后，才搜该对象
                              │
                              ▼
                    语法匹配 → 无则丢
                              │
                              ▼
                    FOMO 族群检测 → ≥2 族则 P2
                              │
                              ▼
                    中文温度计（滞后）
                              │
                              ▼
                    交易门采集（公开页）
                    市值 / fo% / 持仓 / 捆绑 / dev
                    具名同向 / 鲸鱼 / 换手
                              │
                              ▼
                    硬否 → 类型 A/B/D（C 关）→ 份数 + 证伪句
                              │
                              ▼
                    中文早报（固定 7 节）+ 免责
```

发现循环与现网 prompt 一致，禁止颠倒。交易门 **不得** 把 GMGN 热搜灌进对象表。

---

## 4. 采集 runbook（模型每次必须按此顺序）

### 4.1 发现（与 v0 相同，禁止减步骤）

对每个 w3 账号：

```
x_keyword_search  query="from:HANDLE"  mode=Latest  limit=10
时间：since:当天-1（UTC 换算到过去 24h）
```

w2 仅当 w3 安静或已出现新语法时加读。  
一跳：从上述帖的 quoted/replied/RT 作者列表去重，最多再拉 8 个 `from:`。  
官号（vladtenev / RobinhoodApp / ponsdotfamily / circle）只查 PERMISSION，不当发现源。

中文温度计：`from:jiamigou` `from:tmel0211` 及吴说/PANews 是否出现**信念长文**（教程/快讯不算信念）。

### 4.2 对象核验

对象进入表之后才允许：

```
x_keyword_search 该对象 过去 24h Latest + Top
x_thread_fetch 关键帖
web_search / browse 产品页或浏览器标签（机制核验）
```

撞名规则：`$ARC` 必须消歧义（Circle 公链 / Arcus / Arc Liquidity / TryArcFinance / 其它）。无法消歧义则丢。

### 4.3 交易门采集（v1 新增，只对入表对象）

按能读到的公开页填，失败标 `未填`：

| 字段 | 首选源 | 失败 |
|---|---|---|
| 市值、换手、能否卖 | DexScreener / GMGN token 页 / Defined | 未填 |
| 内外盘、捆绑%、内部%、dev 卖 | GMGN token 页 | 未填 |
| fo% | https://wind.jokkimon.club/windvane 贴 CA | 未填 |
| 持仓人数及方向 | GMGN / FOMO token | 未填 |
| 具名同向 | https://stalkchain.com/robinhood/kols 是否 ≥2 具名 24h 买同一 CA | 0 |
| 鲸鱼 24h | Hoodwatch 若打得开；否则未填 | 未填 |
| 机器人 | X 搜该 CA + `pons-voting` / 相同句式 | 有/无 |

v1 **不做**「先扫 windvane 再找币」。方向永远是对象 → 填表。

5 分钟复核：Automations 单次运行做不到真等 5 分钟。v1 用替代：**同一对象用 Latest 再搜一次，看 10 分钟量/价是否单边爆炸或机器人已喷**。文档里称为 `复核≈同轮复搜`，不要假装有 cron。

### 4.4 禁止的采集

- 用热搜榜冷启动对象表  
- 为填满 8 行去搜随机 meme 词  
- 登录墙后的内容  
- 把返佣链接当数据 API  

---

## 5. 判定实现（必须可复述，禁止模型自由发挥）

### 5.1 发现 P 级

```
if 无六句之一: DROP
if FOMO族>=2 同对象 24h: P2
elif grammar in {PERMISSION, VACUUM, TANDEM} and CN信念文==0: P0
elif grammar in {MECHANISM, LOTTERY} and CN只有快讯: P1
elif 英文已神话/Kaleo级: P2
else: 入表但标确认层，不升 P0
MECHANISM 必须产品核验通过，否则当口号 → DROP 或 LOTTERY
```

### 5.2 交易门

```
C_ENABLED = false   # 产品原则 7，改 true 需书面

hard_no = 内盘(对D) or 不能卖 or 捆绑>20 or 内部>20
        or (dev卖>0 and 类型in{C,D})
        or 投票机器人 or fo_24h_delta>10pt or fo>40
        or 关键字段未填

if hard_no: 门=否

# 分类：只选一类，按优先级
if VACUUM or TANDEM or 核过MECHANISM: 类型=A
elif PERMISSION and 盖章后<72h and MC<50e6: 类型=B
elif C_ENABLED and LOTTERY and 新闻可核 and 盖章<12h: 类型=C
elif 外盘 and 30e4<=MC<=3e6 and 15<=fo<=25 and 人数不掉
     and 换手 in [0.3,2] and (具名>=2 or 鲸鱼净流入>0): 类型=D
else: 门=否

份数:
  A: 2（第三方费率已证可写「可加至 3-4，需人确认」）
  B: 1-2
  C: 0.5-1 且不加
  D: 1（fo 20-25 且斜率平: 1.5）
A/B 若 fo>25 且斜率向上: 禁止加仓（首仓仍可按上表，须在输出写明）
```

证伪句模板（必须填一句）：

- A：`份额掉回或板上第二真盘出现前真空被填上且灯亮`  
- B：`官方删推/证伪或市值>$50M且灯亮`  
- D：`fo 破 15% 或 dev 卖或人数掉头或市值穿 $3M`  

---

## 6. 输出 schema（早报必须能对上）

机器可读块（放在早报末尾，便于以后存档）：

```json
{
  "run_at": "ISO-8601+08:00",
  "weather": "discovery|confirmation|extreme-FOMO|quiet",
  "objects": [
    {
      "name": "string",
      "ca": "0x… or null",
      "chain": "robinhood|arc|other",
      "first_seen_by": {"handle": "", "weight": 3, "conflict": ""},
      "grammar": "PERMISSION|VACUUM|TANDEM|MECHANISM|LOTTERY|LAG",
      "p_level": "P0|P1|P2|drop",
      "cn_register": "none|flash|conviction",
      "fomo_families": [],
      "gate": {
        "type": "A|B|C|D|none",
        "pass": false,
        "size_units": 0,
        "mc_usd": null,
        "fo_pct": null,
        "fo_delta_24h_pt": null,
        "holders_delta": "up|flat|down|unknown",
        "bundle_pct": null,
        "dev_sold": null,
        "named_wallets": 0,
        "turnover": null,
        "missing_fields": [],
        "fail_reason": "",
        "falsify": ""
      },
      "links": []
    }
  ],
  "stance_shifts": [],
  "lag": "",
  "checks_24h": [],
  "disclaimer": "观察扫描，不构成投资建议。交易门是规则打分，不是下单指令。"
}
```

中文七节标题固定，便于审计对照。空表时 `objects=[]`，天气 `quiet`，交易门整表省略并写「无对象，不开门」。

---

## 7. 提示词管理

- 完整 prompt 见 [04-PROMPT-v2.md](./04-PROMPT-v2.md)
- 现网 v0 prompt 以 Automations 内文本为准；改 v1 只用 `automation_update` 替换 `prompt`，不改 schedule
- 版本记在 prompt 首行：`PROMPT_VERSION=v1.0`
- 回滚：把 prompt 设回 v0 文本（实现须在发布前把 v0 全文另存 `docs/archive/prompt-v0.md`）

---

## 8. 种子与配置的存放

v1 配置全部写在 prompt 里（Automations 无独立配置文件）。审计后若要改种子：

1. 在 PRD §6.1 提 PR 式说明（哪次复盘、哪条帖、权重）
2. 改 prompt 对应段落
3. 不在运行时「觉得谁准就升档」

Circle Arc 的 SkyAAmen：prompt 里写死「仅当种子点名 Arc（Circle）战壕时作为一跳，RH 对象不加」。

---

## 9. 分期实现

| 步 | 做什么 | 不做 |
|---|---|---|
| **v1（本次）** | 改 prompt：交易门 + C 关 + 未填=否 + JSON 块 | 不改调度、不加 D 冷启动、不接 API key |
| v1 验证 | 审计通过后 `run_now` 一次，人工对照 §回归 | 不连续 run_now 刷 |
| v2 | 允许最多 3 条 `来源:二次监控` 的 D 候选 | 仍不下单 |
| v3 | 自建采集（fomoapi key、风控库、回测） | 新项目 |

---

## 10. 测试计划（实现自测，审计可抽）

1. **回归五票**（PRD §8）：用冻结日期重跑叙述，输出必须匹配期望门。允许模型在 `run_now` 时因搜索窗口变成「今日」，故回归以「给定事实卡」为准——见 AUDIT 附件用例，prompt 规定「若用户在对话里贴回归卡，只根据卡打分不另搜」。  
2. **空窗**：种子无新语法 → 空表，不搜 meme。  
3. **撞名**：同时出现 Circle Arc 与 TryArcFinance → 两行或丢后者，不得合并。  
4. **未填**：windvane 打不开 → fo=未填 → D 否，不得写「估计 20%」。  
5. **C 关**：ZZZ 类即使论文完整，门=否，类型不得写成 A。  

---

## 11. 运维

- 失败：Automations 跑挂 → 用户侧无早报。v1 不建心跳。连续 2 天无输出则人工看任务是否暂停。  
- 改种子/改门槛：改 prompt + 文档版本号同步。  
- 日志：以每日早报全文为唯一日志。JSON 块便于以后粘贴存档。  
- 密钥：v1 无。

---

## 12. 安全与合规（实现检查单）

- [ ] prompt 含「不下单、不跟单、不给目标价」  
- [ ] prompt 含免责声明且要求每份输出复述  
- [ ] 不把用户资金、钱包私钥写入任何字段  
- [ ] 不指示绕过站点登录、不爬需登录的微信/TG 全文  
- [ ] 第三方站点只 GET 公开页  
- [ ] 不输出「建议立即买入 XXX」句式（用「门=否/可 + 份」）  

---

## 13. 工作量估计

- 改 prompt 并冻结 v0 备份：1 小时  
- 审计通过后 `update` + 一次 `run_now` + 人工对照：0.5 小时  
- 不写代码、不起服务、不改仓库应用
