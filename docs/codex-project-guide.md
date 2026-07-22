# Codex 项目协作指南

## 目的

本指南说明 Codex 在该项目中如何使用项目约束、配置、skills、项目上下文和本地 Memory，以及不同文件分别承担什么职责。它不重复产品架构；产品设计以 `ai-coding-workbench-architecture.md` 为准。

## 协作层级

```text
AGENTS.md
  └─ 每次在仓库中工作都应遵守的短规则和路由

.codex/config.toml
  └─ 项目受信任后加载的 Codex 本地运行配置

.agents/skills/ai-coding-workbench/
  └─ 规划、审查、实现工作台时使用的可复用工作流

docs/project-context.md
  └─ 人工维护、可审查、随项目保存的长期事实和决策；不是 Codex Memory

plans/ai-coding-workbench/
  └─ 分阶段任务、验收门槛和执行证据

~/.codex/memories/
  └─ Codex 自动生成的个人本地记忆，不属于仓库事实源
```

OpenAI 官方把这些能力定义为互补层：`AGENTS.md` 约束持续行为，memories 携带从历史工作中学习到的本地上下文，skills 封装可重复流程。官方建议必需的团队规则仍写在 `AGENTS.md` 或版本化文档中，而不是只依赖 memory。

当前官方文档没有定义仓库级 `.codex/memories/`。Codex Memory 的存储位置属于 `CODEX_HOME`，默认是用户目录下的 `~/.codex/memories/`；因此不要在仓库中创建 `.codex/memories/` 并期待 Codex自动加载。

## AGENTS.md

根目录 `AGENTS.md` 只保存每次都必须遵守的规则：

- 文档路由和当前架构事实源。
- 阶段批准门槛。
- 第三方目录和凭据安全边界。
- 实现与验证约束。
- 当前可执行的基础测试命令。

更细的目录规则应在未来对应子目录稳定后再增加嵌套 `AGENTS.md`。不要把完整架构复制进根文件，避免每次会话浪费上下文。

## 项目配置

`.codex/config.toml` 当前保留已有设置：

```toml
approval_policy = "never"
sandbox_mode = "workspace-write"

[features]
memories = true
```

注意：Codex 只在用户信任项目后加载项目级 `.codex/` 配置。未信任时，项目配置、hooks 和 rules 会被跳过，但根目录 `AGENTS.md` 仍是仓库协作约束。

这里的 `memories = true` 只是在受信任项目中启用本机 Memory 功能，不会创建项目隔离的 Memory 仓库；生成内容仍写入当前 Codex host 的 `CODEX_HOME/memories/`。是否让某个会话读取或贡献本地 Memory，仍由用户通过 `/memories` 控制。

`workspace-write + never` 不是“完全权限”：它表示不弹审批并限定在允许的工作区写入范围内。不要用 `danger-full-access` 或 `--dangerously-bypass-approvals-and-sandbox` 解决普通开发问题。

## Repo skill

项目 skill 位于：

```text
.agents/skills/ai-coding-workbench/
├── SKILL.md
└── agents/openai.yaml
```

触发场景包括：

- 修改工作台架构或项目上下文。
- 审查、修订或实施某个 Phase。
- 开发会话索引、统计、实时执行、调度或跨 profile 迁移。
- 处理 Cockpit Tools、CC Switch 的兼容和共存边界。

可显式调用：

```text
$ai-coding-workbench 审查 Phase 1 计划，但不要实现
```

skill 只保存工作流和安全边界，详细设计直接读取仓库中的架构与 phase 文件，避免重复维护。

## 本地 Memory 与项目上下文

### Codex 本地 memories

Codex CLI 的本地 memories 默认关闭；启用后由 Codex 在后台从符合条件的历史会话中生成，存储在 `~/.codex/memories/`。可以在交互式会话中用 `/memories` 控制当前会话是否读取或贡献记忆。

这些文件属于生成状态：

- 不手工编辑为主要控制手段。
- 不作为项目强制规则的唯一来源。
- 分享 `CODEX_HOME` 前检查是否包含不适合共享的上下文。
- 显式用户要求、`AGENTS.md` 和仓库文档优先于记忆。

### 项目长期上下文

`docs/project-context.md` 是人工维护的项目长期记录，解决自动 Memory 不可审查、不可随项目部署的问题。它不是 Codex Memory，也不应移动到 `.codex/memories/`。只写入：

- 已验证的环境和协议事实。
- 用户明确确认的架构决策。
- 当前阶段及完成状态。
- 仍待确认且会影响方案的关键问题。

不要写入：

- API Key、账号 token、Cookie 或凭据路径内容。
- 临时调试输出。
- 未验证猜测。
- 详细任务列表；任务属于 `plans/`。

## 文档更新协议

当用户提出架构建议时：

1. 更新 `docs/ai-coding-workbench-architecture.md`。
2. 将已确认的持久结论同步到 `docs/project-context.md`。
3. 更新受影响的 Phase 计划和依赖。
4. 在架构决策记录中保留日期和状态。
5. 不因为文档确认自动开始实施。

当实施一个 Phase 时：

1. 确认 Phase 状态为 `已批准`。
2. 只执行该 Phase 的任务。
3. 在 Phase 文件中记录验证证据。
4. 完成退出标准后停止，等待用户验收。

## 官方依据

- Codex customization：<https://developers.openai.com/codex/concepts/customization>
- Codex memories：<https://developers.openai.com/codex/memories>
- Codex config basics：<https://developers.openai.com/codex/config-basic>
