# Phase 2：统计中心与 CC Switch 可选增强

> 状态：已批准
> 依赖：Phase 1 已完成
> 允许真实模型请求：否
> 允许修改第三方数据：否；本项目不升级 CC Switch，连接器始终只读
> 验证映射：`docs/verification-and-boundaries.md` §3.3（CC Switch 只读连接器/回退/去重/pricing source，含 CC-01–05 当前空白清单）、§3.4 EVT-04（数据质量传播）

## 目标

在所有部署环境中用原生会话日志提供一致的基础统计，并在 CC Switch 存在时用只读代理观测补充 provider、HTTP 状态、TTFT、延迟和已记录成本。所有指标展示来源和数据质量，且不重复计数。

## 非目标

- 不让 CC Switch 成为依赖。
- 不从本项目写入或迁移 CC Switch 数据库。
- 不升级、降级、重装、修复或调用 CC Switch updater。
- 不把订阅 token 估算称为实际账单。
- 不用“退出码 0”或 AI 自述定义任务成功。
- 不在本 Phase 发送真实模型 prompt。

## 交付物

- `observations`、`usage_records`、`daily_rollups`、`pricing_snapshots`、`rollup_invalidations`、`observation_links`、`rebuild_jobs` 数据模型。
- Codex/Claude 原生日志 usage 解析。
- CC Switch 只读 connector 与 pricing adapter。
- 观测去重与来源合并。
- 统计 API 和统计页面。
- CC Switch 未安装、v10、v16 和未知未来版本的只读兼容报告。

## 任务实施顺序（2026-07-24 设计细化，经 Codex 评审）

任务编号沿用主题编号，不代表实施顺序——与 Phase 1 P1-12→P1-14→P1-13 的先例一致。实际实施顺序：

1. **P2-01**（统计数据模型）——冻结 `observations`/`usage_records`/`daily_rollups`/`pricing_snapshots`/`rollup_invalidations` 合同，后续任务都依赖这一步的字段定义。
2. **P2-02** 与 **P2-03**（Codex/Claude usage 解析，可并行）——必须共享 P2-01 的 normalized event 和 dedup 合同，但两者的事件 identity、累计计数和 cache 交叉校验规则不同，不合并为一个实现任务。
3. **P2-00 前置门禁**（CC Switch 只读能力/字段白名单/cursor/缓存失效合同）——在读取任何 CC Switch 统计数据前必须先冻结。
4. **P2-04**（CC Switch 只读连接器与 pricing adapter）——依赖 P2-00 门禁和 P2-01 的 observation/pricing schema。
5. **P2-05**（去重和观测合并）——必须在 Codex/Claude/proxy 三类 normalized observation 都有稳定字段后实施。
6. **P2-06**（成本语义）——依赖 P2-01 的 pricing snapshot、P2-04 的 pricing adapter、P2-05 的 merge status。
7. **P2-07**（统计 API）——依赖所有后端 metric shape、availability 和 rollup 状态冻结。
8. **P2-08**（统计 UI）——依赖 P2-07 的 API DTO 与 CSV 列定义。
9. **P2-09**（维护与重建）——放在最后，因为它需要重算全部 parser、dedup、merge、pricing 和 rollup 结果。

若确有理由必须调整顺序，调整前必须重新核对被跳过任务的字段依赖是否已冻结，不能假定后续任务可以在依赖字段还未定稿时开工。

## 任务

### P2-01：统计数据模型

- [x] 创建 `observations`、`usage_records`、`daily_rollups`、`pricing_snapshots`、`rollup_invalidations` 五张表，并补充 links/jobs/audit 表。
- [x] 区分 session observation、supervised run observation、proxy observation。
- [x] 每个 token/cost 事实可追溯到 `observation_id`、`source`、`quality`、`observed_at`、`parser_version`。
- [x] 设计可重建 rollup 和时区边界（含 DST 规则）。

#### P2-01 数据模型契约（2026-07-24 设计细化，经 Codex 评审）

原则：把“原始观测”和“可计量 usage record”分离——`observations` 保存来源事实，`usage_records` 保存归一化后的 token/cost 事实。一个 observation 可以产生零个、一个或多个 usage record；rollup 只聚合有效 usage record。未知 token 字段一律用 `NULL`，不用 `0` 代替未知。

**`observations`**

| 字段 | 类型 | 约束/示例 | 语义 |
|---|---|---|---|
| `id` | TEXT | PK，UUID/ULID | Workbench 观测 ID |
| `observation_kind` | TEXT | `session` / `supervised_run` / `proxy` | 观测类型 |
| `source` | TEXT | `codex_jsonl`, `claude_jsonl`, `proxy_log`, `cc_switch` | 原始来源 |
| `source_locator` | TEXT | 脱敏路径或逻辑标识 | 不保存 credential；路径需脱敏 |
| `native_session_id` | TEXT NULL | 原生 session ID | 可为空 |
| `native_event_id` | TEXT NULL | 原生 message/event/request ID | 可为空 |
| `request_id` | TEXT NULL | provider/request ID | 可为空 |
| `conversation_family_id` | TEXT NULL | Workbench family ID | 不把 fork 自动合并为同一请求 |
| `tool` | TEXT | `codex` / `claude` / `proxy` | 归一化工具 |
| `profile_ref` | TEXT NULL | Workbench profile 引用 | 不等同于 Codex `--profile` |
| `project_ref` | TEXT NULL | 项目归一化引用 | 可为空 |
| `model` | TEXT NULL | 例如 `claude-sonnet-4-...` | 原始或归一化模型名 |
| `provider` | TEXT NULL | provider 名称 | 来源可推断时仍需标记置信度 |
| `started_at` | TEXT NULL | ISO-8601 UTC | 观测开始时间 |
| `observed_at` | TEXT | ISO-8601 UTC | 读取/解析到该事实的时间 |
| `payload_hash` | TEXT | SHA-256 | 原始规范化 payload 指纹 |
| `quality` | TEXT | `exact` / `estimated` / `unavailable` | 该事实的数据质量 |
| `parser_version` | TEXT | 例如 `codex-jsonl-v2` | 解析器版本 |
| `parse_status` | TEXT | `parsed` / `partial` / `unknown` / `rejected` | 解析状态 |
| `raw_ref` | TEXT NULL | 原始文件+offset 摘要 | 不强制保存完整敏感 raw payload |
| `created_at` | TEXT | UTC | Workbench 入库时间 |

**`usage_records`**

