# Phase 3：交互式运行、续接与实时输出

> 状态：待审查  
> 依赖：Phase 2 已完成  
> 允许真实模型请求：仅在验收末期单独批准  
> 允许修改第三方数据：仅由官方 CLI/App Server 正常产生新的会话事件

## 目标

允许用户从统一会话中心新建、续接或 Fork Codex/Claude 会话，提交单条或多条独立 prompt，并在前端实时查看结构化消息、工具调用、命令输出、文件变化、usage、错误和审批。

## 非目标

- 不做定时/Cron。
- 不做跨账号物理复制。
- 不默认提供危险权限。
- 不以 PTY 文本抓取作为主事件源。
- 不在未确认预算时运行真实模型测试。

## 交付物

- `CodexAdapter`、`ClaudeAdapter` 正式执行实现。
- Execution Supervisor、运行状态机和 writer lease。
- WebSocket 实时事件与断线补发。
- 会话底部 composer、运行中心和审批 UI。
- 新建、resume、fork、多 Step 手动执行。

## 任务

### P3-01：执行数据模型

- [ ] 创建 runs、run_steps、approval_requests、event stream cursor。
- [ ] 定义 starting/running/waiting_approval/succeeded/failed/cancelled/interrupted。
- [ ] 每个物理 session 实现单 writer lease。
- [ ] 保存 tool/profile/project/model/permission/budget 快照。

### P3-02：Codex App Server 客户端

- [ ] stdio 子进程、initialize handshake、request id 和 notification dispatcher。
- [ ] 白名单使用 `thread/start/read/resume/fork`、`turn/start/interrupt` 和审批方法。
- [ ] 处理消息 delta、tool、command、file change、usage、turn completed。
- [ ] 未知 notification 保存 raw，不中断连接。
- [ ] app-server 缺失或协议失败时切换 exec fallback。
- [ ] 不启用 experimental API，除非后续任务逐项批准。

### P3-03：Codex exec fallback

- [ ] `codex exec --json` 新会话。
- [ ] `codex exec resume <id> --json` 续接。
- [ ] prompt 经 stdin 或独立 argv 元素传递。
- [ ] 解析 JSONL 和 stderr，保留 session/thread id。
- [ ] 明确 fallback 不支持的审批或 fork 能力，并反映到 UI。

### P3-04：Claude adapter

- [ ] `claude -p --output-format stream-json --include-partial-messages`。
- [ ] `--resume`、`--continue`、`--fork-session` 和显式 session id。
- [ ] 评估单 Step 单进程与 `--input-format stream-json` 常驻进程，首版选择更可恢复方案。
- [ ] 解析 init、partial、assistant、tool、result、hook 和 error。
- [ ] 支持 max budget、permission mode、allowed/disallowed tools 参数。

### P3-05：统一事件与持久化

- [ ] 将两个 adapter 映射到 Phase 0 event contract。
- [ ] stdout JSON 增量解析，stderr 独立 diagnostic。
- [ ] 每个 run 严格单调 sequence。
- [ ] 先持久化再广播，避免断线丢事件。
- [ ] usage 同步到 Phase 2 observation 模型。

### P3-06：Execution Supervisor

- [ ] argv spawn、cwd、environment allowlist 和 stdin 生命周期。
- [ ] Windows process group/Job Object；Linux 若在首发范围则实现 process group。
- [ ] 温和取消、超时强杀、子进程树清理。
- [ ] 有限内存 ring buffer、落盘 artifact 和 WebSocket 背压。
- [ ] 服务重启时把失联运行标为 interrupted。

### P3-07：审批桥

- [ ] 将 Codex/Claude 原生审批规范化。
- [ ] 前端显示操作类型、目标、风险和超时。
- [ ] 支持 accept/decline/cancel，并记录决策。
- [ ] 不在线时保持 waiting_approval，不自动危险批准。

### P3-08：会话 composer

- [ ] 从 session copy 选择原 profile 续接。
- [ ] profile/model/permission selector 只显示 adapter 声明的能力。
- [ ] 提供 Resume、Fork、New 三种明确动作。
- [ ] 多句 prompt 保存为独立 Step，逐 Turn 等待完成。
- [ ] 支持停止后续 Step、单步重试和 continue-on-error。

### P3-09：运行中心

- [ ] 当前、等待审批、最近完成分组。
- [ ] 结构化流、raw stdout、stderr 视图。
- [ ] 浏览器刷新后按 sequence 补发。
- [ ] 取消、重试、复制诊断和跳回会话。
- [ ] 大输出虚拟化和自动滚动暂停。

### P3-10：受控真实回合验收

执行前用户必须确认：账号/profile、模型、工作目录、prompt、权限、最大预算。

- [ ] Codex 新建一次，验证 session id、stream、transcript 和 usage。
- [ ] Codex resume 同一会话一次。
- [ ] Claude 新建一次。
- [ ] Claude resume 同一会话一次。
- [ ] 至少验证一次取消或安全审批，不执行危险修改。
- [ ] 对比前端事件与原生 transcript。

## 测试矩阵

- adapter：App Server、exec fallback、Claude stream；缺失命令和版本变化。
- 运行：成功、非零退出、无效 JSON、stderr、超时、取消、进程崩溃、服务重启。
- 会话：新建、resume、fork、错误 profile、cwd 不存在、同 session 并发冲突。
- WebSocket：刷新、断网、重复事件、sequence gap、慢消费者。
- 权限：安全默认、需要审批、拒绝、超时、能力不支持。

## 退出标准

- 两工具都能在前端实时展示结构化输出。
- App Server 不可用时 Codex 可解释降级。
- 同一 session 不会被两个 writer 同时写入。
- 浏览器刷新不丢事件、不重复计 usage。
- 取消后无遗留受管进程。
- 未经批准的危险操作不会执行。
- 受控真实回合全部在预算内，session 可从原生 CLI 再次看到。

## 风险与回滚

- 风险：App Server 命令仍标为 experimental。措施：稳定方法白名单、版本能力探测、exec fallback。
- 风险：取消遗留工具进程。措施：Job Object/process group 和集成测试。
- 风险：prompt shell 注入。措施：argv 数组、stdin/协议字段、禁止命令字符串拼接。
- 回滚：禁用执行路由后，Phase 1 只读会话中心仍完整可用；已产生的原生会话由对应 CLI 管理。

## 审查记录

- 暂无。

## 执行证据

- 尚未实施；真实回合测试尚未授权。
