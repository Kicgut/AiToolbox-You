# CC Switch 原生会话用量导入与聚合调研

> 状态：调研结论
> 更新时间：2026-08-02-10-18-54
> 创建时间：2026-08-02-10-18-54
> 适用范围：CC Switch 当前官方源码中 Codex、Claude Code 原生会话用量的只读导入、跨来源去重、日聚合、保留策略及其对 Workbench 统计复用边界的判断
> 不包含：读取本机 CC Switch 数据库记录、会话正文、账号、令牌、凭据或余额；CC Switch / Workbench 产品代码改动；将 CC Switch 私有 SQLite 当作已发布 API 的实现方案

## 1. 调研口径与结论摘要

本记录仅审阅 [CC Switch 官方仓库](https://github.com/farion1231/cc-switch) `main` 分支在 `8383076791f2c0d34f3a249f43f95e8a3906c0a7`（2026-08-02）时的源码；下列“精确”“缓存”“成本”均是 **CC Switch 对其已覆盖记录的口径**，不是厂商账单、订阅额度或余额。

| 问题 | 已验证结论 |
| --- | --- |
| Codex / Claude 如何补录 Token | CC Switch 分别扫描其原生 JSONL，增量解析后写入同一张 `proxy_request_logs` 明细表；不是通过读取 Workbench，也不是把会话正文复制到统计表。 |
| 未运行时能否补记 | 不能实时截获未经过其代理的请求；但下次 CC Switch 启动后，支持的原生日志仍在且格式可解析时，可由 importer 事后补录 Token。 |
| `session_log` 与 `codex_session` | 前者是 Claude Code 原生日志导入来源；后者是 Codex 原生日志导入来源。二者都不是代理实时记录，实时代理记录的默认来源是 `proxy`。 |
| 为什么可显示 Claude 缓存命中 | Claude importer 直接读取原始 `message.usage.cache_read_input_tokens` 与 `cache_creation_input_tokens`；它**不会**仅从 input/output 推算缓存命中。若某一条原生日志没有这两个字段，则此导入路径不能凭空补出缓存数据。 |
| 能否做 Workbench 唯一统计来源 | 不宜。它可以是显式启用的、只读的“CC Switch 已观测聚合”候选来源；但采集覆盖、内部 schema、去重、价格与 30 天明细保留均由 CC Switch 版本决定，Workbench 不能以此取代自己的轻量索引、分组、任务和运行审计。 |

## 2. 数据模型与两个 data source 的写入语义

官方 schema 将实时代理与原生会话导入共置于 `proxy_request_logs`：主键是 `request_id`，并保存输入、输出、缓存读/写、成本、延迟、状态、`session_id`、时间和 `data_source`。超过保留期的明细会转入 `usage_daily_rollups`；`session_log_sync` 则只保存每个源文件的增量同步水位（路径、mtime、行偏移、上次同步时间）。见 [schema：明细表](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/database/schema.rs#L194-L232)、[日聚合和同步水位](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/database/schema.rs#L272-L309)。

| `data_source` | 写入方与条件 | `provider_id` / `provider_type` | `session_id` 的含义 |
| --- | --- | --- | --- |
| `proxy`（默认） | `UsageLogger::log_request` 在请求已经过 CC Switch 本地代理后落库；其 INSERT 未覆盖 `data_source`，因此使用 schema 默认值。相同 request ID 的同语义代理记录不重复写；已存在的 `session_log` 可被代理明细替换。见 [代理写入与冲突策略](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/proxy/usage/logger.rs#L101-L222)。 | 真实代理提供方 / 请求提供方类型 | 由代理请求携带；语义取决于代理客户端，不能等同于原生会话文件 ID。 |
| `session_log` | Claude Code importer 扫到一个有任一计费 Token 的 `assistant.message.usage` 后写入。见 [解析与导入门槛](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage.rs#L300-L425)、[INSERT 常量](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage.rs#L549-L587)。 | `_session` / `session_log` | 该物理 JSONL 中首次发现的 `sessionId`。它是 Claude 提供的会话标识；表中没有单独的父会话列。 |
| `codex_session` | Codex importer 对每个非零 `token_count` 增量写入一行。见 [写入调用](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L1175-L1210)、[INSERT 常量](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L1213-L1331)。 | `_codex_session` / `codex_session` | 写入的是该 rollout 文件的 `root_thread_id`；`request_id` 还加入每个非零 token 事件序号。因此一个 Codex 原生会话会生成多条“每个 Token 增量事件”的明细，并非一会话一行。 |

### 2.1 Codex 父/子代理不能被误读为表的父子会话图

Codex importer 从文件名取得 `root_thread_id`，又校验 `session_meta` 的 ID；写入时把该 `root_thread_id` 传为 `session_id`。父引用 `forked_from_id` 或 `source.subagent.thread_spawn.parent_thread_id` 仅用于识别 fork 后在子 rollout 中重放的父事件，并跳过相同前缀，避免重复计数；它没有作为独立 `parent_session_id` 写入统计表。见 [父引用解析](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L400-L416)、[会话元数据与 token 事件解析](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L696-L870)、[父 replay 前缀排除](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L1102-L1188)。

因此，`proxy_request_logs.session_id` 不能作为 Workbench 的会话族谱、Handoff 关系或“原生主会话”权威依据。它是统计归属/筛选线索，且不同 `data_source` 的构成方式不同。

## 3. 原生日志如何提取 Token

### 3.1 Claude Code：按 assistant 消息取四种计费字段

CC Switch 扫描 `~/.claude/projects/` 下的主会话 JSONL、`subagents/*.jsonl`，以及 Workflow 的更深一层子代理 JSONL。后两类也进入统计，故“Claude 会话统计”可能包含子代理消耗，而不等于仅用户在主线程看见的消息。见 [扫描范围](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage.rs#L181-L230)。

对每一条 `type == "assistant"` 的 JSONL 行，importer 从 `message.usage` 读取：

| CC Switch 字段 | 原生日志字段 | 说明 |
| --- | --- | --- |
| `input_tokens` | `input_tokens` | 原始输入 Token。 |
| `output_tokens` | `output_tokens` | 原始输出 Token。 |
| `cache_read_tokens` | `cache_read_input_tokens` | 缓存命中/读取 Token。 |
| `cache_creation_tokens` | `cache_creation_input_tokens` | 缓存创建/写入 Token。 |

字段读取和默认值为 0 的逻辑见 [Claude 解析器](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage.rs#L300-L380)。同一 `message.id` 在单个扫描文件中会优先选择有 `stop_reason` 的版本，否则选择 `output_tokens` 较大的版本；随后只要四个计费字段任一非零就导入。源码注释明确说明：Workflow / 子代理可能只留下开始快照但已有 input/cache 计费，不能用“最终输出是否完整”过滤。见 [消息内去重和计费门槛](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage.rs#L361-L425)。

**回答“原始 JSONL 看起来只有 input/output，CC Switch 为什么还有缓存命中”：** 当前 importer 并没有反推算法。只有当原始 `message.usage` 实际携带 `cache_read_input_tokens` 或 `cache_creation_input_tokens` 时，CC Switch 才会把它们分别展示；若用户观察的那条原始记录确实没有这两个字段，则对应的 `session_log` 导入值是 0。界面上另一条带缓存值的记录还可能来自已走代理的 `proxy` 来源，必须以 `data_source` 区分，不能把两类明细混为同一原生行。

### 3.2 Codex：累计计数转为每事件 delta

CC Switch 扫描 `~/.codex/sessions/YYYY/MM/DD/*.jsonl` 及 `archived_sessions/*.jsonl`。见 [文件发现](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L640-L694)。

它读取 `event_msg` 中 `payload.type == "token_count"` 的 `info.total_token_usage`；该值为累计计数，故以相邻累计值相减得到一条增量。若只有 `last_token_usage`，则直接使用该次值。可读字段为 `input_tokens`、`cached_input_tokens`（也兼容 `cache_read_input_tokens`）和 `output_tokens`；`reasoning_output_tokens` 仅纳入签名，不单独写入本表。代码还将 `cached_input` 限制为不大于 `input`，并且 Codex 导入的 `cache_creation_tokens` 固定为 0，因为该日志源不提供该字段。见 [Token 字段/增量规则](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L425-L450)、[累计值解析](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L543-L579)、[事件 delta 处理](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L790-L856)、[Codex 写入字段](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L1293-L1327)。

## 4. 增量同步、去重与汇总

### 4.1 同步覆盖和增量水位

每个 importer 以 `session_log_sync` 的 `last_modified` 和 `last_line_offset` 跳过未改动文件/已处理行；写入后更新水位。Claude 的共享实现见 [读取水位](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage.rs#L430-L454) 和 [写入水位](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage.rs#L456-L478)；Codex 在文件 mtime 未变化时直接跳过，且逐行偏移跳过已处理 token 事件，见 [Codex 增量控制](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L1031-L1051) 和 [行偏移过滤](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage_codex.rs#L1175-L1209)。

应用启动时先触发一次会话同步，随后以 60 秒间隔同步；同步入口聚合 Claude、Codex、Gemini、OpenCode 与 Grok Build importer。见 [启动与周期同步](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/lib.rs#L1225-L1266) 和 [统一 importer 调度](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/session_usage.rs#L69-L95)。这能补录“CC Switch 未运行期间、但后来仍保留在受支持原生目录中的日志”，不能证明其覆盖所有工具、目录、版本或已删除日志。

### 4.2 三层去重：写入前、代理碰撞、读侧有效口径

| 层级 | 规则 | 影响 |
| --- | --- | --- |
| 原生日志内部 | Claude 按 `message.id` 选代表行；Codex 对累计 `total_token_usage` 算 delta，并在子 rollout 中排除父 replay 前缀。 | 避免同一 JSONL 的流式/重放记录直接重复。 |
| 导入写入前 | 导入行若 `request_id` 已存在，或在 ±10 分钟内发现同 app、成功代理记录的 model + input/output/cache 指纹相同，则跳过。Codex/Gemini/OpenCode 缺失 cache creation 时视该维度为未知。 | 代理与会话扫描同时存在时优先少写一份会话行。 |
| 汇总/展示读侧 | `effective_usage_log_filter` 会排除在 ±10 分钟内找到同指纹成功代理记录的 `session_log`、`codex_session`、`gemini_session`、`opencode_session` 行；统计测试明确采用“代理优先”。 | 即使历史或并发导致两行都存在，统计和请求列表按有效口径避免相加。 |

写入前的常量、指纹字段和 SQL 见 [去重窗口/入口](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/usage_stats.rs#L222-L230)、[写入前判断](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/usage_stats.rs#L342-L420)；读侧过滤见 [有效统计过滤器](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/usage_stats.rs#L304-L340)，代理优先的回归测试见 [测试用例](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/usage_stats.rs#L3411-L3605)。

这个策略是 CC Switch 对“字段相同且时间接近”的启发式消重，不是可用于 Workbench 会话身份合并的强等价证明。尤其不应据此把不同原生会话自动合并。

### 4.3 日聚合与 30 天明细保留

CC Switch 启动时调用 `rollup_and_prune(30)`。见 [启动处调用](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/database/mod.rs#L151-L163)。该 DAO 先按本地日的完整边界计算 cutoff，再把早于 cutoff 的**有效**明细按 date、app、provider、model、request model、pricing model 聚入 `usage_daily_rollups`，最后删除所有早于 cutoff 的明细行。见 [保留边界和事务](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/database/dao/usage_rollup.rs#L11-L114) 与 [聚合/删除 SQL](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/database/dao/usage_rollup.rs#L116-L182)。

所以约 30 天后仍可得到日级总数、成功数、四类 Token、成本和平均延迟，却不能恢复逐请求延迟、精确 session ID、data source 或原生日志对应关系。UI 的“真实消耗 Token”和缓存命中率也只是将后端已 cache-normalized 的四类计数重新汇总；它不是另一份独立采集数据。见 [后端统计定义](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src-tauri/src/services/usage_stats.rs#L17-L60) 与 [前端汇总/展示](https://github.com/farion1231/cc-switch/blob/8383076791f2c0d34f3a249f43f95e8a3906c0a7/src/components/usage/UsageHero.tsx#L75-L115)。

## 5. 对 Workbench 的可复用边界

1. **可复用的是汇总结果，不是私有“会话事实”。** 若未来用户显式允许，Workbench 可把 CC Switch 作为可选的、只读的“已观测 Token / 估算成本”卡片来源，显示来源、版本/兼容状态、最近同步时间、覆盖边界和 `estimated` 数据质量。
2. **不得复制或依赖明细库。** 不应导入 `proxy_request_logs` 全表、也不应把其 `session_id` 当 Workbench 的会话 ID/父子关系；30 天 prune、内部 schema 迁移和启发式去重都会使这种依赖脆弱且重复数据量大。
3. **总览总数必须二选一。** 对同一统计范围，CC Switch 聚合与 Workbench 自行从原生 JSONL 的统计不能相加；前者覆盖代理和 importer 已观察到的范围，后者覆盖 Workbench 已注册源目录，二者交集很大但不保证完全相同。
4. **CC Switch 不可用时必须完整降级。** 轻量会话索引、原文读取、分组、自动任务、受控运行审计和官方额度/余额连接器均不依赖 CC Switch；其安装、数据库锁定、schema 变化或停止运行只能使该可选卡片变为 `unavailable`，不能阻塞 Workbench。

以上是外部软件的可变调研事实，不构成对 Workbench 架构的变更授权。若要采用只读聚合适配器，应先单独确认数据源选择、版本 allowlist、最小字段、双计数策略、缓存/刷新频率和降级 UI，再更新架构与对应 Phase 计划。