| 字段 | 类型 | 约束/示例 | 语义 |
|---|---|---|---|
| `id` | TEXT | PK | usage record ID |
| `observation_id` | TEXT | FK | 产生该 record 的观测 |
| `dedup_key` | TEXT | UNIQUE | 稳定去重键 |
| `event_kind` | TEXT | `request_delta`, `request_total`, `session_total` | token 事实类型 |
| `input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_creation_tokens` / `reasoning_tokens` / `total_tokens` | INTEGER NULL | 非负 | 缺失字段一律 NULL；`total_tokens` 只在原始给出或可靠可加时填写 |
| `counter_scope` | TEXT | `request`, `turn`, `session`, `unknown` | 累计值的作用域 |
| `counter_baseline` | TEXT NULL | JSON 摘要 | 差分使用的前一快照 |
| `counter_reset` | INTEGER | 0/1 | 检测到累计器重置 |
| `event_at` | TEXT NULL | UTC | 事件实际发生时间 |
| `recorded_at` | TEXT | UTC | Workbench 记录时间 |
| `source` / `quality` / `parser_version` | TEXT | 同 observations | 事实来源与质量 |
| `merge_status` | TEXT | `primary`, `duplicate`, `conflict`, `unmatched` | 合并状态 |
| `conflict_group_id` | TEXT NULL | UUID | 冲突观测组 |
| `supersedes_id` | TEXT NULL | usage ID | 重解析替代的旧记录 |
| `created_at` | TEXT | UTC | 入库时间 |

**`daily_rollups`**

| 字段 | 类型 | 语义 |
|---|---|---|
| `bucket_date` | TEXT | 用户时区下的 `YYYY-MM-DD` |
| `timezone` | TEXT | 例如 `America/Los_Angeles` |
| `bucket_start_utc` / `bucket_end_utc` | TEXT | 该本地日对应的 UTC 起止点，不固定按 24 小时计算 |
| `tool` / `profile_ref` / `project_ref` / `model` / `provider` | TEXT NULL | 维度 |
| `source` | TEXT | `native`, `proxy`, `cc_switch`, `mixed` |
| `quality` | TEXT | 聚合质量：只要包含 estimated 且无 exact 覆盖则为 estimated；缺失指标为 unavailable |
| `request_count` | INTEGER NULL | 可计量请求数 |
| `input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_creation_tokens` | INTEGER NULL | 聚合 token |
| `recorded_cost_minor` / `estimated_cost_minor` | INTEGER NULL | 实际记录成本 / API-equivalent estimate，币种另列 |
| `currency` | TEXT NULL | 例如 `USD` |
| `source_watermark` | TEXT | 聚合使用的 raw revision |
| `rollup_version` | TEXT | 聚合逻辑版本 |
| `rebuilt_at` | TEXT | 重建时间 |

主键：`(bucket_date, timezone, tool, profile_ref, project_ref, model, provider, source, rollup_version)`。

**`pricing_snapshots`**

| 字段 | 类型 | 语义 |
|---|---|---|
| `id` | TEXT PK | snapshot ID |
| `source_id` | TEXT | `user_snapshot:<name>` 或 `cc_switch:model_pricing` |
| `source_kind` | TEXT | `user_configured` / `cc_switch` |
| `model_key` / `provider` | TEXT | 显式映射后的模型键 / provider |
| `input_price_per_million` / `output_price_per_million` / `cache_read_price_per_million` / `cache_creation_price_per_million` | REAL NULL | 缺失则 NULL，不得补齐 |
| `currency` | TEXT NULL | 必须明确，缺失则拒绝进入可计算集 |
| `unit` | TEXT | 固定 `per_1m_tokens` 或明确支持的单位 |
| `effective_at` | TEXT NULL | 价格生效时间；未知必须保持 NULL，不得用 mtime/导入时间冒充 |
| `published_at` / `source_updated_at` | TEXT NULL | 源数据声称的发布/更新时间 |
| `imported_at` / `observed_at` | TEXT | 本项目导入/读取时间 |
| `parser_version` | TEXT | pricing adapter 版本 |
| `trust_state` | TEXT | `inactive`, `trusted`, `revoked` |
| `validation_status` | TEXT | `valid`, `incomplete`, `rejected` |

**Rollup 失效与重建**：以下任一变化都会把受影响 rollup 标记为 dirty——新增/删除 observation；`parser_version` 变化；`dedup_key`/事件时间/维度/token 数/quality/merge_status 变化；pricing snapshot 启用、撤销或有效区间变化；timezone 配置变化；rollup 算法版本变化。建议增加 `rollup_invalidations` 表（`id`、`bucket_date`、`timezone`、`reason`（`raw_changed`/`parser_changed`/`pricing_changed`/`timezone_changed`/`manual_rebuild`）、`min_observed_at`/`max_observed_at`、`status`（`pending`/`running`/`completed`/`failed`/`cancelled`）、`created_at`）。重建采用“重新从 raw 计算并原子替换 rollup”，不在旧 rollup 上增量叠加；失败时保留旧 rollup 和失败记录。

**DST 规则**：存储时间统一 UTC；日聚合按请求指定的 IANA timezone 转换 `bucket_start_utc`/`bucket_end_utc`；不得按本地时间字符串排序或用 `date + 24h` 推算下一日；无效时区返回 400，不静默回退机器本地时区。

正例：`America/Los_Angeles, 2026-03-08` → `bucket_start_utc=2026-03-08T08:00:00Z`，`bucket_end_utc=2026-03-09T07:00:00Z`（23 小时的 DST 春季跳时日）。反例：把结束时间写成 `2026-03-09T08:00:00Z`（错误地按 24 小时计算）。

验收断言：

- [ ] 每个 token/cost 事实都能追溯到 `observation_id`、`source`、`quality`、`observed_at`、`parser_version`。
- [ ] 未知 token 字段为 NULL，不写成 0。
- [ ] session、supervised-run、proxy 三类 observation 可区分。
- [ ] usage record、rollup、pricing snapshot 三类时间字段不混用。
- [ ] raw usage 变化会使精确受影响的 rollup 进入 `pending`。
- [ ] 重建失败不删除或覆盖旧 rollup；重建是幂等的（同一 raw 输入和算法版本产生相同结果）。
- [ ] 23 小时和 25 小时 DST 日期均按真实 UTC 区间聚合。
- [ ] 无效 timezone 被拒绝，不使用机器本地时区。
- [ ] schema 中不存在写入 CC Switch 数据库的表或迁移路径。

### P2-02：Codex usage 解析

