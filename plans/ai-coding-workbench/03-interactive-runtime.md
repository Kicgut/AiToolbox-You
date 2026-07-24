# Phase 3：交互式运行、续接与实时输出

> 状态：待审查  
> 依赖：Phase 2 已完成  
> 允许真实模型请求：仅在验收末期单独批准  
> 允许修改第三方数据：仅由官方 CLI/App Server 正常产生新的会话事件  
> 验证映射：`docs/verification-and-boundaries.md` §3.5（进程执行/真实额度/危险权限，含 RUN-01–04 当前空白清单，RUN-04 对应 P3-10 一次性审批硬门禁）

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
- [ ] 实现并验证 Windows process group/Job Object；Linux process group 或其他等价进程监管不在本 Phase 的发布阻塞项和验收范围内。
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

2026-07-23 确认：账号模板采用"日常账号 + 一次性硬范围"——使用已登录的日常 Codex/Claude 账号（最贴近真实使用环境），但每次批准只覆盖下方模板里明确列出的固定回合数，不构成后续测试或自动重试的授权。模型选择原则：验证目标是链路（session id/stream/transcript/usage 是否正确），不是回复质量，应选账号当前可用的最低成本、最可预测档位，且必须在批准单里写清楚只读探测到的确切型号，不能只写"便宜模型"，防止 CLI 静默回退到更贵的模型。

- [ ] Codex 新建一次，验证 session id、stream、transcript 和 usage。
- [ ] Codex resume 同一会话一次。
- [ ] Claude 新建一次。
- [ ] Claude resume 同一会话一次。
- [ ] 至少验证一次取消或安全审批，不执行危险修改。
- [ ] 对比前端事件与原生 transcript。

真正执行前，必须由用户逐字段填写并明确批准以下审批单，一般性的 Phase 3 批准、代码审查通过或"可以测试"之类表述不能替代这份一次性授权：

```
### P3-10 真实回合测试一次性审批请求

本审批仅授权下列一次性 Phase 3 验收操作，不构成后续真实模型测试、自动重试或扩大测试范围的授权。

- 批准有效期：〔开始时间〕至〔结束时间〕；到期自动失效。
- Codex 账号/profile：〔非敏感标识〕。
- Codex provider：〔名称〕。
- Codex 模型：〔只读探测确认的确切型号，或明确批准的 CLI 默认模型〕。
- Claude 账号/profile：〔非敏感标识〕。
- Claude provider：〔名称〕。
- Claude 模型：〔只读探测确认的确切型号，或明确批准的 CLI 默认模型〕。
- 计费方式：〔订阅额度/API 计费〕。
- 工作目录：〔确切路径〕。
- 权限模式：〔确切模式〕。
- 允许的工具：〔无，或明确白名单〕。
- 禁止的操作：文件修改、未经批准的命令执行、外部网络操作、危险权限绕过及白名单外工具调用。
- Codex 新建 prompt：〔完整原文或已确认内容哈希〕。
- Codex resume prompt：〔完整原文或已确认内容哈希〕。
- Claude 新建 prompt：〔完整原文或已确认内容哈希〕。
- Claude resume prompt：〔完整原文或已确认内容哈希〕。
- 批准的业务回合：Codex 新建一次、Codex resume 一次、Claude 新建一次、Claude resume 一次，共最多四个成功回合。
- 取消/安全审批测试：〔是否批准；具体操作和是否允许额外模型调用〕。
- 每回合最大输入长度：〔上限〕。
- 每回合最大输出 token：〔上限，或"不受 CLI 直接支持，改由下列 turn/超时限制约束"〕。
- 每回合最大 agentic turn 数：〔上限〕。
- 每回合最大运行时间：〔上限〕。
- 单工具累计预算上限：Codex〔上限〕；Claude〔上限〕。
- 全部测试累计预算上限：〔金额或额度上限〕。
- 自动重试：默认禁止；允许的例外及次数为〔具体条件和次数〕。
- 模型回退：〔禁止；或列出唯一允许的回退型号〕。
- 中止条件：账号/profile/model 不一致、无法读取 usage、达到任一预算或次数上限、出现未批准工具或权限请求、发生重复提交迹象、超时、用户撤销批准。
- 验收记录：保存实际账号非敏感标识、模型、session ID、回合数、usage、费用估算、退出状态，以及 Workbench 事件与原生 transcript 的对比结果。
- 数据保留与清理：〔测试 session、日志和 Workbench 索引的保留或清理规则〕。
- 用户批准结论：〔批准/不批准〕。
- 批准时间：〔时间〕。
- 批准人确认：〔明确确认文本〕。
```

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

- 2026-07-23：经 Codex 头脑风暴确认 P3-10 的账号模板（日常账号 + 一次性硬范围）、模型选择原则（只读探测后选最低成本可预测档位，禁止静默回退）和结构化预算表达方式，并把简短描述替换为逐字段的一次性审批单模板，见架构文档 §19 决策记录。本 Phase 状态仍为 `待审查`，此次只是补充范围，未批准实施。

## 执行证据

- 尚未实施；真实回合测试尚未授权。
