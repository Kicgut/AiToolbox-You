# AI 编程工作台架构方案（讨论稿）

> 文档状态：Draft v0.1  
> 更新日期：2026-07-23  
> 当前范围：Codex CLI、Claude Code；为后续接入其他 AI 编程工具保留扩展点  
> 目的：作为后续讨论的唯一方案文档。用户提出新建议后，继续在本文档中修订，确认后再拆分实施任务。

## 1. 结论与核心决策

本项目新增一个独立的“AI 编程工作台”大模块，形成以下完整链路：

```text
会话发现与索引
    ↓
统一会话查看与搜索
    ↓
新建 / 续接 / Fork 会话
    ↓
结构化实时输出与审批
    ↓
多步骤提示词与定时任务
    ↓
用量、性能、稳定性和结果统计
```

当前确定的架构原则：

1. **项目必须完全独立运行。** Cockpit Tools、CC Switch 均为可选数据源，不构成安装依赖。
2. **原生会话文件是历史会话事实来源。** 本项目的 SQLite 只保存可重建索引、规范化事件和本项目产生的运行记录。
3. **第三方目录默认只读。** 不写入 Cockpit Tools 或 CC Switch 的数据库、配置和锁文件。
4. **先统一查看，再允许修改。** 第一阶段只做会话扫描、解析、搜索和展示；跨实例复制属于后续高风险功能。
5. **实时输出优先使用结构化协议。** 不以屏幕抓取、ANSI 终端文本或持续 tail 文件作为主方案。
6. **统计必须标明数据质量。** 每个指标标记为“精确”“估算”或“不可用”，不能把缺失数据当成 0。
7. **前端升级为 Vue 3 + TypeScript + Vite。** 发布时仍可把构建产物随 FastAPI 一起分发，部署机器不需要 Node.js。

## 2. 已完成的技术验证

### 2.1 本机工具能力

本机验证版本：

| 工具 | 本机版本 | 已验证能力 |
|---|---:|---|
| Codex CLI | 0.144.4 | `resume`、`exec --json`、`exec resume --json`、`app-server` |
| Claude Code | 2.1.200 | `--resume`、`--continue`、`--fork-session`、`stream-json` 输入输出 |

验证只执行了帮助命令、文件与数据库结构检查，没有向模型发送提示词，没有消耗 API 或订阅额度。

另外已直接启动本机 `codex app-server`，通过 stdio 成功完成：

```text
initialize → initialized → thread/list(limit=1) → thread/read(includeTurns=false)
```

返回结果确认平台为 Windows，并成功只读取会话元数据；`includeTurns=false` 返回 `turns_count=0`。该验证没有调用 `thread/start` 或 `turn/start`，因此没有发生模型请求。

### 2.2 本机会话数据

抽样扫描结果：

- Codex：`~/.codex/sessions/**/*.jsonl`，另有 `archived_sessions`、`session_index.jsonl`。
- Claude Code：`~/.claude/projects/**/*.jsonl`，另有 `stats-cache.json`、子代理和附件记录。
- 两者的 JSONL 均足以展示用户消息、AI 回复、工具调用、工具结果、命令输出和 token 信息。
- 历史记录中通常没有可靠的账号邮箱或组织 ID，因此历史会话只能在有证据时归属账号。

### 2.3 CC Switch 本机数据

本机已确认 CC Switch 的主数据库为：

```text
~/.cc-switch/cc-switch.db
```

当前本机 **CC Switch 数据库** `PRAGMA user_version = 10`，包含：

- `proxy_request_logs`
- `usage_daily_rollups`
- `session_log_sync`
- `providers`
- `provider_health`
- `model_pricing`

`proxy_request_logs` 已包含以下有价值字段：

```text
provider_id, app_type, model, request_model,
input_tokens, output_tokens,
cache_read_tokens, cache_creation_tokens,
input_cost_usd, output_cost_usd, total_cost_usd,
latency_ms, first_token_ms, duration_ms,
status_code, error_message, session_id,
provider_type, is_streaming, created_at, data_source
```

本机数据源包含：

- `codex_session`
- `session_log`

当前 CC Switch 源码的数据库版本已经高于本机安装版本，说明其 schema 会持续演化。项目不得依赖固定列集合，更不能对 CC Switch 数据库执行迁移或写操作。