- [x] 处理累计 token snapshot 的差分。
- [x] 识别 input/output/cache/reasoning 语义。
- [ ] 处理 fork、subagent、重放和父子重复。
- [ ] 使用 CC Switch v3.18 修复思路作为测试参考，但实现独立去重。
- [ ] 为 CLI 版本变化保留 token semantics 字段。

#### P2-02 解析与去重契约（2026-07-24 设计细化，经 Codex 评审）

Codex parser 先把累计快照转换为“逻辑事件”，再进入统一 dedup 层，不得直接把每个 snapshot 当作一次请求。标准化事件字段：`tool`（固定 `codex`）、`native_session_id`、`native_event_id`、`turn_id`、`request_id`、`parent_turn_id`、`branch_id`、`snapshot_sequence`、`event_at`、`counter_scope`、`token_counters`、`payload_hash`、`parser_version`。

**累计差分算法**：对同一个 `(tool, profile_ref, native_session_id, turn_id, branch_id, counter_scope)`，按 `event_at`、文件 offset 排序：

1. 首个累计快照产生 `delta = snapshot`。
2. 后续快照若每个非空计数均不小于前值，`delta = current - previous`。
3. 所有计数同时下降视为 counter reset；该快照作为新基线，不把负差分写入 usage。
4. 只有部分字段下降时，标记 `quality=estimated`、`counter_reset=1`，保留可确认的非负字段并记录诊断。
5. 完全相同的 snapshot 不产生新的 delta。

正例：`snapshot A: input=100,output=20` → `snapshot B: input=130,output=25` → `delta: input=30,output=5`。反例：`snapshot B: input=90,output=18`（比 A 小）不能产生 `-10/-2`，应记录 counter reset。

**fork/subagent/replay 去重**：两个 token delta 只有在 `(tool, profile_ref, native_session_id, branch_id, turn_id, request_id 或 normalized_event_position, counter_scope, event_at, token_delta, parser_semantics_version)` 全部相同时才视为同一事件。`request_id` 存在时优先使用；缺失时用 `native_session_id + branch_id + turn_id + source_locator + normalized_event_position + token_delta_hash`。`branch_id` 或 `turn_id` 不同，默认是两个事件，即使 token 数相同；parent turn 与 subagent turn 不得仅因 parent 关系而合并；replay 产生新 request/branch ID 时不得去重。

正例：`A: session=S1,branch=main,turn=T4,request=R9,delta=(100,20)` 与相同的 `B` → duplicate，保留一条 primary。反例：`A` 与 `B: branch=subagent-1,turn=T4,request=R10,delta=(100,20)` → 两个真实事件，不得去重。

验收断言：

- [ ] 累计 snapshot 转成正确 delta；完全重复 snapshot 不增加 token；counter reset 不产生负 token。
- [ ] fork 分支不同即使 token 数相同也保留两条；subagent turn 与 parent turn 不自动合并。
- [ ] replay 只有在稳定 request/event identity 完全一致时才去重。
- [ ] parser 保留 CLI/schema 版本语义；未知 usage record 不使整份 JSONL 失败。
- [ ] 同一 fixture 重复解析结果稳定且幂等。
- [ ] 每条输出都包含 `source`、`quality`、`observed_at`、`parser_version`。

### P2-03：Claude usage 解析

- [x] 解析 input/output/cache read/cache creation。
- [x] 按 message id/content fingerprint 去重。
- [ ] 区分 main/subagent/workflow。
- [x] 可用时交叉校验 `stats-cache.json`，但不把缓存文件作为唯一事实源；不一致只产生诊断和质量标记。

#### P2-03 解析与去重契约（2026-07-24 设计细化，经 Codex 评审）

Claude parser 使用 message/request 级事件作为主要单位。标准化事件字段：`tool`（固定 `claude`）、`native_session_id`、`message_id`、`request_id`、`parent_message_id`、`workflow_id`、`message_role`（`user`/`assistant`/`tool`/`system`）、`content_fingerprint`（脱敏规范化内容 hash）、`event_at`、四类 token 字段、`source_locator`、`parser_version`。

**去重键优先级**：1) `request_id + message_id + token tuple`；2) `message_id + token tuple`；3) `native_session_id + workflow_id + parent_message_id + event_at bucket(±1s) + content_fingerprint + token tuple`；4) 没有稳定 identity 时不得自动去重，只标记 `quality=estimated` 或 `unavailable`，交给 P2-05 观测合并层处理。`event_at bucket` 只能作为弱匹配条件，不能单独用时间和 token 数去重。

正例：两条 `message_id=M7, token=(100,20,0,0)` → duplicate。反例：`message_id=M7` 内容相同但一条 `role=user` 一条 `role=assistant` → 不得去重；两个 subagent message 内容和 token 数相同但 `workflow_id` 不同 → 保留两条。

**`stats-cache.json` 交叉校验**：cache 总数与逐 message 求和一致 → `cross_check=matched`；cache 多于求和 → 不得补写缺失 token，只记录 `cross_check=cache_ahead`；cache 少于求和 → 保留原生解析值，记录 `cross_check=cache_behind`；cache 文件缺失/过期/无法解析 → `cross_check=unavailable`，不降低原生解析结果质量（除非原生数据本身不完整）。

验收断言：

- [ ] input/output/cache read/cache creation 四类字段分别保存。
- [ ] message ID 相同且 token tuple 相同的重复记录只计一次；role/workflow/parent 不同的记录不因内容相同而去重；subagent 不被错误合并到 main workflow。
- [ ] stats cache 只做交叉校验，不作为唯一事实源；cache mismatch 不改写原生 token，只产生质量/诊断信息。
- [ ] 缺失 message ID 时使用明确的弱键，避免静默过度去重。
- [ ] unknown schema record 降级，不使整个 Claude transcript 失败。
- [ ] 每个输出包含 parser version 和 provenance。

### P2-00：升级本项目的 CC Switch 兼容层（前置门禁）

