# Phase 5：跨 Profile 会话复制、分叉与回滚

> 状态：待审查  
> 依赖：Phase 1、3、4 已完成并稳定  
> 发布定位：2026-07-23 确认，不作为首个正式版本的发布门槛；本 Phase 完成后独立发布，交付时默认关闭并标记为实验性功能，首批只开放已验证的 copy/fork 组合，见架构文档 §19  
> 允许真实模型请求：迁移验证若需要续接，必须单独批准  
> 允许修改第三方数据：仅本 Phase 明确选择的目标 profile，且必须备份和可回滚  
> 验证映射：`docs/verification-and-boundaries.md` §3.8（Phase 5 复制安全闸门 MIG-01–04，未到 Phase 前均为空白，不得据此提前实现）

## 目标

在用户明确授权下，把 Codex 或可验证支持的 Claude 会话复制到另一个 profile/account/provider，使目标工具能够查看、续接或 Fork，同时正确处理隐私披露、provider 兼容、并发写入、Cockpit Tools 共存、分叉和回滚。

## 非目标

- 不做隐式“所有账号自动同步”。
- 不把远程云聊天误称为本地会话迁移。
- 不保证所有 provider、模型、工具和 MCP 能无损兼容。
- 不在目标账号未知时自动发送原会话内容。
- 不直接调用 Cockpit 私有进程或写其账号数据库。
- 不实现持续双向的原生文件同步（两台设备都能写同一个 native session 并自动合并）：2026-07-23 已评估并否决，见架构文档 §19 决策记录和 `CONTEXT.md`“会话同步（禁用词）”词条。本 Phase 只交付“复制”（一次性、事务性）和“交接”（复制之后转移活跃写入位置，不自动合并）两种精确定义的操作。

## 交付物

- 迁移预检、计划、备份、原子写入、验证和回滚流水线。
- 会话副本比较、ahead/diverged UI。
- Codex 跨 `CODEX_HOME` 复制实现。
- Claude 跨配置目录迁移可行性结论及实现（只有验证通过才交付）。
- Cockpit Tools 同开/关闭/未安装兼容报告。
- `THIRD_PARTY_NOTICES.md` 和复制代码署名。

## 进入 Phase 前的再次设计审查

该 Phase 风险最高，实施前必须重新核验当前 Codex/Claude 文件格式、App Server 能力和 Cockpit Tools 最新实现。若官方提供安全导入 API，优先替代文件级复制。

## 任务

### P5-01：迁移模型和隐私确认

- [ ] 明确 source copy、target profile、target provider/account、目标 cwd。
- [ ] 显示将发送给目标供应商的历史内容范围。
- [ ] 显示模型、工具、MCP、权限和成本兼容警告。
- [ ] 用户确认采用 copy、fork 还是 replace；首批发布只开放 copy/fork，replace（含 P5-11 设备交接）需单独完成验证矩阵后才开放，见 2026-07-23 发布范围决策。
- [ ] 保存迁移 consent 和计划哈希。

### P5-02：预检与写入门禁

- [ ] 检查 source/target 是否存在、可读、磁盘空间和文件系统原子替换能力。
- [ ] 检查 Codex/Claude/Cockpit 对相关实例的运行状态。
- [ ] 获取 source/target size、mtime、content hash 和 head event hash。
- [ ] 获取本项目 writer lease 和迁移全局锁。
- [ ] 写入前再次比较 precondition，任何变化都终止。

Cockpit 未运行也不能跳过哈希检查。

### P5-03：备份与事务日志

- [ ] 在 Workbench 自有 backup 目录保存目标受影响文件。
- [ ] 记录 manifest：路径、哈希、mtime、权限、操作和 tool version。
- [ ] 备份失败则硬失败，不继续迁移。
- [ ] 所有步骤写入 migration journal，支持崩溃恢复。
- [ ] 敏感备份设置本地访问权限和保留期。

### P5-04：Codex 复制实现

- [ ] 参考 Cockpit `codex_session_manager.rs` 与 `codex_thread_sync.rs`，记录上游 commit。
- [ ] 复制/合并 rollout 时验证共同前缀，不盲目以 mtime 选胜者。
- [ ] 必要时仅重写目标 `session_meta.model_provider`。
- [ ] 原子更新 `session_index.jsonl`，保留未知字段。
- [ ] 通过目标 Codex App Server stable API 重建/读取索引；失败则回滚或标记需修复。
- [ ] 不写 Cockpit `codex_instances.json` 或账号文件。

### P5-05：Claude 可行性验证

- [ ] 重新验证 Claude session id、项目目录编码、resume 搜索范围和 config dir 隔离。
- [ ] 确认是否能只通过官方 CLI 指定目标配置目录恢复。
- [ ] 验证附件、subagent、file-history 和权限引用。
- [ ] 若无法安全迁移，交付明确“不支持跨 profile 复制”，保留原 profile resume。
- [ ] 不为了功能对未知 Claude 文件做猜测性改写。

### P5-06：分叉和冲突处理

- [ ] 同 ID 同内容：标记 in_sync，无需写。
- [ ] 一方是严格后继：允许用户选择更新落后副本。
- [ ] 双方分叉：禁止自动合并，提供并排差异和 Fork 新 id。
- [ ] 迁移后每个物理 copy 独立索引和 lineage。
- [ ] 不把两个 assistant 分支按时间戳交错拼接。

