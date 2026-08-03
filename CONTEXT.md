# AI Coding Workbench 上下文与术语

本文件只定义跨文档、跨模块共享的术语。产品架构以
[`docs/ai-coding-workbench-architecture.md`](docs/ai-coding-workbench-architecture.md)
为准；已确认的产品交互决策以
[`docs/conversation-workspace-rethink.md`](docs/conversation-workspace-rethink.md)
为准。

## 产品边界

- **AI Coding Workbench（Workbench）**：整合本机 Codex、Claude 等原生编程工具的会话、运行入口、自动任务、用量与诊断的本地工作台；不是第二个模型服务、第二份完整会话库或代理服务。
- **原生工具**：Codex、Claude Code 等实际创建会话、执行 CLI/App Server、持有原生会话文件的工具。
- **原生数据源**：原生工具维护的会话 JSONL 与相关只读元数据。会话内容的事实来源，不由 Workbench 复制、改写或替代。
- **原生会话（Native Session）**：由某个原生工具创建并以“工具 + 原生会话 ID”唯一标识的一段会话。
- **会话工作区（Conversation Workspace）**：一级“会话”页的三栏交互空间：全局导航、会话上下文列表、可读消息主区；按需打开高级诊断抽屉。

## 数据与索引

- **轻量索引（Lightweight Index）**：Workbench 自己持久化的少量会话定位和组织元数据，例如工具、原生会话 ID、源路径指纹、偏移量、标题、最近摘要、活动时间、项目、来源健康度和分组归属。它不是会话副本。
- **项目登记项（Project Registration）**：用户确认的规范化根目录、显示名与类型。`project` 可接收会话主归属；`workspace` 只组织子项目和容器内未归属会话。`.git` 只能帮助发现候选目录或类型，不是登记、统计或归属的必要条件。
- **工作区容器（Workspace Container）**：包含多个实际项目的登记目录，例如 `E:\project`。它可汇总子项目和容器内未归属用量，但不接收会话主归属，也不把未登记子目录自动算入父项目。
- **项目归属（Project Attribution）**：一个会话的唯一主项目关系。`native_cwd` / `controlled_run` 表示原生或受控 cwd 自动匹配，`manual` 表示用户确认；归属来源独立于 Token 的精确性。
- **按需原文读取（Source-on-demand Read）**：打开会话、加载更早消息和全文检索时直接解析原生会话文件，而不是查询已持久化的完整转录本或 raw 事件投影。
- **受控运行审计（Controlled Run Audit）**：Workbench 对一次 New、Resume、Handoff 或自动任务提交所保存的最小可追溯记录；它不取代原生会话内容。
- **原生转录本（Native Transcript）**：原生 JSONL 中的人类消息、模型消息、工具活动和协议事件。仅在需要时读取；原始协议仅在高级诊断中展示。
- **重型投影（Heavy Projection）**：持久化完整 raw JSON、事件流、结构化消息副本、会话副本或完整 FTS 的旧设计。目标架构不再保留它。

## 会话组织与动作

- **用户分组（Group）**：用户在 Workbench 内为会话建立的一个主分组。V1 中每个会话至多属于一个主分组，不使用标签。
- **收件箱（Inbox）**：用户主动常驻在会话列表顶部的会话位置；不是未读状态。解除常驻后会话回到“最近”的原有时间位置。
- **最近（Recent）**：未在任何用户分组或收件箱中的全部会话，按原生最后活动时间排序的完整时间线，不是“最近 N 条”。
- **New**：在所选原生工具中新建原生会话。
- **Resume**：在相同工具中继续同一个原生会话。
- **Handoff**：把用户选定消息或摘要作为上下文，在另一工具中新建原生会话；绝不伪装为跨工具 Resume。
- **原生回合完成（Native Turn Completion）**：适配器接收到原生工具明确的回合完成信号（例如 `turn/completed`）后，当前输入才完成。消息流中的 delta 和 item 完成并不等于回合完成。

## 自动任务与设备

- **任务定义（Task Definition）**：可重复执行的计划配置，包含日程、时区、提示词序列、New/Resume 目标、权限参数和并发规则。
- **任务运行（Task Run）**：任务定义的一次实际或跳过的调度尝试；若真正调用原生工具，会关联一个原生会话。
- **所有者设备（Owner Device）**：运行 Workbench 服务、原生工具进程、原生文件和任务调度的那台设备。远程浏览器仅是该设备的 UI，不产生第二个执行端。
- **显式迁移（Explicit Migration）**：用户发起并确认的跨设备迁移/交接，传输轻量元数据、选择的原生会话文件和可选的小型任务摘要；不会后台自动同步或合并原生 JSONL。
- **会话分叉（Session Fork）**：在另一设备复制并继续原生会话文件后形成的独立分支。分叉之间不自动合并；需要结合时使用 Handoff。

## 统计与外部工具

- **全局模型用量**：本机已观测的编程模型请求聚合，包含请求、Token、估算成本和可用性能指标；优先来自兼容且已启用的 CC Switch 只读适配器，不能与同范围原生回退结果相加。
- **项目级模型用量**：按 Workbench 已确认项目归属聚合的同一套模型指标。自动归属只在原生/受控 cwd 所在的已登记 `project` 根目录中选择最长匹配；未匹配保持未归属，位于 `workspace` 的未匹配会话只标记容器。近期 CC Switch 明细仅在 `session_id` 精确匹配“工具 + 原生会话 ID”时继承该归属；全历史基线和缺口由该项目原生 JSONL 建立或增量回退。
- **项目日用量汇总**：Workbench 保存的项目、日期、工具、provider、模型级聚合数字及来源/覆盖水位；不保存请求明细、完整 raw event 或会话正文。
- **CC Switch 只读用量适配器**：用户显式启用、按已测试版本/schema allowlist 读取最小非敏感用量字段的可选适配器。它不读取 CC Switch 凭据、provider 设置、订阅窗口或余额缓存，也不是运行依赖。
- **代理请求观测**：CC Switch 等代理/导入器观察到的请求记录；可能与原生会话重叠，须先按该来源的有效记录规则去重，不能与原生同范围结果直接相加。
- **账户余额 / 订阅窗口**：由各厂商官方连接器或用户配置提供的独立数据类型，不与会话 Token 或代理请求观测混用。
- **代理流量**：`features/proxy-traffic-monitor` 提供的 Clash/Mihomo 网络字节、连接、域名和运行状态辅助视图；与模型 Token、请求成本和 CC Switch 数据不同。

## 废弃术语

- 不再使用“Session Copy（会话副本）”“完整会话投影”或“Conversation Family（会话家族）”作为产品数据模型。
- “运行中心”不再是一级页面；运行入口在会话工作区，运维/诊断能力分散到总览、用量统计、设置、自动任务和会话高级诊断抽屉。