- [ ] 只读探测本机安装版本、`PRAGMA user_version` 和所需表/列能力。
- [ ] 使用脱敏 fixture 覆盖未安装、v10、v16 和未知未来 schema。
- [ ] 记录版本差异对统计字段、去重和数据质量的影响，不把“版本较旧”当成启动失败。
- [ ] 若升级可能改善数据质量，只向用户展示建议；不得调用安装器、包管理器、内置 updater 或 schema migration。
- [ ] 建议用户从 CC Switch 自身软件界面执行完整更新；用户确认更新完成后，才重新探测并重跑兼容测试。
- [ ] 保留 v10 脱敏 schema fixture，不能只测试当前开发机器。
- [ ] （2026-07-23 新增）schema 探测与实际查询绑定同一个短生命周期只读事务，避免 CC Switch 并发写入时读到跨时点不一致数据；探测期间 schema 发生变化时中止本轮，不提交部分结果。
- [ ] （2026-07-23 新增）区分“暂时忙”（`busy_timeout` 重试退避）、“长期不可用”（关闭增强并诊断）、“schema 不兼容”（关闭增强并说明差异）三种状态，分别给出不同 UI 提示，不能只有一种通用错误。
- [ ] （2026-07-23 新增）建立 schema capability 探测结果的缓存和 TTL/失效策略，避免每次查询都重新探测带来的性能开销；价格内容本身的刷新与 schema capability 缓存分离处理。
- [ ] （2026-07-23 新增）明确多个自定义 CC Switch 数据库路径的注册规则，避免重叠数据被重复计数；测试矩阵补充 WAL 模式、文件权限不足、伴随文件（`-wal`/`-shm`）缺失或损坏的场景。
- [ ] （2026-07-23 新增）CC Switch 升级替换数据库文件后，绑定文件身份 + schema version 的 checkpoint，检测到文件被替换时使旧同步游标失效并重新对齐，不盲目继续增量读取。
- [ ] （2026-07-23 新增）对读取到的字段做合法性校验（空值、负数、异常数量级、别名歧义），错误信息经过脱敏后再展示给 UI，不直接暴露本机路径等敏感细节。
- [ ] （2026-07-24 新增）冻结连接器上层返回 DTO：`not_installed`/`disabled`/`available`/`busy`/`corrupt`/`incompatible`/`replaced` 七种状态的枚举和各自的统计回退行为（见下方状态表）。
- [ ] （2026-07-24 新增）只读边界覆盖全部调用路径，不仅 probe：pricing adapter、proxy import、reconcile、cursor checkpoint 都必须明确“只写 Workbench DB，不写 CC Switch DB”。
- [ ] （2026-07-24 新增）文件身份定义具体化，不依赖 Windows 下语义不稳定的 inode：`db_identity = sha256(main_db metadata + first/last bounded bytes + file size)`，结合绝对路径规范化、mtime、size、sidecar 状态；不得为计算 identity 而复制或修改第三方数据库。
- [ ] （2026-07-24 新增）schema capability 缓存失效条件枚举：TTL 到期、DB identity 变化、`user_version` 变化、schema hash 变化、读取失败、用户手动触发重新探测。
- [ ] （2026-07-24 新增）列出实际允许读取的表和列（白名单，而不是抽象说“白名单查询”）：例如 request ID、model、provider、status、latency、TTFT、recorded cost；明确拒绝 credentials、secrets、provider config JSON。
- [ ] （2026-07-24 新增）多数据库路径（默认路径/自定义路径/环境变量路径）的发现顺序、去重身份和“同一逻辑来源多个 DB”的展示规则落表。
- [ ] （2026-07-24 新增）busy（暂时不可用，可重试）与 incompatible（能力差异）在 API/UI 上分别提示，不能统一显示 generic error。
- [ ] （2026-07-24 新增）CC Switch v10/v16/future fixture 的期望字段矩阵：每个 fixture 明确支持哪些统计字段、缺失字段对应 unavailable、哪些字段禁止读取、是否允许继续使用 native baseline、pricing 是否可探测但默认 inactive。
- [ ] （2026-07-24 新增）验收断言：即使用户拒绝升级或 CC Switch 不存在，Phase 2 基础统计仍完整可用（“升级建议”不得与运行时依赖混淆）。
- [ ] （2026-07-24 新增）CC Switch 的版本、schema、能力、错误、信任动作和禁用动作只写入 Workbench 自有 audit 表，不回写 CC Switch。

CC Switch 是否升级不属于本 Phase 的执行范围，也不是本 Phase 的阻塞项。

### P2-04：CC Switch 只读连接器与 pricing adapter

- [x] 默认发现 `~/.cc-switch/cc-switch.db`，支持自定义路径。
- [x] 使用 `mode=ro`、短事务、busy timeout。
- [ ] 先探测 `user_version/sqlite_master/table_info`，再构造白名单查询。
- [ ] 禁止读取 provider 凭据配置和敏感 JSON。
- [ ] 数据库缺失、忙、损坏、未来 schema 时关闭增强并给出诊断。
- [ ] 记录连接状态、版本、最后同步游标和错误，不复制整个第三方 DB。

`model_pricing` 接入 pricing source（2026-07-23 确认，方案 C：只读探测为候选来源，默认不启用，用户显式信任后才生效；只产生 API-equivalent estimate，不得改写 token/会话/实际成本事实；用户自建 snapshot 优先级高于此来源，冲突需显式展示不能静默覆盖）：

- [x] 把 `model_pricing` 实现为独立的 pricing adapter，与 `proxy_request_logs`/UsageRecord 的事实导入流程完全分离。
- [ ] 按 CC Switch schema 版本（v10/v16/未知未来）为 `model_pricing` 建立脱敏 fixture，验证列结构、类型和单位语义；验证完成前不得自动启用此来源。
- [ ] 设立准入规则：记录缺少价格数值、币种或计价单位时拒绝进入可计算集，不得用推测值补齐。
- [ ] 明确区分并分别标注四个时间概念：`effective_at`（价格生效时间，无明确字段/语义时标记未知）、价格本身的更新时间（无字段时不得使用 mtime 冒充）、本项目的导入时间、本项目的观察/读取时间。
- [ ] 定义来源优先级和冲突展示规则：用户手动配置的价格 snapshot 优先于 CC Switch 来源；两者都存在且不一致时并排显示，不静默选择。
- [ ] 建立模型名到 CC Switch 价格记录的显式、可审计别名映射，不做隐式模糊匹配。
- [ ] 来源被用户禁用或移除后，历史已生成的估算保持可审计（不删除、不静默改写），但不得继续用于新估算，也不得回填为实际成本。

#### P2-04 连接器状态与返回契约（2026-07-24 设计细化，经 Codex 评审）

**连接器状态**

| 状态 | 含义 | 统计行为 |
|---|---|---|
| `not_installed` | DB 不存在 | 原生统计正常，CC 增强 unavailable |
| `disabled` | 用户关闭连接 | 不读 DB |
| `available` | schema/字段兼容 | 可读取批准白名单 |
| `busy` | 短事务超时 | 本次增强 unavailable，保留错误原因 |
| `corrupt` | SQLite 损坏 | 不重试修复，不迁移 |
| `incompatible` | schema 不满足白名单 | 关闭增强并返回能力差异 |
| `replaced` | 文件身份变化 | 清空连接器 checkpoint，重新探测 |

