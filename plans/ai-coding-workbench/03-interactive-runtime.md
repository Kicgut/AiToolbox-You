# Phase 3：交互式运行、续接与实时输出

> - 计划版本：2026-07-30 审查修订版
> - 状态：实施中（2026-07-30 审查后重新打开端到端闭环）
> - 依赖：Phase 2 已完成
> - 首版平台：Windows；仅支持单个 FastAPI 进程、单个 runtime worker
> - 网络边界：默认仅监听 `127.0.0.1`，不提供多用户或远程认证
> - 真实模型请求：自动化测试和开发探测默认禁止；P3-10 验收仍需单独一次性授权
> - 第三方写入：只允许由用户明确提交后，官方 Codex/Claude CLI 正常产生新的会话事件
> - 验证映射：`docs/verification-and-boundaries.md` §3.5（RUN-01～RUN-04）
> - 产物约束：`docs/artifact-hygiene.md`

## 1. 目标

让用户在 Workbench 网页中完成一条真正闭环的交互式运行：

1. 选择 Codex 或 Claude、Profile、项目目录、模型、权限和预算。
2. 明确执行 New、Resume 或 Fork。
3. 后端在正确的 Profile 和 cwd 中启动对应官方 CLI/App Server。
4. 页面实时展示消息、工具、命令、文件变化、usage、错误和审批。
5. 用户可以取消正在运行的进程树，或对原生审批请求作出一次性决定。
6. 运行结束后，Workbench 事件、原生 session ID、原生 transcript 和 Phase 2 usage 可以相互追溯。

本阶段的完成标准是“网页到原生 CLI 的端到端行为成立”，不是“数据库表、适配器和 UI 组件分别存在”。

## 2. 非目标与阶段边界

- 不做定时、Cron、misfire、无人值守重试；这些属于 Phase 4。
- 不做跨账号或跨 Profile 物理复制；这些属于 Phase 5。
- 不做多人共享、应用内认证、远程公网部署或 Linux 发布承诺。
- 不默认启用 `danger-full-access`、`bypassPermissions` 或同类危险绕过。
- 不以 PTY/ConPTY 文本抓取作为主事件源。
- 不在自动化测试、页面加载、Profile 探测或服务启动时隐式发送模型请求。
- 不把“原生 CLI 已登录”误当作“允许 Workbench 自动发起请求”。

### 2.1 Phase 3 与 Phase 4 的多 Step 边界

为消除旧计划与架构文档的冲突，Phase 3 v1 固定为：

- 一个 `run` = 一次用户明确提交。
- 一个 Phase 3 `run` = 一个 `run_step` = 一个原生 Turn。
- Resume 表示基于已有 native session 创建一个新的 run，不是重新打开已终结 run。
- Retry 必须创建新的 run，并通过 `retry_of_run_id` / `retry_of_step_id` 关联原失败实体；终态实体不可回写为 running。
- `run_steps` 表继续保留，为 Phase 4 多 Step 自动任务复用，但 Phase 3 不实现批量 prompt、`continue_on_error` 或自动执行下一 Step。

Phase 4 才负责一个 run 内的多 Step 编排、重试策略、延迟、失败后继续和调度恢复。

### 2.2 三类“真实请求授权”必须区分

| 场景 | 授权方式 |
|---|---|
| 自动化测试、开发探测 | 永远使用 fake CLI；默认禁止真实请求 |
| P3-10 项目验收 | 使用本计划的一次性审批 artifact、nonce、次数和预算硬门禁 |
| Phase 3 验收后的日常产品使用 | 用户在 Composer 中查看完整摘要并点击确认，仅授权该次 run |

P3-10 授权不能延续到日常使用；日常一次提交也不能被测试脚本复用。

## 3. 2026-07-30 审查结论

### 3.1 已有基础

- 完整 Python 测试曾达到 `151 passed`，Phase 3 定向测试曾达到 `36 passed`。
- 前端构建和 Python 编译通过。
- 已存在 Phase 3 数据表、Codex/Claude 解析器、事件持久化、Supervisor 辅助类、审批表操作、Composer、运行中心和 WebSocket 骨架。
- Codex `initialize` 已补充必填 `clientInfo`，解决了已观察到的 `Invalid request: missing field clientInfo`。

这些结果保留为回归基线，但不再作为 P3-01～P3-09 端到端完成证明。

### 3.2 必须关闭的结构性缺口

| 严重度 | 当前缺口 | 关闭任务 |
|---|---|---|
| 阻塞 | API runner 无论选择什么工具都进入 Codex 路径，Claude adapter 未接入真实调度 | P3-04、P3-06 |
| 阻塞 | 只执行第一条 Step；旧计划却承诺多 Step，边界不一致 | §2.1、P3-08 |
| 阻塞 | Resume/Fork 没有可靠地从 `session_copy_id` 取得并传入 native session ID | P3-01、P3-08 |
| 阻塞 | Profile 对应的 `CODEX_HOME` / `CLAUDE_CONFIG_DIR`、模型、权限和预算没有完整进入子进程 | P3-02～P3-06 |
| 阻塞 | 取消接口只改数据库状态，没有终止真实进程树 | P3-06 |
| 阻塞 | 审批接口只改数据库，没有向等待中的原生协议请求回送决定 | P3-07 |
| 阻塞 | writer lease、Supervisor、adapter 和 API dispatch 尚未形成一个事务化执行链 | P3-01、P3-06 |
| 阻塞 | App Server 在 Turn 启动后关闭 stdin，无法维持双向审批和 interrupt | P3-02、P3-07 |
| 高 | 状态和终态直接 UPDATE，未统一产生持久化状态事件 | P3-01、P3-05 |
| 高 | WebSocket 在订阅前 replay，存在 replay 与 subscribe 之间丢事件窗口 | P3-05 |
| 高 | process-local broadcaster 只适用于单进程，但旧计划未声明部署限制 | P3-00、P3-05 |
| 高 | Retry 把终态 run 改回 running，违反原状态机的终态不可变规则 | P3-01、P3-08 |
| 高 | `client_request_id` 未绑定请求体哈希，同一 key 携带不同内容时不能识别冲突 | P3-08 |
| 高 | 运行详情仍以原始 JSON 为主，缺少结构化消息、诊断、审计和明确空状态 | P3-09 |
| 高 | 现有测试以组件测试为主，缺少 API runner、浏览器 E2E、真实取消/审批桥闭环 | §14 |
| 中 | 大输出 artifact 的路径、大小、哈希、清理和脱敏规则未定义 | P3-05 |
| 中 | token/金额预算哪些能硬限制、哪些只能事后观察没有区分 | P3-06 |
| 中 | 架构文档仍保留 “Thread 与 native_session_id 未定义” 等过期 TODO | P3-11 |

