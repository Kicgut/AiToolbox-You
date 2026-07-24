# AI Coding Workbench 术语表

跨代码、UI 文案、文档反复使用的规范名称和简短定义。不含实现细节、决策理由或状态——那些分别属于 `docs/ai-coding-workbench-architecture.md`（架构与决策记录）、`docs/adr/`（重大架构决策）和 `plans/ai-coding-workbench/`（阶段任务与执行证据）。

术语分两层：**Native 层**是 Codex/Claude/CC Switch/Cockpit Tools 自己的词汇，本项目不重新定义、只引用；**Workbench 层**是本项目自己设计的统一抽象，建立在 Native 层数据之上，不替代、不改写原生数据。新增词条前必须先问一句"这个词有没有原生对应物，含义是否一致"，避免重复 Profile 词条曾经出现过的遗漏。

## Native 层

**原生会话（Native Session）**：
Codex 或 Claude CLI 自己创建、拥有、写入的会话，物理形式是本机 JSONL transcript 文件（如 `~/.codex/sessions/**/*.jsonl`、`~/.claude/projects/**/*.jsonl`）。本项目对其永远只读，绝不写入。
_Avoid_: 会话（单独使用时，必须先说明是原生会话还是 Workbench 会话副本）

**原生 Session ID**：
Codex/Claude 原生 rollout/JSONL 文件中的 `session_id`/`sessionId`/`id` 字段。对应 Workbench 的 `native_session_id`，是会话副本唯一键的一部分。

**Codex 原生 `--profile`**：
Codex CLI 自己的配置切换机制：`~/.codex/<name>.config.toml`，通过 `codex --profile <name>` 选用一组 model/审批策略/sandbox 等配置，优先级介于项目级配置和默认 `config.toml` 之间。**与 Workbench 的 Profile 不是同一概念**——这是同一个 `CODEX_HOME` 内部的配置切换，粒度比 Workbench Profile 小得多；Claude Code 没有对应机制，这个冲突只存在于 Codex 一侧。
_Avoid_: 不要简称"profile"后直接当作 Workbench Profile 使用；必须写"Codex 原生 --profile"

**Thread（Codex App Server 协议）**：
Codex App Server 协议方法（`thread/start`、`thread/list`、`thread/read` 等）里的会话标识概念。Phase 1 只读解析 JSONL，尚未触达 App Server，因此 Thread 与 Workbench `native_session_id` 的映射规则目前未定义，留待 Phase 3 引入 App Server 客户端时确认，不在此提前下结论。

**实例（Instance）**：
Cockpit Tools 自己的原生概念，记录在其 `codex_instances.json` 里。Workbench 不使用"实例"这个词描述自己的抽象，对应的本项目概念请用 Profile（Workbench 层）。
_Avoid_: 用"实例"指代 Workbench 的 Profile

**Provider（原生）**：
Codex/Claude 自己 `config.toml` 里的 `model_providers` 配置，或 CC Switch 自己数据库里的 `providers` 表——两者都是各自软件定义的供应商配置，含义不由本项目决定。

**账号（Account）**：
Codex/Claude 自身的登录身份。本项目不做认证、不读取或保存明文凭据，只用 Workbench 层的 `account_ref`/`account_source`/`account_confidence` 记录可信度不同的归属推断，不构成本项目自己的用户体系。

## Workbench 层

**workbench SPA**：
Vue 3 + TypeScript + Vite 构建的前端单页应用，是 AI Coding Workbench 的用户界面，浏览器根路径 `/` 的默认入口。
_Avoid_: 前端、workbench 页面

**总览（Overview）**：
workbench SPA 的默认首页路由（`/`），展示功能入口卡片：已上线功能可点击，未上线功能显示为禁用占位并标注对应 Phase。目标态，落地进度见 `plans/ai-coding-workbench/01-read-only-session-center.md` P1-12。
_Avoid_: 首页、主页

**会话中心（Session Center）**：
workbench SPA 内查看、搜索 Codex/Claude 会话记录的页面，目标挂载在 `/sessions`。目标态，当前实现仍挂载在旧路径 `/workbench`，落地进度见 P1-12。
_Avoid_: 会话页、workbench 页（旧名，P1-12 完成后废弃）