连接器返回形状：

```json
{
  "state": "available",
  "db_identity": "sha256:...",
  "user_version": 16,
  "schema_capabilities": {
    "proxy_requests": true,
    "request_id": true,
    "recorded_cost": true,
    "model_pricing": false
  },
  "cursor": {
    "table": "proxy_requests",
    "last_row_key": "1234",
    "schema_version": 16,
    "db_identity": "sha256:..."
  },
  "last_sync_at": "2026-07-24T12:00:00Z",
  "error": null
}
```

pricing adapter 返回形状：

```json
{
  "source_id": "cc_switch:model_pricing",
  "enabled": false,
  "records": [],
  "rejected_records": [{ "model_key": "x", "reason": "missing_currency" }],
  "observed_at": "2026-07-24T12:00:00Z",
  "parser_version": "cc-switch-pricing-v1"
}
```

必须明确：读取 `model_pricing` 不会修改任何 usage record；默认 `enabled=false`；用户显式信任后最多生成 `api_equivalent_estimate`；没有 `effective_at` 时记录 NULL，不使用 DB mtime 冒充；用户 snapshot 优先；冲突时两套价格都可审计，不静默覆盖。

验收断言：

- [ ] CC Switch 未安装、关闭、busy、corrupt、incompatible 时 native baseline 不变。
- [ ] 连接器只访问批准表列；不执行 DDL、VACUUM、journal_mode、INSERT、UPDATE、DELETE。
- [ ] 只读测试同时比较主 DB、WAL、SHM、journal 的 hash/mtime。
- [ ] 文件替换后旧 cursor 不继续使用。
- [ ] pricing adapter 默认不启用；字段缺 currency/unit/effective semantics 时拒绝进入可计算集合；CC Switch 价格只能产生 estimate，不能改变 actual。
- [ ] provider credentials、secret JSON 和 API key 永不进入返回 DTO 或日志。
- [ ] 锁超时返回 `busy`，不执行修复或无限重试。

### P2-05：去重和观测合并

- [ ] `session_log/codex_session` 默认只用于交叉校验，不二次计 token。
- [x] `proxy` observation 补充 TTFT、status、provider、latency、recorded cost。
- [ ] 优先 request id；缺失时使用 session/time/model/token fingerprint。
- [ ] 保留冲突观测并标记，不静默选择更好看的数字。
- [ ] 为 CC Switch v3.17 双计样本建立回归测试。

#### P2-05 匹配与合并契约（2026-07-24 设计细化，经 Codex 评审）

原则：保留所有原始 observations，另建合并关系，不删除“较差”观测；不得用“数字较大者覆盖较小者”。

**匹配层级**（对一个 `session_observation` 和一个 `proxy_observation`）

| 层级 | 条件 | 结果 |
|---|---|---|
| 1 | 两者 `request_id` 非空且完全相同 | strong match |
| 2 | request ID 缺失，但 session/profile/model/provider 相同，时间差 ≤2 秒，token tuple 完全相同 | token match |
| 3 | 无 token tuple，但 session/model 相同，时间差 ≤2 秒，且 proxy 的 request start 与 session event 相邻 | weak match |
| 4 | 仅 session 或 model 相同 | 不合并，保留两条 |
| 5 | 时间相同但 provider/model 不同 | 不合并，标记 possible conflict |

建议增加 `observation_links` 表：`id`、`left_observation_id`（通常 session）、`right_observation_id`（通常 proxy）、`match_level`（`request_id`/`token_fingerprint`/`weak`/`none`）、`match_score`（可选，不能代替规则）、`decision`（`deduplicated`/`kept_both`/`conflict`/`rejected`）、`primary_observation_id`（只有 deduplicated 时填写）、`conflict_group_id`、`reason_code`、`created_at`、`algorithm_version`。

usage record 上同步字段：`merge_status`、`conflict_group_id`、`merge_role`、`counting_policy`（如 `count_separately`）、`match_reason`、`algorithm_version`。

**Tie-break 规则**：同一 request ID 且 token 完全一致——只保留一个计量 record，session 作为 token 主来源，proxy 作为 latency/status/provider enrichment。两者都有 recorded actual cost 且金额不同——`decision=conflict`，两条成本分别保存，不覆盖。session 有 token、proxy 无 token——token 来自 session，proxy 只补充 TTFT/status/latency。proxy 有 recorded actual、session 只有 subscription token——两者分别保留，recorded actual 不得替代 session token 事实。时间和 session 匹配但 token 不同——`kept_both` 或 `conflict`，默认不去重。

正例：`session request_id=R1, tokens=(100,20)` 与 `proxy request_id=R1, tokens=(100,20), ttft=300ms` → 一次 token 计量，保留 proxy latency。反例：`proxy request_id=R1, tokens=(150,30)`（与 session 不同）→ conflict，不能选较大数，也不能静默丢弃一方。

UI 展示形状：

```json
{
  "request_id": "R9",
  "tokens": { "value": 120, "quality": "exact", "source": "codex_jsonl" },
  "latency": { "value_ms": 842, "quality": "exact", "source": "proxy_log" },
  "merge": {
    "status": "conflict",
    "label": "同一请求存在两组不一致观测",
    "counting_policy": "不自动合并",
    "details_endpoint": "/api/ai-workbench/observations/conf-01"
  }
}
```

验收断言：

- [ ] 所有原始 observations 仍可审计。
- [x] request ID 相同且 token 相同只计一次；request ID 相同但 token 不同产生 conflict。
- [ ] weak match 不能单独触发删除或覆盖；proxy enrichment 不会二次计入 token。
- [ ] recorded actual 与 subscription/API estimate 始终分开。
- [x] conflict 记录包含实际 `conflict_group_id`、`merge_status`、`counting_policy`、`reason_code`；UI 能显示冲突原因和详情入口。
- [ ] 合并算法版本变化会使相关 rollup 失效。
- [ ] P2-05 的双计样本和重复样本均可回归验证。

### P2-06：成本语义

- [ ] 区分 recorded actual、API-equivalent estimate 和 unavailable。
- [ ] 2026-07-23 确认：项目不维护内置权威价格表，只实现可插拔 pricing source；价格来自用户导入/配置的本地 snapshot，每条估算附带来源、生效时间、更新时间和币种；没有价格源时成本显示为不可用，不得显示 0 或误导性默认值。CC Switch 的 `model_pricing` 可作为默认不启用的候选来源，见 P2-04。
- [ ] 价格按生效时间保存 snapshot，不用今天价格重写历史。
- [ ] 订阅登录仅显示估算，不能显示“已花费”。