## 4. 完成度口径

每项任务按以下五级记录，不允许用较低级证据宣称更高级完成：

1. `合同完成`：schema、状态、错误码和边界已经写清楚。
2. `组件完成`：独立模块和 fixture 单测通过。
3. `集成完成`：真实 API + SQLite + fake CLI + WebSocket 闭环通过。
4. `产品完成`：真实浏览器交互和 Windows 子进程监管通过。
5. `真实验收完成`：获得 P3-10 一次性授权后，真实 Codex/Claude 回合通过。

当前整体处于“组件完成，集成闭环未完成”。P3-01～P3-09 只有达到第 4 级，才允许进入 P3-10。

## 5. 实施顺序与硬门禁

1. **P3-00**：冻结范围、真实请求门禁和单进程运行约束。
2. **P3-01**：修正 run/session/turn 身份、状态机和迁移。
3. **P3-06A**：先建立 lifespan-managed Runtime Coordinator，再接 adapter。
4. **P3-02/P3-03/P3-04**：分别接通 Codex App Server、Codex exec、Claude。
5. **P3-05**：统一事件事务、artifact 和无竞态重连。
6. **P3-06B**：接通取消、超时、预算、Job Object 和重启恢复。
7. **P3-07**：接通原生审批双向协议。
8. **P3-08**：冻结 API/Composer/New/Resume/Fork/Retry 合同。
9. **P3-09**：完成运行中心产品交互和浏览器 E2E。
10. **P3-11**：同步架构、验证边界和术语文档。
11. **P3-10**：最后执行受控真实回合验收。

任何前置门禁未通过时，不得用 P3-10 真实请求帮助调试。

## 6. P3-00：执行开关、版本基线与运行拓扑

### 6.1 真实请求硬门禁

- [ ] 测试进程设置 `AI_WORKBENCH_REAL_EXECUTION=0`，且没有该变量时也默认为关闭。
- [ ] 关闭时，`POST /runs` 只能进入显式 fake adapter；尝试选择真实 adapter 返回 `real_execution_disabled`，不得 spawn CLI。
- [ ] P3-10 使用一次性 nonce 解锁；nonce 绑定审批内容哈希、有效期、允许工具、模型、次数和预算，消费一次后失效。
- [ ] 日常产品模式与 P3-10 验收模式使用不同开关，不能混用 nonce。
- [ ] 服务启动、Profile 探测、CLI `--help`、版本探测和 schema 生成不发送 prompt。

### 6.2 协议版本基线

- [ ] 启动时只读记录 Codex/Claude 可执行文件解析结果、CLI 版本、能力和 schema hash，不记录凭据。
- [ ] Codex App Server 合同以当前安装版本生成的非 experimental JSON Schema 为准；完整生成物放入 `.artifacts/tmp/`，测试仓库只保留最小脱敏 fixture 和 manifest。
- [ ] `initialize.params.clientInfo` 作为必填字段测试；客户端信息至少包含 name/title/version。
- [ ] 不把某次本机探测到的方法永久当成所有版本都支持，所有可选动作都由 capability DTO 驱动。
- [ ] Claude 参数以 `claude --help` 的当前输出和 fixture manifest 为准；未知版本保守降级。

2026-07-30 只读基线：Codex CLI `0.144.4`，Claude Code `2.1.200`。该版本号只用于审查证据，不构成固定依赖。

### 6.3 发布拓扑

- [ ] Phase 3 明确只支持一个 FastAPI 进程和一个 Runtime Coordinator。
- [ ] 若检测到多 worker 配置，执行功能拒绝启动并给出 `unsupported_multi_worker_runtime`；只读会话和统计可以继续。
- [ ] WebSocket broadcaster、进程 handle registry 和审批 waiter 都由同一 coordinator 所有。
- [ ] 后续若支持多进程，必须改用数据库 outbox/IPC，不得继续依赖进程内队列。

## 7. P3-01：执行数据模型、身份和状态机

### 7.1 身份定义

| 名称 | 定义 |
|---|---|
| `run_id` | Workbench 一次用户提交的不可变 ID |
| `step_id` | 本阶段与 run 一一对应的原生 Turn 尝试 |
| `session_copy_id` | Phase 1 索引中的某个 transcript 副本 |
| `source_native_session_id` | Resume/Fork 提交时从 source copy 快照出的原生 ID |
| `native_session_id` | 本次操作最终写入或新建的原生 session/thread ID |
| `native_turn_id` | 原生 Turn ID；支持时必须持久化 |
| `physical_session_key` | `tool + profile_root_identity + native_session_id` |

Codex 的 App Server `threadId` 是协议字段；只有通过返回值和 transcript 对照确认后，才能映射为 Workbench `native_session_id`。不得仅因字符串相同就推断等价。