本机安装版本为 3.15.0。2026-07-21 官方最新版本为 [3.18.0](https://github.com/farion1231/cc-switch/releases/tag/v3.18.0)，其数据库 schema 为 v16。这里的 v10/v16 都是 CC Switch 自身数据库版本，不是本项目数据库版本；当前不存在“本项目 schema v10 → v16”的迁移。

本项目只读探测 CC Switch 版本和 schema，不负责升级、降级、重装、修复或调用其 updater。若版本差异影响兼容性，先向用户报告并建议用户通过 CC Switch 自身界面执行完整软件更新；用户更新完成后再重新探测。本规则同样适用于 Cockpit Tools、Codex CLI、Claude Code 和其他外部软件。连接器仍必须支持未安装、旧版本、当前版本和未知未来版本。

因此本架构中的“升级”是升级本项目自己的 connector、parser、fixture 和归一化模型，使其兼容 CC Switch v10/v16；不是迁移 CC Switch 数据库。现有代理流量监控数据库（`features/proxy-traffic-monitor/data/traffic.db`，2026-07-24 起随仓库结构迁移调整路径，历史上曾位于 `proxy-traffic-monitor/data/traffic.db`）经只读检查为 `PRAGMA user_version = 0`，新的 Workbench 自有数据库尚未建立，将从 Phase 1 开始使用独立的 schema version。

### 2.4 Cockpit Tools 本机状态

本机 Cockpit Tools 与 CC Switch 均处于运行状态。Cockpit Tools 自身数据目录为：

```text
~/.antigravity_cockpit
```

其中包含账号、实例、配置、锁、备份和日志。该目录可能含凭据或账号快照，本项目默认不得读取无关文件，更不得写入。

## 3. Codex App Server 是什么

Codex App Server 是 Codex CLI 内置的本地集成协议进程，不是新的云服务，也不是 OpenAI API 的替代品。它使用当前 Codex CLI 的认证、配置、沙箱和本地会话，向富客户端提供：

- 会话列举、读取、新建、续接和 Fork。
- Turn 启动、中断和状态。
- 消息增量、工具调用、文件变化等实时事件。
- 命令与文件修改审批。
- 模型、技能、MCP 等元数据。

默认启动方式：

```powershell
codex app-server
```

默认通信方式为 stdin/stdout 上逐行 JSON-RPC/JSONL。官方文档说明客户端需要先发送 `initialize` 和 `initialized`，然后调用 `thread/start`、`thread/resume`、`turn/start` 等方法。

### 3.1 是否需要额外下载

不需要单独下载 App Server。只要所安装的 Codex CLI 包含 `codex app-server` 命令即可。本机已经验证存在。

部署时执行能力探测：

```text
1. 查找 codex 可执行文件
2. 执行 codex --version
3. 执行 codex app-server --help
4. 记录可用能力和 CLI 版本
```

旧版本没有 App Server 时，Codex 适配器自动降级为：

```text
codex exec --json
codex exec resume <SESSION_ID> --json
原生 JSONL 会话解析
```

### 3.2 使用边界

官方 CLI 参考目前仍将 `codex app-server` 命令标为 Experimental，但 App Server 文档提供了稳定 API 子集，并要求未明确需要时不要启用 `experimentalApi`。

因此采用以下策略：

- 会话浏览、交互式续接和审批：优先 App Server 稳定方法。
- 定时批处理：通过 `CodexAdapter` 封装，首版可使用稳定的 `codex exec --json`；后续可切换 Codex SDK。
- 不把 App Server 的实验性 WebSocket 暴露给浏览器。
- 后端持有 stdio 进程，并将事件转换为项目自己的稳定事件协议。
- 所有 App Server 请求经过版本与能力协商，未知事件保留为 raw event，不让前端崩溃。

官方资料：

- <https://developers.openai.com/codex/app-server>
- <https://developers.openai.com/codex/cli/reference>
- <https://developers.openai.com/codex/noninteractive>

## 4. 总体技术架构

采用本地模块化单体：

```text
┌──────────────── Vue 3 SPA ────────────────┐
│ 总览 │ 统计 │ 会话 │ 自动任务 │ 运行中心 │ 设置 │
└───────────────────┬───────────────────────┘
                    │ REST + WebSocket
┌───────────────────▼───────────────────────┐
│                FastAPI API                │
├───────────┬───────────┬──────────┬────────┤
│ Session   │ Execution │Scheduler │ Stats  │
│ Service   │ Supervisor│ Worker   │Service │
├───────────┴───────────┴──────────┴────────┤
│ Adapter Registry + Normalized Event Bus   │
├───────────────┬───────────────────────────┤
│ CodexAdapter  │ ClaudeAdapter             │
├───────────────┼───────────────────────────┤
│ App Server /  │ stream-json / native      │
│ exec JSONL    │ session logs              │
└───────────────┴───────────────────────────┘
          │                  │
          ├── Native session files（默认只读索引）
          ├── Workbench SQLite（唯一可写主库）
          ├── CC Switch SQLite（可选、只读）
          └── Cockpit config（可选、仅路径发现）
```

### 4.1 自有数据目录

使用 `platformdirs` 生成独立目录，不复用任何第三方目录。例如 Windows：

```text
%LOCALAPPDATA%\StatisticsToolbox\ai-workbench\
├── workbench.db
├── logs\
├── run-artifacts\
├── backups\
└── locks\
```

禁止把本项目数据库放进：

- `~/.codex`
- `~/.claude`
- `~/.cc-switch`
- `~/.antigravity_cockpit`

## 5. 与 Cockpit Tools 共存且不冲突

### 5.1 三种运行环境

| 环境 | 行为 |
|---|---|
| 未安装 Cockpit Tools | 自动发现默认 Codex/Claude 目录，也允许手动添加实例目录 |
| 已安装但未启用集成 | 与未安装完全相同，不读取 Cockpit 配置 |
| 已安装且用户启用集成 | 只读读取允许列出的实例路径，不读取凭据，不调用 Cockpit 进程 |

本项目不能通过 Cockpit Tools 的存在与否决定核心功能是否可用。

### 5.2 目录和锁隔离

- 本项目使用自己的数据库、备份目录、临时文件前缀和锁文件。
- 不复用 Cockpit 的 `.cockpit-*` 临时文件名、垃圾箱或备份目录。
- 不监听、不占用 Cockpit 内部服务端口。
- 不修改 Cockpit 的 `codex_instances.json`、账号文件和锁文件。
- 不注入 Cockpit 专用 header、provider 或认证投影。

### 5.3 原生会话目录的并发规则

会话扫描是只读操作，可以与 Cockpit 和 CLI 同时运行，但必须：

- 以共享读方式打开文件。
- 容忍最后一行仍在写入而 JSON 不完整。
- 保存已解析 byte offset，只在换行完成后提交新事件。
- 读取前后比较文件长度和 mtime；变化时重新验证尾部。
- 对暂时被占用的文件指数退避，不将其标记为损坏。

第一阶段不修改原生会话文件，因此不会与 Cockpit 的会话同步功能产生写冲突。

### 5.4 后续跨实例复制的安全闸门

跨账号/实例复制在后续阶段才启用，并满足：

1. 用户显式选择源副本和目标实例。
2. 显示目标供应商会收到原始会话内容的隐私提醒。
3. 检测 Codex/Claude、Cockpit Tools 是否正在对相关实例执行写操作。
4. 对源、目标计算内容哈希和 mtime 前置条件。
5. 创建本项目自己的可恢复备份和操作日志。
6. 临时文件写完、fsync 后原子替换。
7. 替换前再次检查哈希，发现变化立即终止，不覆盖。
8. 成功后重新索引并验证目标 CLI 能读取。

检测到 Cockpit 正在运行时，不必禁止所有功能；只阻止涉及共享目录写入的迁移操作。即使 Cockpit 未运行，也必须执行哈希前置条件，因为其他 CLI 仍可能写入。

## 6. 更完整的统一会话模型

### 6.1 不把“Session ID 相同”等同于“内容相同”

Cockpit 的同步会使同一个 Codex Session ID 出现在多个实例中。复制后各副本还可能分别继续，从而发生分叉。因此统一模型分为两层：

```text
ConversationFamily（逻辑会话族）
    ├── SessionCopy A：Codex / profile-1 / rollout-A
    ├── SessionCopy B：Codex / profile-2 / rollout-B
    └── SessionCopy C：迁移后发生分叉
```

物理副本唯一键：

```text
(tool, profile_root, native_session_id, transcript_path)
```

逻辑会话族不是简单按 Session ID 强制合并，而是结合：

- 工具类型。
- 原生 Session ID。
- 初始事件指纹。
- 共同事件前缀。
- 显式 fork/clone 关系。

当同 ID 内容不一致时，状态显示：

- `in_sync`：内容一致。
- `ahead`：一个副本是另一个的严格后继。
- `diverged`：双方都出现不同的新事件。
- `unknown`：无法安全判断。

UI 不静默拼接分叉内容。用户需要选择查看某个副本、查看差异或显式创建新 Fork。

### 6.2 账号归属可信度

账号归属字段：

```text
account_ref
account_source     # execution / isolated_profile / external_registry / inferred / unknown
account_confidence # exact / likely / unknown
```

规则：

- 由本项目启动的会话：记录启动时实际 profile，标为 `exact`。
- 位于用户明确登记的隔离配置目录：标为 `likely` 或 `exact`，取决于是否有非敏感账号标识。
- 只从历史 JSONL 推断：不显示具体账号，标为 `unknown`。
- 不读取或保存第三方明文 token 来提高归属率。

### 6.3 项目归一化

不同工具对项目路径的编码不同，统一保存：

- 原始 cwd。
- 规范化绝对路径。
- 大小写归一后的 Windows 路径键。
- Git repository root。
- remote URL 的脱敏形式。
- branch/worktree 信息。
- 路径是否仍存在。

同一仓库的多个 worktree 保持独立工作目录，同时归属于同一个 Repository。

“大小写归一后的 Windows 路径键”是首个正式版本的 Windows 规范，不是跨平台通用路径规则。未来正式支持 Linux 时，必须单独定义并验证大小写敏感、符号链接和文件身份语义，不得直接套用 Windows 路径归一化行为。

### 6.4 会话类型和关系

统一支持：

- 主会话。
- Fork 会话。
- Resume 续接。
- 子代理/子任务会话。
- 导入副本。
- 归档会话。
- 已丢失或移动 transcript 的孤立索引。

通过 `session_relations` 保存：

```text
parent, forked_from, resumed_from, cloned_to, subagent_of, imported_from
```

### 6.5 建议数据表

```text
tool_profiles
accounts
repositories
projects
conversation_families
session_copies
session_relations
turns
events
usage_records
source_checkpoints
automations
automation_steps
runs
run_steps
approval_requests
external_connectors
```

关键字段：

#### `tool_profiles`

```text
id, tool, display_name, config_root, session_root,
provider, account_ref, discovery_source,
capabilities_json, enabled, last_probe_at
```

#### `session_copies`

```text
id, family_id, tool, native_session_id, profile_id,
project_id, transcript_path, transcript_kind,
title, model, provider, kind,
created_at, updated_at, archived_at,
content_hash, head_event_hash, parse_version,
account_source, account_confidence,
index_status, divergence_status
```

#### `events`

```text
id, session_copy_id, turn_id, sequence_no,
event_type, role, timestamp,
text_content, structured_json, raw_json,
source_offset, content_hash, redaction_state
```

原始事件可选保留。默认只保留解析所需字段和文件 offset；用户开启“本地全文索引”后再写入全文及 FTS5。

## 7. 会话发现、索引与解析

### 7.1 Profile 发现顺序

本节的 Profile 指 Workbench 层的 `tool_profiles` 抽象（配置根目录 + 会话根目录组合），不是 Codex 自己的原生 `--profile` 配置切换机制——两者粒度不同，且 Claude 没有对应的原生 profile 机制，见 `CONTEXT.md` Profile 词条。

1. 用户手动登记的实例目录。
2. 默认环境变量：`CODEX_HOME`、`CLAUDE_CONFIG_DIR`。
3. 默认用户目录：`~/.codex`、`~/.claude`。
4. 本项目曾经启动过的 profile。
5. 用户明确启用后，从 Cockpit 配置中只读发现额外路径。

发现只是候选；每个目录必须通过工具特征文件验证，禁止把任意用户目录递归当作会话目录。

### 7.2 增量索引

每个 transcript 保存：

```text
path, file_identity, size, mtime, parsed_offset,
last_complete_line_offset, prefix_hash, tail_hash, parser_version
```

工作方式：

- 当前实现使用周期 polling reconcile 检测并索引变化，尚未接入操作系统原生文件系统 watcher。
- 文件系统 watcher 是后续可选的低延迟增强；引入后仍以周期 reconcile 修复漏报、网络盘或系统休眠造成的事件丢失。
- 首个正式版本只要求在 Windows 验证索引行为；Linux watcher 或 inotify 适配不在当前兼容性承诺和验收范围内。
- append-only 文件只解析新增完整行。
- 文件缩短、替换或哈希不匹配时重新解析。
- parser 升级时按版本选择性重建。
- 单个损坏事件降级为 `raw_unknown`，不丢弃整个会话。

### 7.3 解析器输出

Codex 和 Claude 解析器统一产生：

- `user.message`
- `assistant.message`
- `reasoning.summary`
- `tool.started`
- `tool.completed`
- `command.output`
- `file.changed`
- `usage.snapshot`
- `error`
- `unknown`

内部 schema 随 CLI 版本演化，解析器必须 fixture 化测试，并按 `cli_version + event shape` 选择兼容分支。

## 8. 会话内容前端设计

### 8.1 页面结构

桌面端采用三栏工作区，而不是多层卡片：

```text
┌──────────────┬──────────────────────────┬──────────────┐
│ 会话列表/筛选 │ 对话时间线                │ 会话检查器    │
│              │                          │ 元数据        │
│ 工具         │ User                     │ 用量          │
│ 账号         │ Assistant                │ 文件          │
│ 项目         │ Tool / Diff / Output     │ 分支/副本     │
│ 状态         │                          │ 原始来源      │
│ 搜索         │ 固定输入栏                │              │
└──────────────┴──────────────────────────┴──────────────┘
```

- 左栏支持按工具、账号可信度、项目、模型、时间、归档、分叉状态筛选。
- 中栏使用虚拟滚动，按 Turn 懒加载。
- 右栏是可折叠检查器，不使用阻断式 modal。
- 窄屏变为“列表路由 → 会话路由 → 检查器抽屉”。

### 8.2 消息展示

- 用户消息：保留文本、附件和发送时间。
- AI 消息：Markdown、代码高亮、复制、锚点链接。
- Reasoning：只展示工具实际提供且允许展示的摘要，默认折叠。
- Tool：显示工具名、状态、耗时、输入摘要和结果摘要。
- Command：stdout/stderr 分流、长输出折叠、ANSI 可选解析。
- Diff：文件级折叠、行内/并排切换，大文件虚拟化。
- Unknown：显示“当前版本暂不识别”，允许展开原始 JSON。

### 8.3 状态和空页面

必须区分：

- 首次未扫描：引导添加目录或开始扫描。
- 扫描中：骨架列表及进度，不用全页 spinner。
- 没有会话：解释会话会从哪里出现，并提供“新建会话”。
- 文件不可访问：显示路径、原因和重试。
- 会话正在被其他进程写入：显示“实时更新中”，而不是报错。
- 解析器不兼容：保留 raw view，并提示升级适配器。

## 9. 新建、续接、Fork 与多步骤提示词

### 9.1 工具适配器接口

Phase 3 已定义以下受限映射：对于由 Workbench 新建或 Fork 的 Codex App Server run，`thread/start` / `thread/fork` 返回的 `threadId` 同时记录为该 run 的 `native_thread_id` 与 `native_session_id`；它只说明本次受监管运行拥有的 native 身份，不会反向修改或猜测既有 JSONL transcript 的 ID。Resume/Fork 的输入必须来自已索引 `session_copy_id` 的 `native_session_id`，禁止使用“最近会话”推断。Claude 的 native session ID 则只从其 stream-json init/result 记录提取。

Phase 3 的产品 run 固定为单回合：一个 Workbench Run 只有一个 Step，对应一次原生 Turn；多 Step 编排属于 Phase 4。所有状态、事件和 cursor 在同一 SQLite 事务提交后才广播。部署仅支持一个 FastAPI worker 和一个 Runtime Coordinator；Coordinator 统一拥有进程树、timeout、writer lease、审批 waiter 与进程内 WebSocket fan-out。连接过程采用先订阅、后 cursor replay、按 `(run_id, sequence_no)` 去重的顺序，断线重连以 SQLite 为事实源。

原生 command/file approval 是一次性双向桥：server request 先持久化为 `pending`，浏览器决定后进入 `responding`，只有 JSON-RPC response 实际写入同一 App Server stdin 才成为 accepted/declined/cancelled；写入失败标记 `delivery_failed`。浏览器断开不会改变 pending 状态，服务重启时失联 run 统一进入 `interrupted`。

```text
probe()
discover_profiles()
list_sessions()
read_session()
start_session(options)
resume_session(session, options)
fork_session(session, options)
start_turn(prompt, options)
cancel_turn()
respond_approval()
stream_events()
```

前端和调度器只能调用统一适配器，不能拼接 shell 命令字符串。后端使用 argv 数组启动进程，prompt 通过 stdin 或协议字段传递。

### 9.2 Codex

优先级：

```text
App Server stable methods
    ↓ 不可用
codex exec / exec resume --json
    ↓ 仅查看
native session parser
```

### 9.3 Claude Code

执行方式：

```text
claude -p --output-format stream-json --include-partial-messages
claude -p --resume <SESSION_ID> ...
```

多轮常驻执行可使用 `--input-format stream-json`；首版也可以每个 Step 启动一个明确的 resume 进程，以换取更简单的故障隔离。

### 9.4 多步骤语义

“多句提示词，每句独立”定义为有序 Step，而不是一次拼接成大 prompt：

```text
Automation Run
  ├── Step 1 → 原生 Turn 1
  ├── Step 2 → 原生 Turn 2
  └── Step 3 → 原生 Turn 3
```

每个 Step 独立保存：

- prompt。
- 是否启用。
- 前置延迟。
- timeout。
- retry。
- 失败后停止/继续。
- 模型、权限和预算覆盖。
- 运行状态、实际输出和 usage。

只有前一个 Turn 明确结束后才提交下一句。同一物理 Session 同时只能存在一个 writer lease。

## 10. 实时输出与进程监管

### 10.1 统一事件协议

```text
run.started
run.status_changed
turn.started
message.delta
message.completed
reasoning.summary
tool.started
tool.output
tool.completed
file.changed
approval.required
approval.resolved
usage.updated
diagnostic.stderr
run.completed
run.failed
run.cancelled
```

每个事件包含：

```text
event_id, run_id, step_id, session_id,
sequence_no, timestamp, type, payload,
source_tool, source_event_type
```

### 10.2 数据路径

```text
CLI stdout JSONL / App Server stdio
              ↓ 增量逐行解析
Normalized Event Bus
       ├── SQLite 持久化
       ├── WebSocket 推送
       └── 指标聚合

CLI stderr → diagnostic.stderr，绝不和 stdout JSON 混合解析
```

浏览器断线重连时携带最后收到的 `sequence_no`，后端先补发缺失事件，再继续实时流。

### 10.3 Windows 进程生命周期

本节是首个正式版本的规范实现，不是等待 Linux 等价方案补齐的临时平台分支。首版的进程监管、取消和子进程树清理仅以 Windows 为正式支持与验收目标；实现边界可为未来平台适配保留抽象，但不因此形成 Linux 兼容性承诺。

- 使用独立 process group。
- 使用 Job Object 管理子进程树，避免取消后遗留 shell、MCP 或工具进程。
- 支持温和中断、超时后强制终止两阶段策略。
- 限制单运行内存事件缓冲，完整记录落盘，WebSocket 使用背压。
- 应用重启后，将失联的 `running` 任务恢复为 `interrupted`，然后按策略重试或等待用户确认。

### 10.4 原始终端模式

PTY/ConPTY + xterm.js 只作为高级“原始终端”模式，用于无法结构化表达的交互式 TUI。自动任务、统计和默认会话界面不依赖 PTY。

## 11. 定时任务与恢复

### 11.1 调度状态机

```text
scheduled → queued → claimed → starting → running
                                         ├── waiting_approval
                                         ├── succeeded
                                         ├── failed
                                         ├── cancelled
                                         └── interrupted

scheduled → missed
```

### 11.2 可靠性设计

- SQLite 是调度事实来源，内存 scheduler 只负责唤醒。
- Worker 使用带过期时间的 lease 领取任务。
- 幂等键：`(automation_id, scheduled_at, step_no, attempt)`。
- 支持一次性、Cron、时区和夏令时。
- 休眠/停机错过任务时提供：跳过、立即补跑、等待确认。
- 支持任务级和工具/profile 级并发上限。
- 支持最大运行时间、最大预算、最大重试和指数退避。
- 默认权限为安全模板；不得继承 `codex-auto.cmd` 中的危险绕过模式。

### 11.3 审批

- 有前端用户在线：通过运行中心处理 `approval.required`。
- 无人值守：只允许预先保存的权限模板自动处理有限操作。
- 超出模板：保持 `waiting_approval`，到期失败或暂停。
- 每次批准保存批准人、时间、请求摘要和决定。

### 11.4 应用未运行和电脑休眠

首版要求 FastAPI 后台服务运行。后续增加：

- 开机自启/托盘。
- Windows 服务模式。
- 可选 Windows Task Scheduler 桥接，用于唤醒和启动工作台 worker。

上述生命周期方案以 Windows 首版为范围，不同期承诺 systemd、Linux daemon 或其他平台等价实现；未来正式支持 Linux 时另行设计并纳入对应测试矩阵。

## 12. 统计架构与 CC Switch 可选集成

### 12.1 数据源优先级

统计不是简单“有 CC Switch 就全部读取、没有就少展示”，而是统一指标模型、多来源补充：

| 优先级 | 数据源 | 作用 |
|---:|---|---|
| 1 | 本项目监管的运行事件 | 精确运行时间、TTFT、退出状态、审批和重试 |
| 2 | CC Switch 代理请求日志（可选） | 外部运行的 HTTP 状态、供应商、TTFT、延迟和已记录成本 |
| 3 | Codex/Claude 原生会话日志 | 所有部署都可获得的 token、会话、消息和工具调用基线 |
| 4 | 价格表推算 | API 等效估算成本，不冒充实际账单 |

本项目始终实现自己的原生会话解析，因此不会因为服务器未安装 CC Switch 而失去基础统计。

### 12.2 CC Switch 只读连接器

连接器流程：

```text
detect ~/.cc-switch/cc-switch.db
    ↓
SQLite URI mode=ro + 短事务 + busy_timeout
    ↓
PRAGMA user_version + sqlite_master + table_info
    ↓
按实际存在的列构建兼容查询
    ↓
映射到 Workbench UsageRecord
```

约束：

- 绝不执行 DDL、PRAGMA journal 修改、migration、VACUUM 或写入。
- 不读取 providers 中的凭据型配置 JSON。
- 只读取统计所需白名单列。
- 数据库忙、损坏或 schema 不兼容时立即关闭连接器，回退自有解析。
- 数据库路径可配置，自动发现只是默认值。
- UI 显示连接状态、schema version、最后成功同步时间和错误原因。

### 12.3 避免重复统计

CC Switch 会把原生 session log 导入自己的 `proxy_request_logs`。如果本项目同时解析原生日志，再把这些行全部导入，会造成双重计数。

规则：

- `data_source = session_log / codex_session / gemini_session`：默认不作为额外 usage 导入，只用于交叉校验或解析器回退。
- `data_source = proxy`：作为代理观测数据导入，可补充 TTFT、HTTP 状态、provider 和实际记录成本。
- 无 `data_source` 的旧 schema：按 CC Switch 历史语义视为 `proxy`，但必须标记来源版本。
- 以 `request_id` 为第一去重键；缺失时使用工具、session、时间窗口、模型和 token 指纹。
- 一个逻辑请求可同时拥有 `session_observation` 和 `proxy_observation`，聚合时只计一次 token，但允许代理观测补充性能字段。

### 12.4 有无 CC Switch 时的展示一致性

统计页面保持相同的信息架构，不因外部工具缺失而整页改变。字段根据数据质量显示：

| 指标 | 无 CC Switch 的历史会话 | 本项目监管的新运行 | 有 CC Switch 代理数据 |
|---|---|---|---|
| 输入/输出 token | 精确或解析可得 | 精确 | 精确 |
| cache read/create | 工具有记录时精确 | 精确或工具可得 | 精确 |
| 会话/Turn/工具调用 | 精确 | 精确 | 精确 |
| 估算成本 | 可计算 | 可计算 | 可计算 |
| 实际记录成本 | 通常不可用 | API 返回时可用 | CC Switch 已记录时可用 |
| 总耗时 | 文件时间推断/不可用 | 精确 | 精确 |
| 首字延迟 TTFT | 不可用 | 精确 | 精确 |
| HTTP 状态码 | 不可用 | 错误事件可得时部分可用 | 精确 |
| provider/account | 推断或未知 | 启动配置精确 | provider 通常精确 |
| 退出码/取消/审批 | 不可用 | 精确 | CC Switch 不负责此项 |

UI 约定：

- `精确`：实心数据质量标记。
- `估算`：显示 `≈`，悬停解释依据。
- `不可用`：显示 `—`，不显示 `0`。
- 图表维度缺失时保留布局，并显示“该时间段没有此类观测来源”。

### 12.5 核心统计指标

#### 用量与成本

- input/output/cache read/cache create token。
- 会话数、Turn 数、prompt 数、活跃天数。
- 工具、账号、profile、项目、模型、provider 分组。
- API 实际记录成本与 API 等效估算成本分开。
- 订阅登录模式不得把估算成本称为账单。

#### 性能

- 端到端耗时。
- TTFT。
- 输出 token/s。
- 工具调用耗时。
- scheduler 排队时间、启动时间偏差。

#### 稳定性

- completed/failed/cancelled/interrupted。
- CLI exit code。
- 401/403/429/5xx。
- resume 失败。
- 重试率。
- approval 等待、拒绝和超时。
- scheduled/missed/on-time。

#### 工作模式

- 平均 Turn/session。
- 每项目会话量。
- 活跃时段和连续工作时长。
- 工具调用类别。
- 命令数量、文件修改数、diff 行数。
- fork/resume 次数和会话寿命。

#### 结果代理指标

- test/build/lint 命令退出状态。
- commit/PR 仅在实际观察到时统计。
- 用户重试、撤销或立即追加修复提示词。

进程退出为 0、AI 声称完成，均不能单独定义为“任务成功”。

## 13. 前端工程与信息架构

### 13.1 工程升级

当前浏览器直引 Vue ESM 适合单页流量面板，但新增模块需要路由、复杂状态、虚拟列表、实时事件恢复和可测试组件。

建议：

- Vue 3 + TypeScript + Vite。
- Vue Router。
- Pinia 管理 profile、过滤器、运行状态和连接状态。
- REST 查询与 WebSocket 事件分层。
- Markdown、代码高亮、diff、虚拟列表组件。
- 构建产物输出到 FastAPI 静态目录。

开发环境需要 Node.js；发布包和部署服务器只运行已经构建好的静态资源，继续保持 Python 一键启动体验。

### 13.2 主导航与信息架构落地

原方案导航结构：

```text
总览
用量统计
会话
自动任务
运行中心
代理流量（现有功能）
设置
```

Phase 1 首次实现时未落地这一结构：根路径 `/` 保留了旧代理流量页面，新会话中心挂在 `/workbench`，两者用普通超链接连接，不受 Vue Router 管理。2026-07-23 架构复审确认这是与本节原意不符的实现偏差，并确认以下落地方式：

- **workbench SPA 是前端主壳**，浏览器根路径 `/` 直接进入 workbench，不再是代理流量页面。
- **“总览”是 workbench 默认首页路由**，首版只做功能入口卡片：跳转到会话中心、代理流量，并为用量统计、自动任务、运行中心、设置预留位置。首版总览不嵌入统计类小部件；是否需要小部件，等对应功能页上线后再评估。
- **代理流量监控作为“现有功能”迁移为可跳转子页面**，不再占用根路径。其现状实现（浏览器直引 Vue ESM、独立静态资源）保持不变，本次只调整可访问路径和入口方式；是否把它重写为 workbench SPA 内的 Vue Router 路由，留到 §13.1 的前端结构重构一起评估，不在本次主页改造范围内。

### 13.3 统计页面

- 顶部常驻筛选：日期、工具、账号/profile、项目、模型、provider、数据来源。
- KPI 条：token、Turn、估算/实际成本、缓存命中、完成率。
- 趋势区：token/成本/请求，可切换而不堆叠过多图表。
- Breakdown 表：项目、模型、provider、账号。
- 可靠性区：错误、重试、错过任务、审批等待。
- 每张图表可展开“数据来源与质量”。

### 13.4 自动任务页面

- 列表与日历切换。
- 行内编辑任务状态和下一次运行时间。
- 任务详情采用页面/侧栏，不把复杂编辑塞进 modal。
- Step 编辑器支持拖动排序、逐步启用、单步测试和 dry-run 命令预览。

### 13.5 运行中心

- 当前运行、等待审批、最近完成三组。
- 结构化流、原始 stdout、stderr 三种视图。
- 支持暂停后续 Step、取消进程、批准/拒绝请求。
- 浏览器刷新后可恢复运行画面。

### 13.6 视觉和交互原则

- 延续现有工具型产品的深浅主题和紧凑信息密度。
- 使用统一语义状态色，不以工具品牌色替代成功/警告/错误。
- 避免层层嵌套卡片；会话和运行中心使用分栏、工具栏和表格。
- 所有控件覆盖 default、hover、focus、active、disabled、loading、error。
- 加载使用骨架，空状态解释下一步。
- 动效只表达状态变化，支持 `prefers-reduced-motion`。
- 正文和控件满足 WCAG AA 对比度，键盘可完成筛选、选会话、发送和审批。

### 13.7 已识别技术债与后续优化方向（2026-07-23 架构复审）

Phase 1 待验收阶段的架构复审发现以下技术债。除主页改造涉及的路由调整外，以下三项列为独立技术债，不随主页改造（P1-12）自动实施：

1. **前端工程结构落后于设想**（时间点已确认）：当前 `frontend/src/main.ts` 是单文件、模板字符串内嵌的实现，没有 `.vue` SFC，没有按 `views/components/stores/router` 拆分，与 §13.1 设想的可测试组件结构不符。2026-07-23 确认：P1-12 验收后单独设立 `plans/ai-coding-workbench/01-read-only-session-center.md` P1-13 前端基础整理门禁处理，完成后才批准 Phase 2，见 §19 决策记录。
2. **样式系统未统一**：旧代理流量页 `app/static/style.css` 与新 workbench `frontend/src/styles.css` 是两套独立样式，§13.6 的语义状态色和控件状态覆盖目前只在新页面部分体现。两者共存于同一入口结构下后，视觉不一致会更明显，建议规划一次最小 design token 统一（配色、间距）。
3. **会话列表“虚拟滚动”是简化实现**：实际是固定窗口裁剪（当前渲染 70 行），不感知容器高度变化，不是标准虚拟滚动。建议在正式验收前用接近测试矩阵目标（1,000 会话）的数据量实测一次滚动体验，并在 Phase 1 的已知限制中注明，而不是按标准虚拟列表描述。
4. **构建产物一致性未校验**：`app/static/workbench/assets/*` 是构建后手动提交的 hash 命名文件，没有自动校验和 `src` 是否同步。建议后续验证流程加入一次“构建后 diff 检查”，避免只改 `src` 忘记重新构建导致产物静默过期。

## 14. API 草案

以下路径是设计草案，与 Phase 1 已实现的路径前缀（`/api/ai-workbench/*`，见 `plans/ai-coding-workbench/01-read-only-session-center.md` 执行证据）不同，尚未回填统一；Phase 2 起新增 API 时以本节草案为设计参照，实现时再核对实际前缀。

```text
GET    /api/ai-tools/capabilities
GET    /api/ai-tools/profiles
POST   /api/ai-tools/profiles/discover

GET    /api/sessions
GET    /api/sessions/{copy_id}
GET    /api/sessions/{copy_id}/turns
GET    /api/sessions/{copy_id}/copies
GET    /api/sessions/{copy_id}/diff/{other_copy_id}
POST   /api/sessions/{copy_id}/resume
POST   /api/sessions/{copy_id}/fork
POST   /api/sessions/new

GET    /api/stats/overview
GET    /api/stats/timeseries
GET    /api/stats/breakdown
GET    /api/stats/data-quality

GET    /api/automations
POST   /api/automations
PUT    /api/automations/{id}
POST   /api/automations/{id}/run
POST   /api/automations/{id}/pause

GET    /api/runs
GET    /api/runs/{id}
POST   /api/runs/{id}/cancel
POST   /api/approvals/{id}/respond
WS     /ws/runs
```

列表接口统一使用 cursor pagination；会话全文搜索和事件查询不返回无限数组。

## 15. 安全与隐私

- 默认只监听 `127.0.0.1`；不在应用内建设认证系统、不作为网络远程服务部署。
- 用户需要远程查看时，自行通过 SSH 本地端口转发连接到运行工作台的机器；认证和传输加密完全由 SSH 承担，本项目不重新实现登录、TLS 或会话管理。
- SSH 隧道连入后视为实例所有者本人，拥有该实例当时开放的全部能力（不是天然只读）；Phase 3–5 上线后，运行、审批、自动任务和迁移等高风险操作同样可以通过隧道执行，不得因为经过 SSH 而降低确认、预算或回滚要求。
- 项目不支持多人共享同一个 workbench 实例；`account_ref` 等字段指 Codex/Claude 自身的账号归属，不构成本项目的用户认证或多租户能力。
- 若未来确实需要真正的"远程只读"模式或多用户隔离，需作为独立产品定位决策单独提出并批准，不得在现有 Phase 中顺带实现。
- 不把 API Key、OAuth token、Cookie、完整环境变量写入日志或数据库。
- transcript 全文索引默认本地，可关闭并支持清空重建。
- prompt 和命令输出导出前执行密钥模式扫描。
- 所有跨账号复制显示数据外发目标。
- 定时任务保存权限模板，不保存 shell 拼接字符串。
- 危险权限只能由用户显式开启，并在运行中心持续显示。
- 原始第三方文件的删除、归档和覆盖不进入首版。

## 16. 实施阶段与验收

### Phase 0：技术 Spike

- Codex App Server 无费用 `initialize`、`thread/list`、`thread/read(includeTurns=false)` 已验证。
- Codex/Claude JSONL mock/fixture 流解析已建立最小 golden event 测试。
- 脱敏 fixture 覆盖 user、assistant、tool、file.changed、usage、error、unknown 和 invalid JSON tail。
- CC Switch v10、本机缺失/损坏数据库和当前源码 schema 能力清单已建立只读兼容测试。
- fake CLI process supervisor 覆盖 argv、stdin、stdout、stderr、timeout 和有限输出缓冲。

验收：不发送真实模型请求，也能完成能力探测、历史索引和模拟实时流。

### Phase 1：只读会话中心

- Profile 发现。
- Codex/Claude 增量索引。
- 会话三栏界面。
- 搜索、筛选、raw view。
- 副本和分叉检测。

验收：Cockpit Tools 开启、关闭、未安装三种环境下行为一致，无第三方目录写入。

### Phase 2：统计中心

- 原生会话基线统计。
- 数据质量标记。
- CC Switch 只读连接器。
- 去重与来源合并。

验收：删除或禁用 CC Switch 连接器后，基础 token/会话统计保持一致，丰富指标正确降级。

### Phase 3：手动运行

- 新建、resume、fork。
- 结构化实时输出。
- 审批、取消、断线补发。
- 受控真实回合测试：两种工具各新建一次、续接一次。

### Phase 4：自动任务

- 多 Step。
- 一次性/Cron。
- lease、幂等、重试、misfire。
- 开机自启和恢复。

### Phase 5：高级迁移

- 跨 profile 复制。
- 备份、哈希前置条件和回滚。
- 与 Cockpit 并存写入测试。
- 明确的隐私和 provider 兼容性提示。

## 17. 参考实现与引用规则

### 17.1 Cockpit Tools

项目：<https://github.com/jlcodes99/cockpit-tools>

重点参考：

- `src-tauri/src/modules/codex_session_manager.rs`
- `src-tauri/src/modules/codex_thread_sync.rs`
- `src-tauri/src/modules/codex_official_app_server.rs`

许可：CC BY-NC-SA 4.0。当前项目不计划商业化，可以在遵守署名、相同方式共享等条件下复用，但实施前仍需确认项目整体许可证与该许可证兼容。

如果复制或实质改写代码，每个文件顶部注明：

```text
Derived from jlcodes99/cockpit-tools
Upstream file: <URL>
Upstream commit: <commit SHA>
License: CC BY-NC-SA 4.0
Changes: <本项目修改摘要>
```

并维护 `THIRD_PARTY_NOTICES.md`。本讨论稿目前只引用设计与源码位置，没有复制源码。

### 17.2 CC Switch

项目：<https://github.com/farion1231/cc-switch>

重点参考：

- `src-tauri/src/services/session_usage.rs`
- `src-tauri/src/services/session_usage_codex.rs`
- `src-tauri/src/database/schema.rs`
- `docs/user-manual/en/4-proxy/4.4-usage.md`

许可：MIT。可以参考或复用兼容模块，但同样记录文件、commit 和许可证。

### 17.3 Claude Waitlist

项目：<https://github.com/oyster-zzz/claude-waitlist>

只参考持久队列、倒计时、优先级和确认发送思路，不采用浏览器 DOM 注入方案。

## 18. 当前待讨论问题

2026-07-23 起本节原有 7 项已全部解决，详见 §19 决策记录（Windows/Linux 支持范围、前端结构重构时间点、远程访问认证与多用户边界、跨账号复制发布范围、Phase 3 真实回合测试账号/模型/预算、全文索引默认值、模型价格表）。当前没有待讨论问题；新问题出现时按 §19 决策记录的格式追加到本节。

2026-07-31：新增 `docs/ai-coding-workbench-visual-design.md` 作为 Workbench SPA 的视觉设计提案。其侧栏导航、会话中心分栏和独立运行中心路由方向等待审查；在确认前不得将其视为完成状态或以视觉稿推断运行能力。

## 19. 决策记录

| 日期 | 决策 | 状态 |
|---|---|---|
| 2026-07-21 | 参考项目修正为 `jlcodes99/cockpit-tools` | 已确认 |
| 2026-07-21 | 项目不以 Cockpit Tools 或 CC Switch 为安装依赖 | 已确认 |
| 2026-07-21 | Cockpit Tools 代码允许在非商业且满足许可证时参考/复用并署名 | 已确认 |
| 2026-07-21 | CC Switch 采用可选只读连接器，自有解析器始终存在 | 方案建议 |
| 2026-07-21 | App Server 采用能力探测和 fallback，不作为不可替换依赖 | 方案建议 |
| 2026-07-21 | 首阶段不写原生会话，不做自动跨账号同步 | 方案建议 |
| 2026-07-21 | 本项目不升级外部软件；需要时先沟通并建议用户从软件自身界面完成整包更新 | 已确认 |
| 2026-07-21 | Phase 2 升级的是本项目 CC Switch 兼容层，覆盖外部 schema v10/v16，不迁移外部数据库 | 已确认 |
| 2026-07-21 | 项目规则使用根 `AGENTS.md`，长期决策使用可审查的 project context，重复流程使用 repo skill | 已确认 |
| 2026-07-23 | workbench SPA 作为前端主壳，根路径 `/` 默认进入总览页；代理流量监控迁移为可跳转子页面，不再是默认首页 | 已确认 |
| 2026-07-23 | “总览”首页首版只做功能入口卡片，不嵌入统计小部件 | 已确认 |
| 2026-07-23 | 前端结构重构、样式系统统一、构建产物一致性校验列为独立技术债，暂不随主页改造一并实施 | 已确认 |
| 2026-07-23 | 项目长期上下文改为分流治理，取代 2026-07-21“长期决策使用可审查的 project context”一条：术语进根 `CONTEXT.md`；架构决策进本文档决策表，重大长期权衡进 `docs/adr/`；Phase 状态和执行证据进 `plans/ai-coding-workbench/`；`docs/project-context.md` 已删除 | 已确认 |
| 2026-07-23 | 首个正式版本仅正式支持并验收 Windows；Linux 设计上尽量保持可迁移，但不作兼容性、测试或维护承诺，也不作为发布阻塞项；未来正式支持 Linux 需单独批准并补齐测试矩阵 | 已确认 |
| 2026-07-23 | 前端结构重构和样式系统统一不并入 P1-12，也不作为 Phase 2 内部任务；P1-12 验收后单独设立 P1-13 前端基础整理门禁（只做结构迁移，不改变现有业务行为），完成后才批准 Phase 2 | 已确认 |
| 2026-07-31 | 新增 Workbench SPA 与代理流量监控视觉设计提案：以左侧应用导航、会话中心分栏、独立运行中心、可审计统计页和独立流量页为目标；总览仍不嵌入统计事实，最终实现范围待审查 | 待审查 |
| 2026-07-23 | 不做应用内远程服务：FastAPI 永远只监听 127.0.0.1，不建认证系统；远程访问由用户自行通过 SSH 隧道实现，隧道连入视为实例所有者本人，拥有当时开放的全部能力；不支持多人共享实例；真正的远程只读或多用户隔离需单独提出并批准 | 已确认 |
| 2026-07-23 | “多设备会话同步”需求拆解为远程查看/复制/交接/分叉四个精确概念（定义见 `CONTEXT.md`）：远程查看复用已确认的 SSH 隧道方案，不需要新功能；复制沿用 Phase 5 已设计的一次性迁移流水线；新增“交接”作为复制的一种用户操作，在 Phase 5 内实现（P5-11）；不实现持续双向原生文件同步——两个物理副本各自独立写入产生的分叉不能按时间戳自动合并，且绕过工作台的原生 CLI 写入无法被 writer lease 约束 | 已确认 |
| 2026-07-23 | Phase 5（跨账号复制）不作为首个正式版本的发布门槛；Phase 5 在 Phase 1/3/4 稳定后单独审查、独立发布，交付时默认关闭并标记为实验性功能；首批只开放已完整验证的 copy/fork 组合，replace、设备交接、Claude 目标、跨 provider 分别验证通过后再逐项开放；“实验性”只能收窄支持范围，不得降低备份、precondition、原子写入、回滚、隐私披露的验收标准 | 已确认 |
| 2026-07-23 | Phase 3 真实回合测试采用"日常账号 + 一次性硬范围"账号模板：使用已登录的日常 Codex/Claude 账号，但每次批准只覆盖固定业务回合数，不构成后续测试或自动重试授权；模型选择只读探测账号可用列表后选最低成本、最可预测档位，批准单须写明确切型号；预算以结构化字段（回合数、单回合输入/输出/turn数/时长、单工具和总预算上限、重试和模型回退规则、中止条件）表达，不用单一金额数字；真正执行前需逐字段填写并批准 `plans/ai-coding-workbench/03-interactive-runtime.md` P3-10 审批单模板 | 已确认 |
| 2026-07-23 | 全文索引默认值改为"新实例默认建议开启，但首次构建索引前明确提示（存储位置、脱敏局限、关闭/清空方式）并允许拒绝；已有安装不自动改变现有设置"，见 `plans/ai-coding-workbench/01-read-only-session-center.md` P1-14 | 已确认 |
| 2026-07-23 | 模型价格表不由项目维护内置权威数据，只实现可插拔 pricing source：价格来自用户导入/配置的本地 snapshot，每条估算附带来源、生效时间、更新时间和币种，无价格源时显示不可用；见 `plans/ai-coding-workbench/02-statistics-center.md` P2-06 | 已确认 |
| 2026-07-23 | CC Switch 的 `model_pricing` 表可作为 pricing source 的候选来源（方案 C）：只读探测但默认不启用，用户显式信任后才生效；只产生 API-equivalent estimate，不改写 token/会话/实际成本事实；用户自建价格 snapshot 优先级高于此来源；当前仅确认表存在，列结构/币种/生效时间语义验证完成前不得自动启用；P2-00/P2-04 同步补充一致性读取、锁状态区分、schema 缓存、多数据库路径发现、文件替换游标失效等兼容性设计缺口 | 已确认 |
| 2026-07-23 | 术语消歧：`CONTEXT.md` 改为 Native 层/Workbench 层两栏结构；确认 Workbench 的 Profile（`tool_profiles`，配置根目录+会话根目录组合）与 Codex 原生 `--profile`（同一 CODEX_HOME 内更小粒度的配置切换，Claude 无对应机制）是不同概念，互不替代；新增 Provider、账号、Turn、Thread、实例五个词条；Thread 与 `native_session_id` 的映射规则留待 Phase 3 确认，不提前定义 | 已确认 |
| 2026-07-24 | 仓库结构反转：AI Coding Workbench 是主产品，仓库根即 Workbench 工程根（`app/`/`frontend/`/`tests/` 提升到仓库根，不再套 `products/`/`ai-coding-workbench/` 包装目录）；代理流量监控降级为挂载在主产品上的辅助功能 `features/proxy-traffic-monitor/`；未来新增辅助功能统一走 `features/<slug>/`，提供进程内模块/静态子应用/独立进程三种技术栈无关的集成模式；文档治理不对称——根 `AGENTS.md`/`CONTEXT.md` 兼任仓库级和主产品治理，辅助功能默认只配轻量 README；详见 `docs/adr/0002-workbench-root-and-feature-module-layout.md`（取代 ADR 0001 的放置决定）。物理迁移已于当日完成：`git mv` 保留历史记录，26 个测试（Workbench 21 + 代理流量监控 5）全部通过，端到端 TestClient 冒烟测试确认两个子系统在同一 FastAPI 进程内正常工作 | 已确认，迁移已完成 |
