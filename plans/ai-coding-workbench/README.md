# AI 编程工作台分阶段计划

> 状态：架构重基线后待逐阶段审查
> 更新时间：2026-08-01-22-45-00
> 架构依据：[架构](../../docs/ai-coding-workbench-architecture.md)、[会话工作区决策](../../docs/conversation-workspace-rethink.md)、[术语](../../CONTEXT.md)
> 实施规则：只有用户明确批准某一 Phase 后，才可以实现该 Phase；计划更新不构成代码实施授权。

## 计划目的

本目录把已确认的目标架构拆成可审查、可验收的实施阶段。Workbench 的目标是整合原生 Codex / Claude，而不是再建一份完整 transcript、事件仓或模型服务：原生 JSONL 是正文事实源；Workbench 只保存轻量索引、用户组织数据、自动任务与最小受控运行审计。

旧计划中已经完成的试验、测试和实现记录仍可作为历史证据，但不能被理解为目标架构已完成。每个 Phase 都明确列出：

- **过时项**：不再实施、后续迁移时删除或停止维护的旧方向；
- **清理清单**：需要从现有代码、数据模型、路由或前端移除的内容；
- **修改清单**：可保留但必须改成新边界的能力；
- **新增任务**：目标架构仍缺失、必须新建的能力。

除已有历史证据外，重基线产生的任务一律从 `[ ]` 开始。完成后须填入同一 Phase 的“执行证据”，并按 [通用验证边界](../../docs/verification-and-boundaries.md) 验证。

## 推荐实施顺序

| 顺序 | Phase | 目标 | 当前状态 |
| --- | --- | --- | --- |
| 0 | [00-technical-foundation.md](00-technical-foundation.md) | 固化新数据边界、迁移前审计与 fixture 基线 | 待审查 |
| 1 | [01-read-only-session-center.md](01-read-only-session-center.md) | 轻量索引、原生按需读取、三栏会话工作区 | 待审查；后续实现的第一依赖 |
| 2 | [02-statistics-center.md](02-statistics-center.md) | 四类用量目标、CC Switch 只读聚合、项目日汇总、额度/余额 | 待审查；依赖 Phase 1 来源读取 |
| 3 | [03-interactive-runtime.md](03-interactive-runtime.md) | 会话内 New / Resume / Handoff 与最小运行审计 | 待审查；依赖 Phase 1 |
| 4 | [04-automation-scheduler.md](04-automation-scheduler.md) | 任务定义、调度与会话内结果入口 | 待审查；依赖 Phase 3 |
| 5 | [05-cross-profile-migration.md](05-cross-profile-migration.md) | 显式迁移、来源副本与分叉处理 | 待审查；依赖 Phase 1、3、4 |
| 6 | [06-traffic-ui-unification.md](06-traffic-ui-unification.md) | 保持 Clash/Mihomo 网络流量辅助视图并接入新导航 | 待审查；可与核心 Phase 并行评审 |
| 7 | [07-visual-design-implementation.md](07-visual-design-implementation.md) | 以已确认视觉规范统一总览、会话、任务、用量和设置 | 待审查；随各功能 Phase 逐步落地 |

Phase 0–7 不是自动流水线。每一阶段结束后必须：核对该文件的退出标准、记录验证证据、更新 `docs/phase-execution-lessons.md`，并请用户确认是否进入下一阶段。

## 全局不可违背的约束

- [ ] 不把完整 native transcript、每条 raw event、常驻全文 FTS 或会话副本重新写入 Workbench 数据库。
- [ ] 不把“运行中心”或“运维”恢复为一级页面；运行入口与诊断按架构分散到会话、总览、任务、用量和设置。
- [ ] 不读取、展示、调用或写入 Cockpit Tools 的账号、多实例、配额、同步、日志、API 或凭据；移除 Workbench 的 Cockpit 专用目录发现路径。
- [ ] 不依赖 CC Switch；用户启用且版本/schema 兼容时，才以其最小非敏感只读用量聚合作为优先统计来源，并始终提供原生回退。
- [ ] 不写入 Codex / Claude 原生会话文件，除非已批准的显式迁移任务逐文件列明目标、预检、用户确认与结果报告。
- [ ] 不把代理流量的网络字节/连接指标与模型 Token、余额或订阅额度混合。
- [ ] 删除旧重型投影前，向用户展示精确对象、预计释放空间与保留的轻量数据；删除后报告实际释放空间，不保留兼容读取或同等大小备份。

## 计划维护规则

- 计划以当前代码和 `tests/ai_workbench/` 的实际结构为证据；测试文件名、命令和结果只写入对应 Phase，不写入通用验证文档。
- 一个已完成的旧任务若与新架构冲突，应移至“过时项/清理清单”，而不是继续打勾作为交付完成。
- 每个新任务必须写成可验证的 `[ ]` 条目；只有实施、测试和证据同时存在后才改为 `[x]`。
- 外部工具协议、schema、供应商 API 等易变事实在实施前重新调研；不要用旧计划中的版本号作为当期事实。