### 7.2 `runs` 必需字段

保留现有字段，并补齐：

```text
updated_at, source_native_session_id, native_thread_id,
dispatch_state, dispatch_committed_at,
runtime_instance_id, lease_generation,
cancel_requested_at, retry_of_run_id, retry_of_step_id,
capabilities_snapshot_json, request_body_hash
```

约束：

- `action/mode` 只保留一个事实字段，值为 `new|resume|fork|retry`。
- New 禁止携带 `session_copy_id`；Resume/Fork 必须携带且必须解析出稳定 native ID。
- `client_request_id` 唯一；同 key + 同 body 返回原 run，同 key + 不同 body 返回 409。
- `config_snapshot_json` 不得包含 token、Cookie、完整环境变量或授权 artifact。
- `retry_of_run_id` 指向终态 run；原 run 永远保持终态。

### 7.3 Run 状态机

```text
queued
  ├── starting
  └── cancelled

starting
  ├── running
  ├── cancel_requested
  ├── failed
  └── interrupted

running
  ├── waiting_approval
  ├── cancel_requested
  ├── succeeded
  ├── failed
  └── interrupted

waiting_approval
  ├── running
  ├── cancel_requested
  ├── failed
  └── interrupted

cancel_requested
  ├── cancelling
  ├── succeeded
  └── interrupted

cancelling
  ├── cancelled
  ├── failed
  └── interrupted
```

规则：

- [ ] 所有转移使用一个 compare-and-set 服务，不允许路由直接执行任意 SQL 状态更新。
- [ ] 每次转移在同一事务中更新 run/step，并插入 `run.status_changed`。
- [ ] `succeeded|failed|cancelled|interrupted` 为不可变终态。
- [ ] cancel 与自然完成竞态按被 coordinator 首先确认的事实决定；已确认 succeeded 后不能覆盖为 cancelled。
- [ ] `cancelled` 只表示进程树已确认退出；无法确认时是 `interrupted`。

### 7.4 writer lease

- [ ] Resume/Fork 在 spawn 前取得 source `physical_session_key` 的 lease。
- [ ] New 在取得 native ID 后，于继续写入前把 provisional ownership 转换为正式 session lease。
- [ ] 获取、heartbeat、审批回复、interrupt 和释放都校验 `run_id + lease_generation`。
- [ ] heartbeat 失败立即停止继续写入，并进入 `interrupted`。
- [ ] 有效 lease 冲突返回 HTTP 409 `session_busy`，且不得创建真实进程。
- [ ] 服务重启后只允许过期 lease 被接管，不自动重放 prompt。

### 7.5 审批与 artifact 表

- [ ] `approval_requests` 对 `(run_id, native_request_id)` 建立唯一约束。
- [ ] 审批状态扩展为 `pending|responding|accepted|declined|cancelled|expired|delivery_failed`。
- [ ] 新增 `run_artifacts`：`id,run_id,step_id,kind,relative_path,sha256,size_bytes,mime_type,redaction_state,created_at,expires_at`。
- [ ] 大输出存放在 `data/ai_workbench/run-artifacts/<run_id>/`；`.artifacts/` 只用于工程验证，不能作为产品运行时事实源。

## 8. P3-02：Codex App Server

### 8.1 协议客户端

- [ ] 使用 argv 启动 `codex app-server --stdio`，绑定正确 cwd、Profile 环境和 Windows Job Object。
- [ ] 完整实现双向 request/response/notification dispatcher：
  - client request：有 id，等待匹配 response；
  - client notification：无 id；
  - server notification：无 id，归一化为事件；
  - server request：有 id，必须交给审批/交互 handler 并回送 response。
- [ ] `initialize` 必含 `clientInfo`，随后发送 `initialized`。
- [ ] 只使用当前 schema 宣告的方法；experimental schema 默认不生成、不启用。
- [ ] 单条 malformed/unknown notification 保存为 `unknown`，不能破坏其他 request id 的同步。
- [ ] stderr 独立读取为 `diagnostic.stderr`。

当前安装版本生成的 schema明确包含 `thread/start`、`thread/resume`、`thread/fork`、`turn/start`，并把命令/文件审批建模为 server request。计划不再使用一个未经 schema 证明的通用 `approval/resolve` 作为唯一审批合同。

### 8.2 New/Resume/Fork

- [ ] New 调用 thread start，持久化返回 thread ID，再启动 turn。
- [ ] Resume 必须使用 `source_native_session_id`，禁止隐式“最近会话”。
- [ ] Fork 必须使用 source thread ID，并把返回的新 thread ID 作为结果 session。
- [ ] model、cwd、sandbox、approval policy 必须来自服务端校验后的快照。
- [ ] `turn/start` 成功提交后立刻把 `dispatch_state` 置为 `submitted`。
- [ ] stdin 在 Turn 终结、interrupt/approval 完成和进程退出前保持可写；不得在 `turn/start` 后立即关闭。

### 8.3 Fallback 原子性

`dispatch_state`：

```text
not_started → submitting → submitted → completed
                         └→ unknown
```

- [ ] 只有 `not_started` 或可证明尚未提交时允许切换到 exec。
- [ ] spawn 失败、initialize 超时、协议版本不兼容、必需 capability 缺失可以 fallback。
- [ ] prompt 拒绝、审批拒绝、预算超限和已提交后的连接故障不能 fallback。
- [ ] `submitted|unknown` 后失败必须进入 `failed`/`interrupted`，由用户显式创建 Retry run。
- [ ] fallback 决策和原因作为 `run.execution_path_selected` 事件持久化。

## 9. P3-03：Codex exec fallback

