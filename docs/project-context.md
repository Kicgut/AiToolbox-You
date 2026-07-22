# AI 编程工作台项目上下文

> 性质：人工维护、可审查、随项目保存的长期上下文；它不是 Codex 自动生成的 Memory。  
> 最近更新：2026-07-22。  
> 规则：只记录已验证事实、已确认决策、当前状态和关键待决项。

## 为什么不放在 `.codex/memories/`

- Codex 官方文档只说明本地 Memory 存储在 `CODEX_HOME` 下，默认是用户目录的 `~/.codex/memories/`。
- 当前没有文档化的仓库级 `.codex/memories/` 发现或加载机制；在项目中自行创建该目录不能视为有效的项目 Memory。
- `~/.codex/memories/` 是 Codex 生成的个人本地状态，不应作为团队规则或项目事实的唯一来源，也不应通过本项目手工维护。
- 项目级持久约束放在 `AGENTS.md`，可复用流程放在 `.agents/skills/`，可版本化的事实和决策放在本文件。

## 当前状态

- 架构文档：`docs/ai-coding-workbench-architecture.md`，状态为 Draft v0.1。
- 阶段计划：Phase 0–5 拆分到 `plans/ai-coding-workbench/`，均需逐阶段审查批准。
- Phase 0 已完成隔离原型实现和内部验证，状态为待验收；尚未开始 Phase 1。
- 已建立根 `AGENTS.md` 和 repo skill `$ai-coding-workbench`。

## 已确认决策

- 参考项目是 `jlcodes99/cockpit-tools`，不是 `cockpit-project/cockpit`。
- 项目不计划商业化；可以在满足 CC BY-NC-SA 4.0 的署名和相同方式共享条件时复用 Cockpit Tools 代码。
- 复制上游代码时必须记录 repository、source URL、commit SHA、license 和本项目修改。
- Cockpit Tools 和 CC Switch 都是可选集成，不是部署依赖。
- 没有安装 Cockpit Tools 或 CC Switch 时，核心会话查看和基础统计仍必须完整工作。
- 先完成只读会话中心，再开放 resume、自动任务和跨 profile 写入。
- 前端目标为 Vue 3 + TypeScript + Vite；发布产物随 FastAPI 分发，部署端不要求 Node.js。
- 本项目不负责升级、降级、重装或修复 Cockpit Tools、CC Switch、Codex CLI、Claude Code 等外部软件。
- 项目规范仓库为 `https://github.com/Kicgut/AiToolbox-You.git`；每个完整且验证通过的变更单元应使用仓库级 Kicgut 身份提交并同步到 `origin/main`，不修改其他项目使用的全局 Git/GitHub 账号配置。

## 已验证事实

- 本机 Codex CLI 0.144.4 提供 `resume`、`exec --json`、`exec resume --json` 和 `app-server`。
- 已通过 stdio 对 App Server 完成 `initialize → initialized → thread/list(limit=1)`，未创建 Turn、未产生模型请求。
- 2026-07-22 已通过 `codex.cmd app-server --stdio` 完成 `thread/read(includeTurns=false)` 只读验证；未调用 `thread/start` 或 `turn/start`。
- Codex App Server `generate-json-schema` 可生成稳定 schema，当前 schema 包含 `thread/list` 和 `thread/read`。
- 本机 Claude Code 2.1.200 提供 `--resume`、`--continue`、`--fork-session` 和 `stream-json`。
- Codex 与 Claude 的本地 JSONL 足以解析消息、工具调用、工具结果和 usage，但历史文件通常缺少可靠账号身份。
- 本机 Cockpit Tools 和 CC Switch 可以与只读扫描同时运行。
- 本机 CC Switch 3.15.0 的 `~/.cc-switch/cc-switch.db` 为 schema v10。
- 2026-07-21 官方最新 CC Switch 为 [3.18.0](https://github.com/farion1231/cc-switch/releases/tag/v3.18.0)，其数据库 schema 为 v16。
- 上述 schema v10/v16 都属于 **CC Switch 自身数据库**，不是本项目数据库版本。当前仓库不存在“本项目数据库 schema v10 → v16”的迁移任务。
- 现有项目数据库 `proxy-traffic-monitor/data/traffic.db` 的 `PRAGMA user_version = 0`，目前只有 `traffic_minute_app` 和 `connection_log`；新的 AI Coding Workbench 自有数据库尚未实施，将在 Phase 1 建立独立 schema version 和迁移机制。
- Phase 0 已在 `proxy-traffic-monitor/app/ai_workbench/` 建立隔离原型：能力探测、统一事件、只读 CC Switch schema probe 和 fake CLI process supervisor；没有挂入正式 API 或前端页面。
- Phase 0 process supervisor 仅覆盖 argv/stdin/stdout/stderr/timeout/有限缓冲原型；Windows Job Object 进程树管理留到 Phase 3 正式运行中心实现。

## 外部软件版本策略

- 版本、可执行文件和 schema 探测必须只读。
- 本项目不得调用安装器、包管理器、内置 updater 或数据库 migration 来升级外部软件；阶段批准也不自动包含这种授权。
- 若发现 CC Switch、Cockpit Tools 或其他外部工具版本较旧，只记录兼容性影响并告知用户。
- 如升级有价值，先与用户沟通，并建议用户通过该软件自己的设置或“检查更新”界面完成整包升级。
- 用户完成升级后，本项目只重新探测版本、重跑兼容性测试；不得把升级作为核心功能的前置条件。
- 连接器必须同时兼容“未安装、旧版本、当前版本、未知未来版本”，不能用升级本机软件替代兼容设计。
- “升级本项目”在这里指更新本项目自己的 connector、parser、fixture 和数据模型以理解 CC Switch v10/v16，而不是修改 CC Switch 软件或把它的数据库从 v10 迁到 v16。

## 不可破坏的安全边界

- 未批准的阶段不得修改第三方会话、账号、配置或数据库。
- CC Switch 连接器永远只读，不执行其 schema migration。
- 不为了账号归属读取或保存 token、Cookie 和明文凭据。
- 未经明确批准，不发送真实模型测试提示词，不消耗订阅或 API 额度。
- 自动任务不得默认使用危险权限绕过。
- GitHub 同步前检查 staged diff、敏感信息和本地运行数据；不得强制推送或擅自改写已发布历史。

## 当前关键待决项

- 首个正式版本是否同时支持 Windows 和 Linux 服务器。
- 远程查看会话全文的认证和多用户边界。
- 全文索引是否默认开启。
- Phase 3 真实回合测试使用的账号、模型和预算。
- 跨账号复制是否进入首个正式版本。
- 是否维护项目自己的公开模型价格表。

## 更新规则

- 用户确认的新架构结论同步到本文件。
- 详细理由写入架构文档，任务和验证证据写入对应 Phase 文件。
- 被推翻的结论从“已确认决策”移除，并在架构决策记录保留变更历史。
- 不将临时会话摘要或未经确认的建议提升为项目长期上下文。
