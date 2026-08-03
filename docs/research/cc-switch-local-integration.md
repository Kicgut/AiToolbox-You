# CC Switch 本机集成调研（只读）

> 状态：调研结论；已采纳为受限只读用量适配边界
> 更新时间：2026-08-03-07-07-39
> 创建时间：2026-08-01-22-01-01
> 适用范围：CC Switch 的本机只读能力、Token 用量/订阅额度/余额边界，以及 AI Coding Workbench 的可选数据源决策
> 不包含：读取任何凭据、供应商配置值、日志正文、请求记录内容或余额原文；也不包含 CC Switch 写入、升级、逆向 IPC 或实现 Workbench 连接器。

> 初始调研范围：本机已安装的 CC Switch 3.18.0；不读取凭据、供应商配置值、日志正文或数据库记录内容。

## 0. 2026-08-02 补充：Token 用量的记录方式与可复用边界

### 0.1 结论

CC Switch 的 **Token 用量统计** 与其“订阅额度 / API 余额”不是同一种数据，也不应使用同一结论：

| 问题 | 已验证结论 |
| --- | --- |
| Token 怎样记录 | 两条来源并行：经过 CC Switch 本地代理的请求会写请求日志；Codex / Claude / Gemini 的原生会话 JSONL 可被其周期扫描并导入。官方文档称 Codex 是精确 JSONL 解析，不再使用旧估算。 |
| 记录在哪里 | 本机 CC Switch 3.18.0 的 `~/.cc-switch/cc-switch.db`（SQLite，`user_version=16`）存在 `proxy_request_logs` 明细与 `usage_daily_rollups` 日汇总；本次只读确认了表/列/索引，未读取任何记录。 |
| CC Switch 未启动时能否记录 | **代理请求不能**：代理服务、应用接管和日志记录均需运行。**会话日志可在之后补齐，但不是实时记录**：CC Switch 启动时同步，之后约每 60 秒扫描；只有对应应用已启用、来源 JSONL 仍存在且目录被支持时，才可能导入历史 usage。 |
| 能否把它当成事实来源 | 它可作为“CC Switch 已观测范围”的高价值汇总视图；不能替代原生 transcript 的会话事实来源，也不能承诺覆盖所有本机会话、所有自定义目录、所有工具或所有版本。 |
| 订阅额度/余额能否同样读取 | 不能据此推出。其订阅/脚本查询结果由进程内 `UsageCache` 持有，重启即空；它不是已发布的持久化第三方读取契约。 |

官方用量文档明确区分代理日志（须代理服务运行、接管与日志开启）和 CLI 会话日志（不要求代理，但要求 CC Switch 周期扫描会话目录），并说明 Token/成本计算存在自己的标准化与估算口径。[官方 Usage Statistics 文档](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/4-proxy/4.4-usage.md)

本机元数据确认的 `proxy_request_logs` 含 `request_id`、应用/提供商/模型、输入/输出/缓存 Token、成本、延迟、状态、`session_id`、`created_at` 与 `data_source`；`usage_daily_rollups` 含日期、应用/提供商/模型、请求数、成功数、Token、成本和延迟；`session_log_sync` 保存来源文件路径、修改时间、已读取行偏移和上次同步时间。两类统计表有专用索引，说明它们是 CC Switch 自己的持久化统计实现，但**表名/列/语义并未被发布为跨版本 API 契约**。上游源码还显示：明细默认仅保留约 30 天，之后滚入日汇总并删除，因此不能把它当作永久逐请求审计库。