- [ ] New 使用受支持的 `codex exec --json` 路径；Resume 使用明确 native session ID。
- [ ] fork、原生审批或其他不支持能力必须在 capability DTO 中为 false，API 直接拒绝，不静默改成 New/Resume。
- [ ] prompt 通过 stdin 或协议字段传递；`shell=False`，用户内容不参与命令字符串拼接。
- [ ] stdout 按行实时读取，不使用等待进程结束后才返回全部内容的 `communicate()` 作为主流式路径。
- [ ] stderr 独立读取；未知 JSON 和非 JSON 行保留 raw。
- [ ] session/turn ID 一出现就持久化，不等到进程退出。
- [ ] 进程 handle、cancel、timeout 和 Job Object 统一交给 Runtime Coordinator，不在 adapter 内自行 `kill()`。
- [ ] exec 与 App Server 的语义等价事件具有相同 payload 合同；能力差异显式展示。

## 10. P3-04：Claude adapter

- [ ] API 根据 `tool=claude` 真正进入 Claude adapter，禁止复用 Codex runner。
- [ ] 每个 Phase 3 run 使用一个短生命周期 Claude 进程。
- [ ] New、`--resume <id>`、`--fork-session` 使用明确动作；`--continue` 不作为产品默认能力。
- [ ] 使用 `--output-format stream-json --include-partial-messages`，并按当前 CLI 能力决定是否加入 hook event。
- [ ] model、permission mode、allowed/disallowed tools、max budget 从已校验快照映射到 argv。
- [ ] prompt 优先通过当前版本支持的 stdin/text input；若只能作为单个 argv 参数，必须保持 `shell=False` 并在诊断中标记 process-list 可见性风险。
- [ ] 从 init/result 事件提取 native session ID，Resume 必须对照请求 ID，Fork 必须得到新 ID。
- [ ] 如果当前 stream-json 路径无法暂停并接收审批回复，声明 `approval_bridge=false`，UI 不展示虚假审批能力。
- [ ] stdout/stderr、取消、超时和 Job Object 复用统一 Coordinator。

## 11. P3-05：统一事件、持久化、重连与大输出

### 11.1 事件合同

统一 envelope：

```json
{
  "event_id": "uuid",
  "run_id": "uuid",
  "step_id": "uuid",
  "session_id": "native-or-workbench-session-id",
  "sequence_no": 42,
  "timestamp": "UTC ISO-8601",
  "type": "message.delta",
  "payload": {},
  "source_tool": "codex",
  "source_event_type": "item/agentMessage/delta",
  "source_version": "cli-or-schema-version",
  "quality": "exact|estimated|unavailable",
  "raw_ref": null
}
```

稳定事件集合：

```text
run.queued
run.started
run.status_changed
run.execution_path_selected
turn.started
user.message
message.delta
message.completed
reasoning.summary
tool.started
tool.output
tool.completed
command.output
file.changed
approval.required
approval.responding
approval.resolved
usage.updated
diagnostic.stderr
stream.gap
run.completed
run.failed
run.cancelled
unknown
```

- [ ] 原生 Turn completed 先映射为 Turn 事实，再由 Coordinator 决定 run 终态；adapter 不自行把任意 completed 记录解释成整个 run 成功。
- [ ] 状态事件、业务数据和 cursor 在同一 SQLite 事务提交，提交后才广播。
- [ ] `last_broadcast_sequence_no` 只在实际成功入队/发送后更新，不能冒充客户端已接收。
- [ ] raw payload 有大小上限和密钥模式脱敏；不得记录环境变量、token 或 Cookie。

### 11.2 无竞态 WebSocket 握手

服务端固定流程：

1. 校验 run 和 cursor。
2. 先订阅该 run 的有界实时队列。
3. 在数据库快照中读取 `cursor < sequence_no <= high_watermark`。
4. 发送 `hello`：run snapshot、`high_watermark`、capabilities、connection ID。
5. 分页发送 replay。
6. drain 实时队列，仅发送 `sequence_no > high_watermark` 的事件并按序去重。
7. 发现 sequence gap 时发送 `stream.gap`，客户端从最后连续 cursor 请求 resync。

- [ ] replay 与 subscribe 之间不存在丢事件窗口。
- [ ] 客户端以 `(run_id, sequence_no)` 去重，不以数组位置或 event 到达时间排序。
- [ ] REST/WS 单页最多返回固定数量事件；禁止每秒从 0 重新加载完整历史。
- [ ] 慢客户端不会阻塞 stdout reader；关键事件不丢，delta 可合并并通过持久化 replay 恢复。
- [ ] 关闭详情、切换 run、页面卸载时释放 socket、poll、queue 和监听器。

### 11.3 大输出与保留

- [ ] 超过事件内联阈值的 stdout/diff/raw 写 `run_artifacts`，事件只保存摘要、hash 和引用。
- [ ] artifact 路径必须位于 `data/ai_workbench/run-artifacts/`，使用相对路径并校验路径穿越。
- [ ] 默认保留期、用户清理动作和数据库引用清理顺序明确。
- [ ] 复制诊断默认脱敏，并显示将复制的字段范围。

### 11.4 Phase 2 usage 去重

- [ ] live usage 和 transcript usage 用 `tool + profile identity + native_session_id + native_turn_id/request_id` 精确关联。
- [ ] 先 live 后 scan、先 scan 后 live 两种顺序最终只有一个 primary。
- [ ] 弱匹配只标冲突，不自动合并。
- [ ] 预算 UI 标明 exact/estimated/unavailable，缺失不得显示为 0。

## 12. P3-06：Runtime Coordinator、进程监管、取消和预算

### 12.1 生命周期托管