#### P2-06 成本对象与定价匹配契约（2026-07-24 设计细化，经 Codex 评审）

所有 API、rollup 和 CSV 使用统一成本对象，不使用裸数字：

```json
{
  "recorded_actual": {
    "status": "available", "amount_minor": 37, "currency": "USD",
    "source": "proxy_log", "quality": "exact",
    "observed_at": "2026-07-24T10:00:03Z", "recorded_at": "2026-07-24T10:00:04Z",
    "label": "recorded actual"
  },
  "api_equivalent_estimate": {
    "status": "available", "amount_minor": 52, "currency": "USD",
    "source": "user_snapshot:default", "quality": "estimated",
    "pricing_snapshot_id": "price-123", "effective_at": "2026-07-01T00:00:00Z",
    "observed_at": "2026-07-24T10:00:05Z",
    "formula": { "input_tokens": 1000, "input_price_per_million": 20, "output_tokens": 200, "output_price_per_million": 160 },
    "label": "API-equivalent estimate"
  }
}
```

不可用时两个字段各自返回 `{"status":"unavailable","amount_minor":null,"reason_code":"...","source":...,"quality":"unavailable"}`；不得返回 `{"cost": 0}`。

**pricing snapshot 匹配**：对 usage record 的 `event_at`——只选 `trust_state=trusted` 且 `validation_status=valid`；按显式 model/provider mapping 匹配；若多个 snapshot 的 `effective_at <= event_at`，取 `effective_at` 最大者；若 `effective_at` 全部为 NULL，不得按 `imported_at`/文件 mtime/当前时间推测历史价格，默认返回 unavailable，可在 UI 显示“价格存在但历史生效时间未知”；若没有过去生效的价格但有未来价格，不得用于历史 usage；用户 snapshot 与 CC Switch snapshot 同时存在时用户 snapshot 优先，冲突写入审计信息。

正例：`usage event: 2026-06-15`，价格 `2026-01-01→$10`、`2026-06-01→$12` → 使用 $12。反例：`usage event: 2026-02-01`，价格 `imported_at=2026-07-24, effective_at=NULL` → unavailable，不使用 $12，也不用当前价格倒推。

验收断言：

- [x] API 中 actual、estimate、unavailable 是三个可区分对象；actual 只来自明确 recorded actual source；subscription token 永远不产生 actual 标签。
- [x] 没有价格源时金额为 NULL 且有 reason code。
- [x] 历史 usage 使用当时生效的 snapshot；unknown `effective_at` 不用 mtime/import time 代替；未来价格不用于过去 usage。
- [x] CC Switch price 只产生 estimate。
- [ ] 每个 estimate 包含 source、snapshot ID、effective_at、currency、formula。
- [ ] CSV/API/UI 均不把 unavailable 显示为 0。

### P2-07：统计 API

- [x] overview、timeseries、breakdown、reliability、data-quality。
- [x] 统一日期、工具、profile、项目、模型、provider、source 过滤器。
- [x] 对大范围查询使用 rollup 和查询上限。
- [x] 返回 metric availability，不用 0 代替缺失。

#### P2-07 API 契约（2026-07-24 设计细化，经 Codex 评审）

统一前缀 `/api/ai-workbench/statistics`。

**通用 query 参数**：`from`/`to`（`YYYY-MM-DD`，含端点）、`timezone`（IANA，默认用户配置，无效返回 400）、`tool`/`profile`/`project`/`model`/`provider`/`source`（重复参数）、`quality`（`exact`/`estimated`/`unavailable`）、`include`（`summary`/`details`）、`limit`（最大 5000）、`cursor`。

**Route 列表**

| Method | Path | 响应 |
|---|---|---|
| GET | `/overview` | KPI 总览 |
| GET | `/timeseries` | 按日/小时序列 |
| GET | `/breakdown` | 按 tool/profile/project/model/provider/source 分组 |
| GET | `/reliability` | status、TTFT、latency、错误率 |
| GET | `/data-quality` | exact/estimated/unavailable 分布和原因 |
| GET | `/export.csv` | CSV 导出 |
| GET | `/rollups/status` | dirty/pending/rebuild 状态 |

**统一 metric shape**（不可用）：

```json
{ "key": "input_tokens", "value": null, "unit": "tokens", "availability": "unavailable", "quality": "unavailable", "source": null, "reason_code": "no_native_usage", "display": "—" }
```

可用时 `value` 为实数，`availability: "available"`，`quality` 为 `exact`/`estimated`，`reason_code: null`，`display` 为格式化字符串（如 `"1,200"`）。

`/overview` 响应包含 `range`（from/to/timezone）、`metrics`（每项都是上述 metric shape）、`data_quality`（exact/estimated/unavailable 记录数）、`generated_at`。`/timeseries` 按 `bucket`（`day`）返回 `items[]`，每项含 `date`、`bucket_start_utc`、`bucket_end_utc`、`metrics`。`/breakdown` 返回 `group_by` 维度列表和 `items[]`（`dimensions` + `metrics`）。`/reliability` 返回 `success_rate`、`ttft_ms` 等 metric。`/data-quality` 返回 `counts`（exact/estimated/unavailable）、`reasons[]`（`reason_code`/`count`/`affected_metrics`）、`sources[]`（`source`/`quality`/`record_count`）。

**查询边界**：`from > to` 返回 400；单次范围超过配置上限返回 413 或明确业务错误，不偷偷扫描无限历史；大范围优先用 rollup，短范围可读 raw；raw 与 rollup 不一致时返回 `rollup_stale=true` 和状态信息，不静默返回旧数字；`value=null` 必须伴随 `availability=unavailable` 和 `reason_code`；真实 0 必须是 `value=0`、`availability=available`，不能与 null 混淆。

验收断言：

- [ ] 五类统计 endpoint 均存在明确 method/path/query contract；所有 endpoint 使用统一过滤参数。
- [ ] 每个 metric 带 `availability`、`quality`、`source`；unavailable 是 `value=null` 不是 0；真实 0 与 unavailable 可区分。
- [x] 无效日期、timezone、filter enum、过大范围返回明确 4xx。
- [ ] DST 日期返回真实 bucket UTC 边界。
- [ ] CC Switch 关闭时 overview/timeseries 仍可用；rollup stale 状态不会伪装成最新统计。
- [x] CSV endpoint 与 JSON 使用相同过滤语义。