### P5-07：验证和回滚

- [ ] 目标 App Server/CLI 只读列出并读取迁移会话。
- [ ] transcript 事件数、头尾 hash、标题、cwd 和 provider 通过。
- [ ] 若批准低成本验证，只发送一条无副作用 resume prompt。
- [ ] 任一验证失败执行 rollback，并再次验证原目标状态。
- [ ] 提供手动恢复命令和 manifest 查看。

### P5-08：Cockpit Tools 共存测试

- [ ] 未安装 Cockpit。
- [ ] 已安装但关闭。
- [ ] 已安装且 GUI 运行，但未对目标执行同步。
- [ ] 检测到 Cockpit 正在同步/目标变化，必须中止。
- [ ] 迁移后 Cockpit 能正常查看且其配置未改变。

### P5-09：UI

- [ ] 会话检查器显示所有 physical copies 和 divergence。
- [ ] 迁移向导分预检、隐私确认、执行、验证、结果。
- [ ] 风险和目标 account/provider 始终可见。
- [ ] 失败页面提供 rollback 状态，不只显示通用错误。
- [ ] 高风险动作要求再次输入目标名称或等价明确确认。

### P5-10：许可证与引用

- [ ] 创建/更新 `THIRD_PARTY_NOTICES.md`。
- [ ] 每个派生文件记录上游 URL、commit、CC BY-NC-SA 4.0 和 changes。
- [ ] 保留上游版权与许可证文本。
- [ ] 确认项目发布方式满足 ShareAlike 和非商业限制。

### P5-11：设备交接（2026-07-23 新增）

背景：用户提出"多设备会话同步"需求，评估后拆解为远程查看（复用已确认的 SSH 隧道方案，不需要新功能）、复制（本 Phase 已有的一次性迁移）和交接（本任务）三个精确操作，明确不做持续双向同步（见上方非目标）。

- [ ] 交接建立在 P5-01 已有的 copy/fork/replace 确认流程之上，新增一个显式"设备交接"入口，语义等价于 replace，但 UI 文案和确认步骤专门针对"我要换到另一台设备继续用这个会话"的场景。
- [ ] 交接完成后，在源设备的会话检查器里标记该会话副本为"已交接"，并提示用户不要在源设备继续对其调用 resume/continue。
- [ ] 明确说明本项目无法阻止用户绕过工作台直接在源设备运行原生 CLI；标记只是提示，不是强制锁。
- [ ] 若源设备在交接后仍产生新事件（用户绕过提示继续写），按 P5-06 标记为 `diverged`，不自动合并，提示用户手动选择保留哪一方。
- [ ] 交接流程复用 P5-02 预检、P5-03 备份、P5-07 验证与回滚，不单独建一套写入路径。

## 测试矩阵

- source/target：空目标、相同内容、target ahead、source ahead、diverged、corrupt。
- 并发：CLI 正写、Cockpit 正运行、迁移中目标变化、进程崩溃。
- 文件：权限不足、磁盘满、长路径、跨卷、杀毒软件占用、非原子文件系统。
- provider：相同、不同、模型缺失、MCP 缺失、工具能力不兼容。
- 回滚：每个事务步骤注入故障并验证目标完全恢复。

## 退出标准

- 未安装 Cockpit 时功能独立可用；安装 Cockpit 时无配置或数据冲突。
- 迁移前一定有可验证备份，迁移后一定有读取验证。
- precondition 变化会中止，不覆盖并发写入。
- divergent 会话不会自动合并。
- 失败后 rollback 恢复目标哈希和索引。
- 目标 provider 和数据外发范围经过显式确认。
- 所有派生代码符合署名和许可证要求。
- 实验性标记只收窄支持范围（首批 copy/fork），不降低备份、precondition、原子写入、回滚、隐私披露的验收标准。

## 风险与回滚

- 风险：损坏或覆盖真实历史。措施：默认 copy、备份硬门槛、CAS/hash、原子写和故障注入。
- 风险：跨账号泄露上下文。措施：明确目标和数据范围、二次确认、审计。
- 风险：与 Cockpit 同时写入。措施：进程检测只是辅助，最终以 precondition hash 为准。
- 风险：ShareAlike 影响项目许可。措施：实现前许可证审查和完整 notices。
- 回滚：使用 migration manifest 恢复目标文件、索引、mtime 和权限；不删除 source。

## 审查记录

- 2026-07-23：用户提出"多设备会话同步"需求，经 Codex 头脑风暴评估后拆解为远程查看/复制/交接/分叉四个精确概念（见架构文档 §19 决策记录和 `CONTEXT.md`）。远程查看复用已确认的 SSH 隧道方案；复制沿用本 Phase 已有设计；新增 P5-11 设备交接；明确否决持续双向原生文件同步。本 Phase 状态仍为 `待审查`，此次只是补充范围，未批准实施。
- 2026-07-23：确认 Phase 5 不作为首个正式版本的发布门槛，完成后独立发布、默认关闭、标记实验性；首批只开放 copy/fork，replace/设备交接/Claude 目标/跨 provider 分别验证后再开放；验收标准不因"实验性"降低。本 Phase 状态仍为 `待审查`。

## 执行证据

- 尚未实施。