- [ ] Runtime Coordinator 在 FastAPI lifespan 启动和停止，不使用路由内 daemon thread 承担事实执行。
- [ ] `POST /runs` 只完成校验、落库和 enqueue，返回 HTTP 202；worker 事务化 claim 后才 spawn。
- [ ] coordinator registry 保存 `run_id → adapter/session/process/job/lease/cancel token/approval waiter`。
- [ ] shutdown 先停止接收新 run，再 interrupt/清理受管进程，最后把无法确认的 run 标记 interrupted。
- [ ] 服务启动时 reconcile 非终态 run 和过期 lease，绝不自动重发 prompt。

### 12.2 Profile 与环境

- [ ] 从 `tool_profiles` 解析并规范化配置根目录、session 根目录和 executable。
- [ ] Codex 只设置该 Profile 所需的 `CODEX_HOME`；Claude 只设置 `CLAUDE_CONFIG_DIR` 或当前版本确认的等价配置。
- [ ] 环境采用 allowlist + 必需系统变量继承；快照只保存变量名和非敏感摘要，不保存值。
- [ ] cwd 必须是存在的规范化目录，并位于已登记项目根或用户当次明确确认的目录。
- [ ] Windows 路径比较使用大小写归一和 `Path.resolve()` 后的边界检查；拒绝路径穿越和不可访问目录。

### 12.3 取消与超时

- [ ] 取消 API 只发出幂等 cancel request；coordinator 负责原生 interrupt、grace period 和 Job Object 强杀。
- [ ] App Server 优先调用当前 schema 支持的 turn interrupt，再走进程级清理。
- [ ] exec/Claude 先温和中断；超时后关闭 Job Object，确认父子进程全部退出。
- [ ] 只有清理确认后状态才是 cancelled/failed(timeout)；未知为 interrupted。
- [ ] 重复取消只触发一次终止流程。
- [ ] cancel 与自然退出竞态有真实子进程测试，不能只测内存状态类。

### 12.4 预算语义

| 限制 | Phase 3 强度 |
|---|---|
| 单 run 一个 Turn | 硬限制 |
| 最大运行时间 | Workbench 硬限制 |
| 允许工具/权限模式 | CLI 能力支持时硬限制；否则拒绝运行 |
| 精确模型/禁止 fallback | CLI 能力支持时硬限制；无法保证时拒绝 P3-10 |
| Claude `max-budget-usd` | CLI 原生硬限制 |
| Codex token/金额上限 | 无原生支持时只监测，不得标为硬限制 |
| 最大输出 token | 无原生支持时只监测；通过时长/Turn 和取消兜底 |
| 累计费用 | usage 到达后的软中止和验收上限 |

- [ ] API、数据库和 UI 均标注每个限制是 `hard|provider_enforced|observed_only|unsupported`。
- [ ] 不支持的硬要求必须在 spawn 前拒绝，不能静默降级。

## 13. P3-07：原生审批桥

### 13.1 双向流程

```text
server request
  → normalize + persist approval.required
  → run waiting_approval
  → UI decision
  → DB CAS pending→responding
  → validate lease + native request id
  → send native response
  → protocol confirms delivery
  → accepted/declined/cancelled + approval.resolved
  → run running 或终止
```

- [ ] App Server server request 的 id、方法名和 params 原样保留为受限 raw，响应使用当前 schema 对应的 response 类型。
- [ ] Phase 3 只提供“一次接受/拒绝/取消”；不提供 session 级永久自动批准。
- [ ] `decided_by` 固定为本地实例用户标识，不信任客户端任意字符串。
- [ ] 两个并发决定只有一个能进入 `responding`。
- [ ] native 发送失败进入 `delivery_failed`，不得显示为已接受。
- [ ] 浏览器断开不改变 pending 状态；重连后恢复。
- [ ] 服务重启时等待审批的 native 连接不可确认，run 进入 interrupted。
- [ ] approval bridge=false 时 API 返回 `capability_not_supported`，UI 隐藏操作。

### 13.2 安全展示

- [ ] UI 显示 operation、argv 数组、cwd、受影响路径、网络目标、risk、reason、有效期和一次性范围。
- [ ] 命令使用 argv 逐项展示，不拼接成可复制执行的 shell 字符串。
- [ ] 文件 diff/命令输出先脱敏再展示。
- [ ] 未知操作按 high/unknown 处理，不能默认接受。

## 14. P3-08：API、Composer 与会话动作

### 14.0 网页新建 Codex 会话专项门禁

用户此前在 `http://127.0.0.1:8899/sessions` 实际观察到过以下问题：

- 点击“创建 Run”曾返回 `Method Not Allowed`。
- 创建后只增加一条黑色状态条，无法打开详情。
- 状态停留在 starting/running，页面没有实时输出。
- 刷新后才变成 failed，错误曾包括 App Server `initialize` 缺少 `clientInfo`。
- 条目点击、关闭和取消没有形成清晰可验证的行为。

这些问题全部属于 Phase 3，不得延期到 Phase 4。必须建立一条独立的端到端验收用例：

```text
/sessions Composer
  → POST /api/ai-workbench/runs
  → 202 queued + run_id
  → Runtime Coordinator claim
  → 正确 Codex Profile/cwd
  → App Server handshake（含 clientInfo）
  → thread/start
  → 回填 native thread/session ID
  → turn/start
  → persist event
  → WebSocket replay/live
  → 可点击 Run 详情
  → succeeded/failed/cancelled 明确终态
  → 原生 transcript 可追溯
```

专项断言：