### P2-08：统计 UI

- [ ] 紧凑 KPI、趋势、breakdown 表和可靠性区。
- [ ] 每项显示 exact/estimated/unavailable。
- [ ] 可展开数据来源、公式和缺失原因。
- [ ] CC Switch 连接器关闭时保持相同布局。
- [ ] 支持 CSV 导出原始数值及质量字段。

#### P2-08 UI 契约（2026-07-24 设计细化，经 Codex 评审）

**KPI tile 数据契约**：`MetricViewModel { key, value: number|null, unit: 'tokens'|'count'|'ms'|'currency', availability, quality, source, reasonCode, displayValue, label, formula? }`。

显示规则：`exact` 显示数字+`Exact`标签，可展开 source；`estimated` 显示数字+`Estimated`标签，可展开 source/价格 snapshot/公式；`unavailable` 显示 `—`+`Unavailable`标签，可展开 reason，不显示数字 0；`exact` 值为 0 时显示 `0`+`Exact`标签，说明是真实零值。

正例：`API-equivalent estimate: $0.52`，标签 `Estimated`，来源 `user_snapshot:default`。反例：没有价格源时显示 `$0.00`——应显示 `—` + 原因 `No trusted pricing source`。

**组件数据契约**：`StatisticsPage` 只消费 normalized API DTO；`KpiGrid` 接收 `MetricViewModel[]`；`TimeseriesChart` 接收每个点的 metric object 而非裸数字；`BreakdownTable` 每行保留 dimensions 和 metric provenance；`ReliabilityPanel` 对缺失 proxy 数据显示 unavailable；CC Switch connector 状态只影响增强字段，不改变基础布局或隐藏整个页面；错误状态与“无数据”状态区分。

**CSV 列集合**（固定列，至少包含）：`bucket_date`、`bucket_start_utc`、`bucket_end_utc`、`timezone`、`tool`、`profile_ref`、`project_ref`、`model`、`provider`、`source`、`quality`、`availability`、`reason_code`、`request_count`、`input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_creation_tokens`、`reasoning_tokens`、`total_tokens`、`recorded_actual_amount_minor`、`recorded_actual_currency`、`recorded_actual_source`、`recorded_actual_quality`、`api_equivalent_estimate_amount_minor`、`api_equivalent_estimate_currency`、`api_equivalent_estimate_source`、`api_equivalent_estimate_quality`、`pricing_snapshot_id`、`pricing_effective_at`、`merge_status`、`conflict_group_id`、`parser_version`、`rollup_version`。不可用字段值为空，但 `availability=unavailable`、`quality=unavailable`、`reason_code` 必须存在。

验收断言：

- [ ] KPI exact/estimated/unavailable 三态可见；unavailable 显示 `—`，不显示 0。
- [ ] 用户能展开查看 source、reason、formula；actual 与 estimate 使用不同视觉标签和字段。
- [ ] 缺少 CC Switch 时页面布局不变化；API 错误不显示成空数据。
- [x] CSV 包含 source、quality、availability、reason_code；包含 actual 和 estimate 的独立列；包含 pricing snapshot 和 parser version（当前无数据时对应字段为空）。
- [ ] 冲突观测在表格中显示冲突状态，而非静默合并。
- [ ] 空日期范围、真实零值和 unavailable 三者视觉上可区分。

### P2-09：维护与重建

- [x] 支持只重建 Workbench usage 和 rollup。
- [x] 重建不触碰 CC Switch DB。
- [x] 提供 parser version 迁移、进度、取消和失败恢复；支持的 parser 版本迁移会写入 job audit，未知版本明确拒绝。
- [x] 重建前后生成数量与总量审计摘要。

#### P2-09 重建契约（2026-07-24 设计细化，经 Codex 评审）

引入 rebuild job，不让 HTTP 请求同步执行全量重建。`scope=workbench_usage_and_rollup` 只允许触碰 Workbench 自有 `observations`/`usage_records`/`observation_links`/`daily_rollups`/自有 invalidation/job/audit 表、自有 pricing snapshot 派生 estimate；明确不触碰 Codex/Claude 原生 transcript、`~/.cc-switch/cc-switch.db` 及 sidecar、CC Switch credentials/provider JSON、proxy 原始日志文件、Phase 1 session index、外部软件安装/升级/修复/updater。