实现证据分别见上游的 [数据库路径/启动清理](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/database/mod.rs#L96-L102)、[usage 表 schema](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/database/schema.rs#L194-L232)、[会话同步水位](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/database/schema.rs#L272-L309)、[代理写入](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/proxy/usage/logger.rs#L101-L223)、[启动后 60 秒会话扫描](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/lib.rs#L1225-L1266) 与 [30 天 rollup/prune](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/database/dao/usage_rollup.rs#L11-L19)。

### 0.2 已采纳的产品边界

不应把 CC Switch 的明细复制进 Workbench，也不应让 Workbench 重做同一份代理日志账本；可考虑增加一个显式启用的 `CcSwitchAggregateAdapter`：

1. 仅在版本/Schema allowlist 命中时，以 SQLite 只读方式查询日汇总或受限聚合；禁止读取 `providers`、`settings`、日志正文、请求参数、响应摘要及任何凭据字段。
2. UI 标注为“CC Switch 聚合用量（覆盖范围由 CC Switch 决定）”，显示版本、schema、最后修改时间、刷新时间和 `unavailable/stale` 状态；不伪装为厂商账单或完整本机总 Token。
3. Workbench 不持久化 CC Switch 明细；最多保存用户是否启用、兼容状态与最后一次成功聚合时间。没有兼容版本、数据库锁定或读取异常时降级为不可用。
4. 同一张总览/用量视图中，CC Switch 聚合与 Workbench 原生会话解析必须**二选一作为总数来源**，绝不能相加；需要会话级定位、未覆盖目录或 CC Switch 未运行期间的完整性时，回退原生 JSONL 按需解析。
5. 订阅套餐额度和 API 余额继续优先使用厂商官方连接器；CC Switch 的进程内缓存不作为自动读取来源。

该方案能减少 Workbench 自建近期 Token 明细/日汇总的重复工作，但引入对 CC Switch 私有 SQLite 的版本耦合。因此已确认它只是显式启用、版本化的“读取现成聚合结果”能力，而不是核心依赖；采用范围、项目历史回退与实现任务以[架构文档](../ai-coding-workbench-architecture.md#9-用量统计订阅额度与账户余额)和 Phase 2 为准。

## 1. 本机确认结果

| 项目 | 结果 |
|---|---|
| 已安装版本 | CC Switch **3.18.0**（Windows 用户级安装） |
| 可执行文件 | `C:\Users\YOU2\AppData\Local\Programs\CC Switch\cc-switch.exe` |
| 运行情况 | 调研时 `cc-switch.exe` 正在运行；其 WebView2 用户资料目录为 `C:\Users\YOU2\AppData\Local\com.ccswitch.desktop\EBWebView`，仅是嵌入式浏览器缓存，不是 Workbench 集成目标。 |
| 主数据目录 | `C:\Users\YOU2\.cc-switch\` |
| 主数据库 | `C:\Users\YOU2\.cc-switch\cc-switch.db`，SQLite，`PRAGMA user_version = 16` |
| 设置文件 | `C:\Users\YOU2\.cc-switch\settings.json`；仅确认顶层存在 `usageConfirmed` 等设置键，**未记录或输出任何设置值，更未读取凭据**。 |
| 备份与日志 | `C:\Users\YOU2\.cc-switch\backups\db_backup_*.db`、`C:\Users\YOU2\.cc-switch\logs\cc-switch.log`、`crash.log`。它们可能含配置或诊断信息，不应作为 Workbench 的读取来源。 |
| 本地服务 API | 调研时未发现由 `cc-switch.exe` 持有的 TCP 监听端口。源码中的 `get_usage_summary` 等是 Tauri 前端到桌面进程的内部 IPC command，不是对外发布的 localhost/public API；官方用户手册也未发布供第三方消费的本地 HTTP/IPC API 或数据契约。因此不能把“未发现端口”误作 API 保证。 |

路径均为本机实际探测结果；安装位置和数据库版本会随安装方式、用户目录和 CC Switch 更新而变化，不能硬编码为跨版本契约。

官方源码的默认目录计算也使用用户 home 下的 `.cc-switch`，允许自定义存储目录，并保留旧路径回退分支；这进一步说明 Workbench 必须能力探测，不能只硬编码 Windows 路径。[路径实现](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/config.rs#L182-L220)、[配置文件 FAQ](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/zh/5-faq/5.1-config-files.md)。

## 2. CC Switch 的用量查询实际语义

官方把该功能分为两类：[Usage Query 手册](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/2-providers/2.5-usage-query.md)。

| 类别 | CC Switch 的行为 | 与当前需求的对应 |
|---|---|---|
| 官方订阅自动查询 | Claude、Codex、Gemini 官方登录，Copilot 和 Codex OAuth 卡片会调用相应官方/OAuth 查询端点；卡片显示使用百分比和重置倒计时。 | 可呈现 5 小时、7 天等窗口（实际窗口由上游和当前模板决定）。官方在 v3.16.2 起把官方订阅模板改为显式可选、默认关闭，并允许设置刷新间隔，原因是查询 IP 与应用请求 IP 不一致可能有风险。[发布说明](https://github.com/farion1231/cc-switch/releases/tag/v3.16.2) |
| 手动启用的内置模板 | Token Plan（Kimi、Zhipu GLM、MiniMax、Volcengine）和第三方余额（含 DeepSeek）必须在供应商卡片中打开 **Enable Usage Query**，选择模板并保存；仅活跃供应商会后台刷新。 | 用户所说的“开启后显示 DeepSeek 余额”与官方说明一致。DeepSeek 是余额查询，不等同于订阅 5h/7d 窗口。 |
| 自定义脚本 | 用户可以提供请求与提取 JavaScript；文档明确支持 `remaining`、`used`、`total`、`planName`、`unit` 等结果字段。 | 这是 CC Switch 自己的 UI 配置能力，不能成为 Workbench 读取该软件内部数据的稳定协议。自定义脚本和它引用的 API Key/Token 都属于敏感配置。 |

官方说明还指出：手动模板的自动刷新间隔为 0–1440 分钟、只在供应商处于“Currently Active”时触发，并且查询本身会消耗少量 API 请求额度。见 [Usage Query 手册：启用及刷新规则](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/2-providers/2.5-usage-query.md#enable-steps)。

从源码实现可再确认两点：启用配置保存在供应商的 `meta.usage_script` 一类内部数据中；查询结果由运行中进程的 `UsageCache`（Rust `RwLock`）持有，而不是一个已发布的、可供外部只读查询的持久化结果表。对于 DeepSeek，内置余额实现会用供应商 key 调用其余额端点并将结果映射为 `remaining`。这些是 CC Switch 内部实现细节，不应用于 Workbench 的跨版本读取契约。[用量脚本服务](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/services/provider/usage.rs)、[进程内缓存](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/services/usage_cache.rs)、[Tauri usage commands](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/commands/usage.rs)、[DeepSeek 余额实现](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/services/balance.rs)。

## 3. 本机 SQLite 中可安全确认的结构边界

本次只读取 SQLite 元数据（表名、列名、`user_version`），没有查询任何记录。v16 中与使用量相关的表如下：

| 表 | 可确认的列（节选） | 适用性与风险 |
|---|---|---|
| `usage_daily_rollups` | `date`、`app_type`、`provider_id`、`model`、`request_count`、`input_tokens`、`output_tokens`、`total_cost_usd` | 是 CC Switch 自己汇总的代理/会话用量，不等价于官方订阅窗口，也不包含可承诺的余额字段。 |
| `proxy_request_logs` | `provider_id`、`app_type`、token、成本、耗时、`session_id`、`created_at`、`data_source` 等 | 是请求日志；数据规模、去重口径和 schema 都由 CC Switch 维护。Workbench 不应复制或把它作为自身会话事实来源。 |
| `providers` | `id`、`app_type`、`name`、`settings_config`、`meta` 等 | `settings_config`/`meta` 可能包含 API Key、Access Token 或自定义脚本；其中的内部 `usage_script` 也是 CC Switch 用量查询的配置来源。**禁止 Workbench 读取、导出、迁移或记录这些值。** |
| `settings` | `key`、`value` | 值可能包含用户设置或敏感信息，禁止通用读取。 |

该 schema 中未发现一个可仅凭表名/列名确认、且独立于供应商配置的“官方额度/余额查询结果”表。即使某一版本把展示缓存藏在 `providers.settings_config`、`meta` 或 JSON 中，也会同时踩到敏感数据边界和非公开 schema 兼容风险，不能采用。

## 4. 可行读取方式的判定

| 方式 | 是否采用 | 原因 |
|---|---|---|
| 读取 CC Switch 的本地 HTTP/IPC API | **否** | 未发现运行时监听端口；`get_usage_summary` 等是 Tauri 内部 IPC，不是第三方 API；官方未发布版本化契约。 |
| 读取 `cc-switch.db` 的 `providers.settings_config` / `settings.value` / JSON 缓存 | **否** | 可能包含凭据、access token 或自定义脚本；字段语义和 schema 未承诺稳定。 |
| 读取 `usage_daily_rollups` / `proxy_request_logs` | **受限可采用** | 用户显式启用、版本/schema allowlist 命中时，可只读聚合最小非敏感用量字段；必须复现有效记录去重，且不复制明细。近期项目归属仅接受精确 `session_id` 映射；不用于订阅额度、余额或 Clash 代理流量。 |
| 由 Workbench 直接调用各厂商官方 API | **可采用** | 凭据在 Workbench 本机凭据库中独立保存；只读取官方端点；能清楚标注来源、刷新时间与失败状态。DeepSeek、Kimi 和阿里云 BSS 的官方连接器已另有调研。 |
| 让用户在 CC Switch UI 中查看，并在 Workbench 显示“由 CC Switch 管理”说明 | **可采用（无自动读取）** | 零耦合、零凭据复制，且不会将 CC Switch 的私有内部实现变成 Workbench 兼容承诺。 |
| 未来读取 CC Switch | **仅可作为显式启用的、版本化 best-effort 适配器** | 前提是 CC Switch 发布稳定只读 API，或维护者明确发布非敏感导出格式及版本契约；否则不要实现。适配器必须版本探测、仅 allowlist 非敏感字段、读取失败即降级为“不可用”，不得扫描 JSON 或猜测字段。 |

## 5. 对 Workbench 的建议

1. **额度/余额边界不变：** 均由 Workbench 的官方连接器读取；CC Switch 不是必要依赖，也不被静默读取。
2. **模型用量边界已确认：** 在用户启用且版本/schema allowlist 命中时，`CcSwitchReadOnlyAdapter` 可作为全局与近期项目模型用量的优先聚合来源；其数据质量必须标注为 CC Switch 已观测/`estimated`。
3. **避免双重计数：** 适配器须按 CC Switch 的有效记录规则聚合，不复制 `proxy_request_logs`；同一范围的原生 JSONL 聚合只作替代来源，不能相加。
4. **项目历史仍需原生来源：** CC Switch 旧日汇总没有会话 ID/项目路径。首次登记项目和不可归属缺口由该项目原生 JSONL 建立/增量回退，Workbench 仅保存日级聚合。
5. **不要重放 CC Switch 查询：** Workbench 不调用其自定义脚本、也不从 provider 配置借用 API Key。需要 DeepSeek 余额时，由用户在 Workbench 自己授权官方 DeepSeek 连接器。

## 6. 与架构的关系

本调研中的本机版本、路径和 schema 是可变事实，不应被硬编码。已确认的产品规则在[架构文档](../ai-coding-workbench-architecture.md#9-用量统计订阅额度与账户余额)及其决策记录中：版本化只读用量适配可用，订阅/余额内部缓存与任何敏感字段不可用；具体实现只在已批准的 Phase 2 内进行。

## 7. 官方来源

- [CC Switch 源码仓库](https://github.com/farion1231/cc-switch)
- [Usage Query：自动查询、手动模板、刷新与脚本返回格式](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/2-providers/2.5-usage-query.md)
- [FAQ：哪些类型自动显示、哪些必须手动开启](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/5-faq/5.2-questions.md#quota--balance)
- [v3.13.0 发布说明：额度与余额展示范围](https://github.com/farion1231/cc-switch/releases/tag/v3.13.0)
- [v3.16.2 发布说明：官方订阅额度模板改为显式可选](https://github.com/farion1231/cc-switch/releases/tag/v3.16.2)