- [ ] `/sessions` 和 `/` 上的 Composer 均只调用 API 路由，不被 SPA fallback 吞掉；POST 不再出现 405。
- [ ] 单击提交后立即出现带 run ID 的可点击条目，重复点击不会创建第二个 run。
- [ ] 条目在 queued、starting、running、waiting approval、cancelling 和终态之间变化时无需整页刷新。
- [ ] starting 必须对应真实 worker claim/握手；不能先写 running 再尝试 spawn。
- [ ] App Server initialize payload 通过当前 schema 验证，`clientInfo` 缺失有固定回归测试。
- [ ] thread/start 返回后立即显示并持久化 native session/thread ID。
- [ ] turn 事件到达后详情至少显示 user message、assistant delta/completed、diagnostic 和 terminal event。
- [ ] 点击条目一定打开详情；Close 仅关闭详情；Cancel 终止真实受管进程树。
- [ ] 无输出、连接断开、握手失败和协议错误分别有可读空状态/错误，不显示不可交互黑条。
- [ ] 页面刷新后通过 cursor 恢复同一 run，不把 running 错判为 failed，也不重复事件。
- [ ] fake Codex E2E 必须覆盖成功、握手失败、运行中取消和浏览器刷新四个场景。

### 14.1 提交合同

```json
{
  "action": "new|resume|fork",
  "tool": "codex|claude",
  "profile_id": "profile-id",
  "session_copy_id": "required-for-resume-or-fork",
  "cwd": "E:\\repo",
  "model": "exact-or-null",
  "permission_policy": {
    "sandbox": "read_only",
    "approval": "on_request",
    "allowed_tools": [],
    "disallowed_tools": []
  },
  "budget_policy": {
    "max_turns": 1,
    "max_duration_seconds": 180,
    "max_total_tokens_observed": 20000,
    "max_cost_minor_observed": null,
    "allow_model_fallback": false
  },
  "prompt": "one non-empty prompt",
  "client_request_id": "uuid"
}
```

不再同时接收可矛盾的 `action` 与 `mode`，也不在 Phase 3 接收 `prompts[]`。

### 14.2 服务端校验

- [ ] New 禁止 `session_copy_id`；Resume/Fork 必须提供。
- [ ] source copy 必须属于所选 tool/profile，且 native ID 和 transcript 状态可用。
- [ ] action 必须被 adapter capability 支持。
- [ ] Profile 必须 enabled，CLI 必须可执行，cwd 必须通过规范化和范围确认。
- [ ] model、权限和预算必须符合 capability；禁止前端声称支持后端无法执行。
- [ ] prompt 非空、有大小上限，日志/错误不得回显未脱敏全文。
- [ ] `client_request_id + request_body_hash` 实现幂等。
- [ ] real execution gate 在 enqueue 前检查。

### 14.3 API 语义

| API | 成功语义 | 关键错误 |
|---|---|---|
| `POST /runs` | 202 queued；幂等命中返回原 run | 400 invalid、409 idempotency/session busy、423 gate disabled |
| `GET /runs` | cursor pagination + filters | 400 invalid cursor |
| `GET /runs/{id}` | snapshot，不默认返回无限事件 | 404 |
| `GET /runs/{id}/events` | `after_sequence + limit` | 409 resync required |
| `WS /runs/{id}/stream` | hello/replay/live/gap | 4404、4409 |
| `POST /runs/{id}/cancel` | 202 cancel_requested | 409 terminal |
| `POST /runs/{id}/retry` | 201 新 run | 409 source not retryable |
| `POST /approvals/{id}/decision` | 202 responding | 409 stale/conflict |

- [ ] 所有错误返回 `{code,message,details,retryable}`，UI 不直接显示 Python dict/repr。
- [ ] Retry 返回新的 run ID，不修改原终态 run。

### 14.4 Composer

- [ ] `/sessions` 选择已有 session 时显示 Resume/Fork，并自动锁定其 tool/profile/native identity。
- [ ] 全局 New 不要求先选择已有 session。
- [ ] capability 不支持的 action 隐藏或禁用，并解释原因。
- [ ] 提交前显示 tool/profile/cwd/model、权限、预算强度和 prompt 摘要确认。
- [ ] 创建后立即打开可点击的 run 详情，starting/queued 有明确等待状态。
- [ ] 禁止双击重复提交；页面刷新后可通过 idempotency key 找回原 run。

## 15. P3-09：运行中心与浏览器体验

### 15.1 列表

- [ ] 分组展示 queued/active/waiting approval/recent terminal。
- [ ] 每条 run 是可聚焦、可点击的真实 button/link，显示 action、tool、profile、cwd basename、model、state、duration、pending approval 和最新事件。
- [ ] starting 超过阈值显示“仍在握手”及诊断入口，不只显示黑色条。
- [ ] failed 显示结构化 `failure_code` 和用户可读 message。

### 15.2 详情

详情至少有四个独立区域：

1. 对话时间线：user、assistant、reasoning summary。
2. 工具活动：tool、command、file diff、审批。
3. 诊断：stderr、unknown/raw、execution path、CLI/schema version。
4. 审计摘要：run/step/session mapping、permission、budget、usage、artifact。

- [ ] 不再只用 `JSON.stringify(payload)` 作为主 UI。
- [ ] 无事件时区分 queued、握手中、连接断开、运行无输出、已失败。
- [ ] failed/cancelled/interrupted/waiting_approval/offline 视觉和文案不同。
- [ ] 自动滚动只在用户位于底部时开启；用户上滚后暂停并显示“有新事件”。
- [ ] 大列表使用虚拟化，但不得永远只保留最后 200 条而无历史访问入口。
- [ ] Close 只关闭详情和连接，不取消 run；Cancel 有二次确认和 cancelling 反馈。
- [ ] 页面刷新、切换 run、网络断开/恢复均通过浏览器 E2E 验证。

### 15.3 可访问性

- [ ] 状态不仅靠颜色区分。
- [ ] run 行、审批按钮和 tabs 支持键盘和可见 focus。
- [ ] `aria-live` 只播报关键状态，不逐 token 播报 delta。
- [ ] 错误与审批焦点管理不会把用户困在滚动流中。

## 16. P3-11：跨文档同步

P3-01～P3-09 产品闭环完成后、P3-10 前：