**API**

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/ai-workbench/statistics/rebuild` | 创建重建任务 |
| GET | `/api/ai-workbench/statistics/rebuild/{job_id}` | 查询状态 |
| POST | `/api/ai-workbench/statistics/rebuild/{job_id}/cancel` | 请求取消 |
| GET | `/api/ai-workbench/statistics/rebuild/{job_id}/audit` | 前后审计摘要 |

请求体：`{"scope": "workbench_usage_and_rollup", "from": "...", "to": "...", "timezone": "...", "parser_version": "current", "include_pricing_estimates": true}`。

**状态机**：`queued → running → cancelling → cancelled` / `completed` / `failed`。`queued` 可取消；`running` 收到取消后进入 `cancelling`，在当前批次完成后变为 `cancelled`；`completed`/`failed`/`cancelled` 为终态，不可重复 cancel；同一 scope/date range 已有 running job 时返回 409 或复用已有 job；进程崩溃后下次启动将过期 `running` 标记为 `failed`，保留 checkpoint。

**`rebuild_jobs` 持久化表**（2026-07-24 补充，经 Codex 评审）：

| 字段 | 类型 | 语义 |
|---|---|---|
| `job_id` | TEXT | PK，UUID |
| `job_type` | TEXT | 重建范围/类型 |
| `status` | TEXT | `queued`/`running`/`cancel_requested`/`cancelled`/`failed`/`completed`/`interrupted` |
| `scope_json` | TEXT | 重建范围、过滤条件 |
| `parser_version` | TEXT | 本次使用的解析器版本 |
| `requested_at` / `started_at` / `finished_at` | INTEGER | Unix 秒时间戳 |
| `heartbeat_at` | INTEGER | 最近进度心跳，用于判定失联 |
| `cancel_requested_at` | INTEGER | 取消请求时间 |
| `worker_id` | TEXT | 进程/工作者标识，用于重启后识别失联任务 |
| `attempt_no` | INTEGER | 当前尝试次数 |
| `checkpoint_json` | TEXT | 可恢复游标、阶段、批次等 checkpoint |
| `progress_json` | TEXT | 已处理数量、总量、百分比 |
| `error_code` / `error_message` | TEXT | 稳定错误分类 / 脱敏后的错误摘要 |
| `before_summary_json` / `after_summary_json` / `delta_summary_json` | TEXT | 重建前/后/差异摘要 |
| `created_at` / `updated_at` | INTEGER | 记录创建/最近更新时间 |

进程重启后，`worker_id` 与 `heartbeat_at` 超时未更新的 `running` job 判定为失联，转 `failed` 并保留 `checkpoint_json` 供下次重试复用。

**原子性和失败恢复**：raw usage 解析阶段写入 staging revision；rollup 计算写入临时 revision；全部成功后在 Workbench DB 内事务性切换 active revision；取消或失败只删除 staging/temp revision，旧 active rollup 保持可读；每个 bucket 完成后保存 checkpoint；重试从最近安全 checkpoint 重新计算，不在旧 rollup 上继续叠加；`daily_rollups` 增加 `data_revision`/`build_id`，避免混用不同版本结果。

**审计摘要**：`before`/`after` 均含 `observation_count`、`usage_record_count`、`rollup_bucket_count`、`token_totals`、`actual_cost_minor`、`estimate_cost_minor`、`quality_counts`、`conflict_count`、`parser_versions`；`delta` 为对应字段差值；`reasons[]` 说明触发原因（如 `parser_version_changed`、`dedup_algorithm_changed`）；`external_files_modified: []` 和 `cc_switch_db_modified: false` 必须显式出现。若计数变化不能解释，审计响应必须包含 `reason_code`，不能只显示数字差异。

验收断言：

- [ ] scope 明确限制为 Workbench usage/rollup；rebuild 不写入、迁移、锁定或修改 CC Switch DB。
- [ ] job 有完整状态机、进度、checkpoint、取消和失败状态，且状态持久化在 `rebuild_jobs` 表中，进程重启后可查询。
- [ ] 取消不会删除当前可读的旧 rollup；失败不会留下半套 active rollup。
- [ ] 重试是幂等的，不会重复加 token；并发重复 rebuild 被拒绝或复用。
- [ ] 审计包含 before/after/delta、quality、parser version、conflict count，以及 `external_files_modified=[]` 和 `cc_switch_db_modified=false`。
- [ ] parser/merge/pricing 变化会说明触发原因。
- [ ] 维护任务不会读取或写入第三方 credentials。

## 六张附加表是否可合并（2026-07-24，经 Codex 评审确认）

`observations`、`usage_records`、`daily_rollups`、`pricing_snapshots`、`rollup_invalidations`、`observation_links`、`rebuild_jobs` 七张表均不建议合并：`observations` 是原始观测事实，`usage_records` 是规范化用量记录，`daily_rollups` 是派生聚合，`pricing_snapshots` 是价格版本，`rollup_invalidations` 是失效队列，`observation_links` 是关系映射，`rebuild_jobs` 是维护任务状态——七者生命周期、粒度和写入语义均不同，合并会破坏对应的退出标准（例如把 `observation_links` 并入 `usage_records` 会让“保留冲突观测并标记，不静默选择”失去独立可审计的匹配记录）。

## 测试矩阵

- CC Switch：未安装、v10、v16、future version、busy、corrupt、无 proxy rows。
- 来源：仅原生日志、仅 proxy fixture、两者重叠、冲突、重复。
- 统计：缓存 token、累计差分、fork/subagent、时区/DST、模型切换。
- UI：exact/estimated/unavailable 混合、空时间段、大数量、connector 失败。

## 退出标准

- 未安装 CC Switch 时基础 token、会话、Turn、工具统计完整可用。
- 安装 CC Switch 时只增加可证明的丰富字段，不改变基础计数。
- v10/v16 和缺失数据库均通过测试。
- CC Switch 数据库在连接器测试前后哈希不因本项目改变。
- fork/subagent 重放不造成重复 token。
- recorded cost 和 estimate 在 API、UI、导出中始终分离。
- 所有不可用指标显示 `—` 和原因，不显示 0。

## 风险与回滚

- 风险：外部软件版本差异改变字段或统计语义。措施：只读能力探测、版本化 fixture、数据质量标签和兼容降级；本项目不执行外部升级。
- 风险：第三方 schema 继续变化。措施：字段探测、白名单、未来版本 fallback。
- 风险：观测去重误合并。措施：保留 observation、可审计匹配原因、冲突不覆盖。
- 回滚：禁用 CC Switch connector 后重新从原生日志构建；没有由本项目触发的外部软件升级需要回滚。

## 审查记录

- 2026-07-23：经 Codex 头脑风暴确认模型价格表方案（不维护内置权威价格表，只做可插拔 pricing source），已同步到 P2-06 和架构文档 §19 决策记录。本 Phase 状态仍为 `待审查`，此次只是补充范围，未批准实施。
- 2026-07-23：经 Codex 仔细评估 CC Switch `model_pricing` 接入方案（方案 C：只读探测为候选来源，默认不启用）和 P2-00/P2-04 的兼容性设计缺口，已把具体子项补进 P2-00（一致性读取、锁状态区分、schema 缓存、多数据库路径、文件替换游标失效、字段校验脱敏）和 P2-04（pricing adapter 分离、版本 fixture、准入规则、时间字段区分、来源优先级、别名映射、禁用后可审计）。本 Phase 状态仍为 `待审查`。
- 2026-07-24：经 Codex 三轮设计评审（P2-01~P2-09 完整合同提案 → 表数量最小化/`rebuild_jobs` 字段/退出标准冲突检查的追问 → 确认结果），把全部任务细化到 P1-12 同等严谨度：具体表结构、去重算法、cost 三态对象、API 路由/参数/响应形状、UI 组件契约、CSV 列集合、rebuild 状态机全部落表；同时确认新增表集合与现有退出标准“无冲突”，且七张表均无法合并（各自生命周期、粒度、写入语义不同）。新增“任务实施顺序”小节，明确实际实施顺序为 P2-01 → P2-02/P2-03（并列）→ P2-00 前置门禁 → P2-04 → P2-05 → P2-06 → P2-07 → P2-08 → P2-09，任务编号仍沿用主题编号。
- 2026-07-24：用户确认细化结果无需单独展示审查，直接批准 Phase 2 进入实施，状态改为 `已批准`；按用户指示，实施期间不再逐任务向用户汇报，只在整个 Phase 2 完成后一起验收（与 Phase 1 的 P1-12→P1-14→P1-13 模式一致）。

## 执行证据

- 规划时验证：本机 CC Switch 3.15.0/schema v10；官方 3.18.0/schema v16。
