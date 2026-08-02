# Codex App Server 原生事件映射清单

本文统一记录 Codex App Server stdio/JSON-RPC 事件到 Workbench 事件契约的映射。表中“当前状态”以 `app/ai_workbench/execution/codex_runtime.py::_map_record` 为准；“建议处理”用于下一轮协议兼容完善。

## 1. 映射原则

1. 先读取顶层 `type`、`event` 或 JSON-RPC `method`。
2. JSON-RPC 通知先展开 `params`，再读取 `params.item`、`params.delta` 等业务字段。
3. `item` 的具体 `type` 决定它是用户消息、模型消息还是工具活动。
4. 原始 `method`、`params` 和 `source_event_type` 保留在事件 payload 中，便于审计和未来重放。
5. 原生回合是否结束只由 `turn/completed`（归一化为 `run.completed`）和 Workbench 终态共同确认；单个 `item/completed` 不代表整个回合结束。
6. reasoning 内容不直接当作用户可见回复；只保存安全的生命周期/摘要元数据，避免泄露内部推理内容。

## 2. 客户端生命周期与回合事件

| 原生事件 | 常见 payload | Workbench 事件 | 页面区域 | 当前状态 | 处理说明 |
|---|---|---|---|---|---|
| `thread/started`、`thread.started` | `threadId` | `run.started` | 状态/审计 | 已处理 | 记录 native thread/session 映射 |
| `turn/started` | `turn`、`threadId` | `run.started` | 状态/审计 | 已处理 | 表示本次回合已被原生接受 |
| `turn/completed` | `turn.status`、`usage` | `run.completed` | 状态 | 已处理 | 回合终止信号；不能被 usage 分支抢先匹配 |
| `turn/failed`（若版本提供） | `error` | `error` | 诊断 | 待补充 | 应写入 `failure_code/message`，并进入失败终态 |
| `turn/cancelled`、`turn/interrupted`（若版本提供） | `reason` | `run.cancelled`/`run.interrupted` | 状态 | 待补充 | 与 Workbench Cancel 状态机对齐，不能当作普通失败 |
| `thread/status/changed` | `status.type`、`activeFlags` | `run.status_changed` | 状态 | 待补充 | `active/idle` 作为原生状态证据，不直接覆盖 Workbench 终态 |
| `thread/goal/cleared` | `threadId` | `run.goal_changed` | 审计 | 待补充 | 只记录目标变化，不生成回复 |

## 3. 用户、模型与工具 item 事件

| 原生事件 | `item.type` | Workbench 事件 | 页面区域 | 当前状态 | 处理说明 |
|---|---|---|---|---|---|
| `item/started` | `userMessage` | `user.message` | 对话 | 已处理 | 记录用户输入开始；通常与 completed 成对出现 |
| `item/completed` | `userMessage` | `user.message` | 对话 | 已处理 | 从 `item.content[].text` 提取用户文本 |
| `item/started` | `agentMessage` | `message.started` | 对话 | 待补充 | 可选；用于显示“正在生成”，不应计作最终回复 |
| `item/agentMessage/delta` | — | `message.delta` | 对话 | 已处理 | 每个 delta 是同一消息的流式片段，按 itemId 聚合 |
| `item/completed` | `agentMessage` | `message.completed` | 对话 | 已处理 | 从 `item.text` 提取完整回复；与 `run.completed` 不等价 |
| `item/started` | `commandExecution` | `tool.started` | 工具活动 | 已处理 | 展示 command/cwd/status；命令执行仍受审批策略约束 |
| `item/completed` | `commandExecution` | `tool.completed` + `command.output` | 工具活动/诊断 | 部分处理 | 保存 exit code、aggregated output、command；大输出走 artifact |
| `item/started` | `fileChange` | `tool.started` | 工具活动 | 待补充 | 展示受影响路径，不直接展示原始 diff |
| `item/completed` | `fileChange` | `file.changed` | 工具活动 | 待补充 | 脱敏后保存路径和摘要；文件内容需 artifact/边界检查 |
| `item/started` / `item/completed` | `reasoning` | `diagnostic.reasoning` | 诊断 | 待补充 | 仅保存生命周期和安全摘要，不展示/持久化隐藏推理正文 |
| `item/started` / `item/completed` | `plan`、`context` 等未来类型 | `unknown` 或 `diagnostic.item` | 诊断 | 待补充 | 保留原始事件，等待 schema 明确后再提升为产品事件 |

## 4. 用量、集成与运行环境事件

| 原生事件 | Workbench 事件 | 页面区域 | 当前状态 | 处理说明 |
|---|---|---|---|---|
| `thread/tokenUsage/updated` | `usage.updated` | 用量/审计 | 待补充 | 映射 input/output/cached/reasoning tokens；敏感字段继续脱敏 |
| `account/rateLimits/updated` | `diagnostic.rate_limit` | 诊断/配置 | 待补充 | 展示剩余额度和重置时间；不得把账户标识写入普通回复 |
| `mcpServer/startupStatus/updated` | `diagnostic.integration` | 诊断 | 待补充 | 展示 MCP 名称和 ready/starting/failed；错误可关联当前 turn |
| `remoteControl/status/changed` | `diagnostic.integration` | 诊断 | 待补充 | 展示 remote-control 是否启用；不影响本地 run 终态 |
| `hook/started` | `diagnostic.hook` | 诊断 | 待补充 | 记录 hook 名称、scope、handler，不保存完整路径中的敏感信息 |
| `hook/completed` | `diagnostic.hook` | 诊断 | 待补充 | 记录 completed/failed、exit code 和安全错误摘要 |
| `diagnostic.stderr` | `diagnostic.stderr` | 诊断 | 已处理 | 与 stdout JSONL 分离；内容继续执行凭据/环境字段脱敏 |
| 非 JSON stdout | `unknown` | 诊断 | 已处理 | 保留 raw，不能触发 fallback 或伪造成功 |

## 5. 原生服务请求（不是普通通知）

| 原生请求 | Workbench 行为 | 当前状态 |
|---|---|---|
| `item/commandExecution/requestApproval` | 创建 `approval.required`，等待一次性 Accept/Decline/Cancel，再回复 JSON-RPC | 已处理 |
| `item/fileChange/requestApproval` | 创建文件变更审批，记录 paths/risk/reason，再回复 JSON-RPC | 已处理 |
| 未在 manifest 中声明的带 id 请求 | 返回 `unsupported_method` JSON-RPC 错误并记录审计错误 | 已处理 |

## 6. 实现优先级

下一步优先补齐：

1. `item/agentMessage/delta` 按 `itemId` 聚合，避免大量 delta 在历史列表中显示成互相独立的消息。
2. `thread/status/changed`、`turn/failed`、`turn/cancelled` 与 Workbench 状态机的严格映射。
3. `thread/tokenUsage/updated`、`account/rateLimits/updated` 的结构化用量与限额展示。
4. MCP、hook、remote-control 事件的诊断分组和安全摘要。
5. 对 `reasoning`、`plan` 等事件继续保持保守降级，直到 manifest/schema 明确字段语义。

## 7. 结束判定

一次用户输入对应一个 Workbench run 和一个原生 turn。一个 turn 可以包含多个 `message.delta`、多个 `item/completed`（例如中间说明和最终回答），但只有：

```text
原生 turn/completed
        +
Workbench state = succeeded / failed / cancelled / interrupted
```

才表示该次输入的完整生命周期已经结束。