- [ ] 更新 `docs/ai-coding-workbench-architecture.md`：删除 Thread 映射未定义 TODO，写入 run=single-turn、单进程 runtime、无竞态 WebSocket 和审批双向合同。
- [ ] 更新 `docs/verification-and-boundaries.md` RUN-01～RUN-03 的“当前空白”描述和实际测试引用。
- [ ] 更新 `CONTEXT.md` 中 Run、Step、Turn、Thread、native session、session copy 的定义。
- [ ] 更新计划索引状态；不得提前把 Phase 3 标为待验收或已完成。
- [ ] 所有验证临时文件遵循 `.artifacts/tmp/` 和 `.artifacts/verification/` 约束。

## 17. P3-10：受控真实回合验收

### 17.1 前置条件

只有以下条件全部满足才请求一次性授权：

- [ ] P3-00～P3-09、P3-11 全部达到“产品完成”。
- [ ] 完整测试、Phase 3 测试、浏览器 E2E、前端 build、Python compile 全部通过。
- [ ] fake CLI 已证明 New/Resume/Fork、取消、审批、断线补发和 transcript reconciliation。
- [ ] 真实执行默认门禁和 nonce 消费测试通过。
- [ ] 当前 CLI 版本、能力、精确模型、Profile 和 cwd 已只读探测。
- [ ] 没有待解释的 root-level 临时产物或真实请求日志。

### 17.2 必做真实场景

1. Codex New 一次。
2. Codex 对同一 native session Resume 一次。
3. Claude New 一次。
4. Claude 对同一 native session Resume 一次。
5. 在预算允许时选择一个额外安全场景：
   - 取消：在 `turn.started` 后取消，并确认原生进程树退出；或
   - 审批：只读命令审批一次，例如在受信项目中请求执行 `git status --short`，只允许“一次接受”，不得写文件。
6. 对每个 run 比较 Workbench event 与原生 transcript。

Fork 必须先由 fake CLI 和无费用协议路径证明；若真实 Fork 会产生额外模型回合，必须在审批单中单独列出，不能包含在上述四回合授权里。

### 17.3 一次性审批 artifact

审批文件放入：

```text
.artifacts/verification/p3-10/<nonce>/approval.json
```

必须包含：

```json
{
  "nonce": "single-use-uuid",
  "valid_from": "UTC",
  "expires_at": "UTC",
  "approval_text_hash": "sha256",
  "codex": {
    "profile_id": "non-sensitive-id",
    "provider": "name",
    "model": "exact-model",
    "max_successful_turns": 2,
    "max_duration_seconds_per_turn": 180,
    "max_cost_minor_observed": null
  },
  "claude": {
    "profile_id": "non-sensitive-id",
    "provider": "name",
    "model": "exact-model",
    "max_successful_turns": 2,
    "max_duration_seconds_per_turn": 180,
    "max_cost_minor_or_native_budget": null
  },
  "cwd": "exact-path",
  "permission_policy": {},
  "prompt_hashes": [],
  "extra_cancel_or_approval_case": {},
  "allow_retry": false,
  "allow_model_fallback": false,
  "retention_policy": "keep-or-delete",
  "approved_by": "user-confirmed-local-owner",
  "approved_at": "UTC"
}
```

审批正文还必须明确：

- 完整 prompt 原文或可核对的 prompt hash。
- 允许和禁止的工具。
- 是否允许命令、网络和文件写入。
- 每工具和全局累计预算。
- 自动重试次数，默认 0。
- 中止条件：模型/Profile/cwd 不一致、usage 不可见、重复提交、出现未批准工具、超时、预算达到上限、用户撤销。

缺字段、过期、hash 不匹配或 nonce 已消费时，真实执行必须在 spawn 前失败。

### 17.4 transcript 对照表

每个真实 run 记录：

| 字段 | Workbench | 原生 transcript/CLI | 结果 |
|---|---|---|---|
| tool/profile/model/cwd |  |  |  |
| run ID / native session ID / thread ID |  |  |  |
| native turn ID |  |  |  |
| user prompt hash |  |  |  |
| assistant completed |  |  |  |
| tool/command/file/approval |  |  |  |
| usage token 分项 |  |  |  |
| terminal state / exit code |  |  |  |
| transcript path、mtime、hash |  |  |  |

只有关键 identity、事件顺序、终态和 usage 均可解释时才通过。模型回复内容质量不属于验收目标。

## 18. 测试矩阵

### 18.1 自动化层级

| 层级 | 必测内容 | 是否可调用真实模型 |
|---|---|---|
| 单元 | 状态机、parser、capability、预算映射、错误码 | 否 |
| SQLite 集成 | CAS、lease、sequence、usage 去重、迁移 | 否 |
| API 集成 | Compose→queue→fake CLI→events→terminal | 否 |
| WebSocket 集成 | subscribe-before-replay、gap、慢消费者、断线 | 否 |
| Windows 进程 | Job Object、父子树、cancel/timeout、重启 | 否 |
| 浏览器 E2E | New/Resume/Fork UI、详情、取消、审批、刷新 | 否，使用 fake CLI |
| P3-10 | 四个固定真实回合和一个可选安全场景 | 是，单次授权 |

### 18.2 必须使用真实无害子进程的场景

- 父进程派生 child 后 cancel/timeout，父子都退出。
- stdout/stderr 交错、malformed JSON、unknown event、长行。
- 高频 delta + 慢 WebSocket，不阻塞生产者。
- cancel 与自然退出的确定性竞态。
- Supervisor 重启后旧 run 变 interrupted，prompt 不重放。
- 两个 Resume 同一 session，只有一个取得 lease。
- 审批 pending 时浏览器断开，原生 fixture 继续等待。
- 同一审批并发回复，只有一个 native response。
- App Server 在 turn 提交前/后分别失败，fallback 只发生在提交前。
- REST replay 与 WS live 交界处持续输出，不丢不重。