**代理流量监控（Proxy Traffic Monitor）**：
独立的、零构建的 Clash/Mihomo 流量监控页面，目标挂载在 `/traffic`，技术实现（Vue ESM 直引、无 Node.js 依赖）与 workbench SPA 无关。目标态，当前实现仍在根路径 `/`，落地进度见 P1-12。
_Avoid_: 旧主页、流量页

**会话族（Conversation Family / ConversationFamily）**：
Workbench 自己的逻辑分组，纯本项目概念，原生工具没有对应物。一个会话族可能对应多个物理会话副本——同一原生 Session ID 经跨实例复制或分叉后产生。对应 `conversation_families` 表。
_Avoid_: 会话（容易与会话副本混淆）

**会话副本（Session Copy / SessionCopy）**：
Workbench 对一个原生会话的只读索引记录和解析结果（族归属、分叉状态等派生字段），不包含独立可写的会话状态。由 `(tool, profile_root, native_session_id, transcript_path)` 唯一标识，对应 `session_copies` 表。
_Avoid_: session（单独使用时必须先分清是原生会话还是这里的索引记录）

**Profile（ToolProfile）**：
Workbench 对"一个工具的配置根目录 + 会话根目录"组合的统一抽象，是本项目对"发现了一处原生配置目录"的登记和能力探测结果，不是新账号或新配置系统，对应 `tool_profiles` 表。
_Avoid_: 账号、实例（容易与 account_ref 混淆）；**且不得与 Codex 原生 `--profile` 配置混淆**——原生 `--profile` 是同一 `CODEX_HOME` 内部更小粒度的配置切换，Claude 无对应机制，两者不是同一层概念

**Turn（Workbench 记录）**：
`turns` 表对原生 Turn 事件的索引记录，与原生 Turn 一一对应，不设"副本"层——不像会话副本那样可能有多个物理副本、可能分叉，Turn 没有这种多副本/分叉语义。
_Avoid_: 不要类比 Session 的处理方式给 Turn 设计"TurnCopy"式拆分

**Provider（记录字段）**：
`tool_profiles`/`session_copies` 上的 `provider` 字段，转录 Codex/Claude 原生配置或 CC Switch 观测到的供应商信息，Workbench 不自行定义新的供应商语义，出现冲突时以原生/CC Switch 记录为准。

**数据质量标记**：
每个统计指标必须标注为"精确""估算"或"不可用"三态之一；"不可用"显示为 `—`，禁止用 `0` 代替缺失数据。
_Avoid_: N/A、默认值 0

**远程查看**：
主设备继续持有并续写原生会话，其他设备通过 SSH 隧道连接同一个运行中的 workbench 实例查看历史，不产生新的会话副本。
_Avoid_: 远程同步

**复制**：
用户显式发起的一次性、事务性操作，把一个会话副本的静止内容复制到另一个 profile/设备，产生新的独立 SessionCopy，之后两边各自独立演化。对应 Phase 5 的迁移流水线。
_Avoid_: 迁移同步、备份（复制不隐含定期性）

**交接**：
复制的一种用法：复制完成后，明确把"当前活跃写入位置"从源设备转移到目标设备，提示用户不要在源设备继续写入，但不做自动合并，也无法强制阻止用户绕过工作台直接使用原生 CLI。
_Avoid_: 切换、迁移（迁移在本项目指整个 Phase 5 能力，交接是其中一种用户操作）

**分叉**：
同一会话族下的两个会话副本各自基于同一历史前缀独立产生了不同的后续内容（`divergence_status = diverged`）。禁止按时间戳交错自动合并，只能由用户选择查看某一方或显式建立新分支。
_Avoid_: 冲突、脑裂（脑裂描述的是产生分叉的过程，分叉是本项目记录的状态）

**会话同步（禁用词）**：
不使用这个词，因为它混淆了远程查看、复制、交接三种不同行为。凡是产品文案、代码命名或讨论中出现"同步"描述会话内容跨设备可用性时，必须换成以上三个精确词之一。持续双向原生文件同步（两台设备都能写同一个 native session 并自动合并）已评估为不实现，见架构文档 §19 2026-07-23 决策记录。
_Avoid_: （本条目本身即为 Avoid 声明）
