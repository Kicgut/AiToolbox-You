# CC Switch 本机集成调研（只读）

> 调研日期：2026-08-01
> 范围：本机已安装的 CC Switch 3.18.0；不读取凭据、供应商配置值、日志正文或数据库记录内容。
> 结论：CC Switch 可以作为用户可见的用量/余额**展示工具**，但截至本报告，不应被 Workbench 当作具有稳定本地 API 或稳定 SQLite 结果 schema 的数据源。

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
| 读取 `usage_daily_rollups` / `proxy_request_logs` | **默认否** | 可用于 CC Switch 自己的成本/代理统计，但会与 Workbench 原生会话统计重复，且不解决订阅额度和余额。若将来有单独的“代理流量”只读导入需求，必须另行设计去重、版本白名单和 schema fixture，不能顺带接入。 |
| 由 Workbench 直接调用各厂商官方 API | **可采用** | 凭据在 Workbench 本机凭据库中独立保存；只读取官方端点；能清楚标注来源、刷新时间与失败状态。DeepSeek、Kimi 和阿里云 BSS 的官方连接器已另有调研。 |
| 让用户在 CC Switch UI 中查看，并在 Workbench 显示“由 CC Switch 管理”说明 | **可采用（无自动读取）** | 零耦合、零凭据复制，且不会将 CC Switch 的私有内部实现变成 Workbench 兼容承诺。 |
| 未来读取 CC Switch | **仅可作为显式启用的、版本化 best-effort 适配器** | 前提是 CC Switch 发布稳定只读 API，或维护者明确发布非敏感导出格式及版本契约；否则不要实现。适配器必须版本探测、仅 allowlist 非敏感字段、读取失败即降级为“不可用”，不得扫描 JSON 或猜测字段。 |

## 5. 对 Workbench 的建议

1. **首选逻辑不变：** 额度/余额由 Workbench 的官方连接器读取；CC Switch 不是必要依赖，也不被静默探测后读取。
2. **UI 文案：** 对已安装 CC Switch，可提示“CC Switch 可显示其已配置供应商的额度/余额；Workbench 不读取其凭据或内部缓存”。不要显示为 Workbench 已取得的数值。
3. **避免双重计数：** 不导入 `usage_daily_rollups` 或 `proxy_request_logs` 作为总览 Token 的默认来源；WorkBench 应继续使用原生 Codex/Claude 会话与自身运行审计，或在未来把代理流量作为独立辅助视图。
4. **不要重放 CC Switch 查询：** Workbench 不应调用其自定义脚本、也不应从其 provider 配置借用 API Key。需要 DeepSeek 余额时，由用户在 Workbench 自己授权官方 DeepSeek 连接器。
5. **将来若有稳定接口：** 用 `CcSwitchReadOnlyAdapter` 隔离实现，能力探测需返回 `unsupported / compatible / stale / unavailable`，保存来源、版本、最后成功时间；不兼容时回退到官方连接器或“不可用”。

## 6. 对架构文档的定向更正建议（本报告不修改架构文档）

`docs/ai-coding-workbench-architecture.md` 的“2.3 CC Switch 本机数据”和决策表有两处需要在后续统一修订：

1. **更新实测版本事实：** 本机现在为 CC Switch 3.18.0，`cc-switch.db` 为 `user_version = 16`，不是文中旧的 3.15.0/v10。保留 Windows 路径 `~/.cc-switch/cc-switch.db`，但明确它是探测候选路径，不是 API 契约。
2. **收紧“CC Switch 只读连接器”的定位：** 原先允许 CC Switch 数据库作为 pricing/统计候选来源的表述，应改为“官方连接器优先；CC Switch 内部数据库默认不读，尤其不得访问 `providers.settings_config`、`settings.value` 或任何缓存 JSON。只有 CC Switch 发布稳定只读 API/导出契约后，才以版本化、显式启用的 best-effort 适配器接入。”

## 7. 官方来源

- [CC Switch 源码仓库](https://github.com/farion1231/cc-switch)
- [Usage Query：自动查询、手动模板、刷新与脚本返回格式](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/2-providers/2.5-usage-query.md)
- [FAQ：哪些类型自动显示、哪些必须手动开启](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/5-faq/5.2-questions.md#quota--balance)
- [v3.13.0 发布说明：额度与余额展示范围](https://github.com/farion1231/cc-switch/releases/tag/v3.13.0)
- [v3.16.2 发布说明：官方订阅额度模板改为显式可选](https://github.com/farion1231/cc-switch/releases/tag/v3.16.2)