### 18.3 必须新增的测试入口

```powershell
python -m pytest -q tests/ai_workbench/phase3
python -m pytest -q
python -m compileall -q app

Set-Location frontend
npm run build
npm run test:e2e:phase3
```

若尚无 `test:e2e:phase3`，P3-09 必须先建立基于 fake CLI 的浏览器测试入口。所有 basetemp、截图、trace 和报告分别写入 `.artifacts/tmp/` 或 `.artifacts/verification/`。

## 19. 验收清单

### 19.1 数据与并发

- [ ] 状态转移和状态事件原子提交。
- [ ] 终态不可变，Retry 创建新 run。
- [ ] writer lease 真正包围 spawn、approval、interrupt 和 cleanup。
- [ ] 同 session 并发 loser 在 spawn 前返回 409。

### 19.2 工具执行

- [ ] Codex App Server New/Resume/Fork fake 集成通过。
- [ ] Codex exec New/Resume 和 capability 降级通过。
- [ ] Claude New/Resume/Fork fake 集成通过。
- [ ] tool/profile/cwd/model/permission/budget 均进入真实 argv/protocol 快照。

### 19.3 流、取消与审批

- [ ] persist-before-broadcast 和 subscribe-before-replay 成立。
- [ ] 浏览器刷新不丢事件、不重复、不每秒重载全历史。
- [ ] Cancel 确实终止 Windows 进程树。
- [ ] 审批决定确实送达原生 waiter，发送失败不会假装成功。

### 19.4 产品体验

- [ ] 网页新建 Codex 专项门禁全部通过，不再出现 405、空黑条、不可点击或刷新后才暴露失败。
- [ ] run 条目可点击并打开详情。
- [ ] queued/starting/running/waiting/cancelling/terminal 有明确反馈。
- [ ] 结构化时间线、工具、诊断、审计视图可用。
- [ ] Close、Cancel、Retry 语义互不混淆。

### 19.5 最终退出标准

- [ ] P3-00～P3-09、P3-11 全部达到产品完成。
- [ ] 所有自动化、真实无害子进程和浏览器 E2E 通过。
- [ ] P3-10 获得单独授权并在预算内通过。
- [ ] 原生 transcript 可看到新建/续接会话，Workbench 映射可追溯。
- [ ] 未经批准的危险操作没有执行。
- [ ] 回滚和已知限制已记录。

满足以上全部条件后，状态改为 `待验收`；只有用户确认后才能改为 `已完成`。

## 20. 风险与回滚

| 风险 | 控制 |
|---|---|
| 协议版本变化 | 本机 schema/`--help` 探测、版本化 fixture、capability 降级 |
| 重复模型回合 | dispatch barrier、idempotency body hash、submitted 后禁止 fallback |
| 取消残留进程 | lifespan coordinator、Job Object、两阶段终止、真实 child fixture |
| 审批误报成功 | pending→responding→native ack→resolved 两阶段状态 |
| WebSocket 丢事件 | SQLite 事实源、先订阅后 replay、sequence gap 恢复 |
| prompt/输出泄密 | shell=False、限制 raw、脱敏、artifact 路径隔离 |
| 预算假安全 | hard/provider/observed/unsupported 四级标识 |
| 多 worker 状态分裂 | Phase 3 明确拒绝多 worker 执行 |

回滚方式：

1. 关闭 real execution gate 和运行入口。
2. 停止接收新 run，清理 coordinator 中所有受管进程。
3. 将无法确认的非终态 run 标记 interrupted。
4. 保留 Phase 1 只读会话中心和 Phase 2 统计中心。
5. 不删除或改写官方 CLI 已产生的原生 session；只停止 Workbench 后续写入。

## 21. 执行证据登记

证据只登记当前有效结论，失败和被替代结果不与最新结果混写。

| 日期 | 范围 | 结果 | 结论 |
|---|---|---|---|
| 2026-07-27 | 完整 pytest | 151 passed | 回归基线 |
| 2026-07-27 | Phase 3 pytest | 36 passed | 组件基线，不是端到端完成 |
| 2026-07-27 | frontend build / compileall | 通过 | 构建基线 |
| 2026-07-30 | 代码与计划对照审查 | 发现 §3.2 所列闭环缺口 | P3-01～P3-09 重新按产品完成口径验收 |
| 2026-07-30 | 本机只读 CLI 探测 | Codex 0.144.4；Claude 2.1.200；Codex schema 证实 `clientInfo` 必填和审批 server request | 更新协议设计，不发送 prompt |

后续每轮证据必须写明：commit/worktree 状态、命令、测试数量、fake/real、CLI 版本、cwd、是否产生第三方写入、产物位置和未覆盖项。

## 22. 审查记录

- 2026-07-23：确认 P3-10 使用“日常账号 + 一次性硬范围”，精确模型、回合、预算、重试和 fallback 必须逐字段批准。
- 2026-07-27：批准 Phase 3 实施；确认 Claude v1 使用每 Turn 一个短生命周期进程和显式 resume。
- 2026-07-27：完成第一轮组件实现与测试，形成 151/36/build/compile 基线；真实回合未授权。
- 2026-07-30：重新审查计划与当前代码。确认此前“P3-01～P3-09 已完成”的表述过宽：组件存在，但 API dispatch、Profile 环境、Claude 路由、lease、真实取消、双向审批、WebSocket 无竞态恢复和浏览器 E2E 尚未形成闭环。计划状态改为 `实施中`，新增 P3-00/P3-11 门禁，明确 run=single-turn、终态不可变、Retry 新建实体、单进程 runtime 和 P3-10 前置条件。
