# Phase 4：多步骤自动任务与可靠调度

> 状态：待审查  
> 依赖：Phase 3 已完成并稳定  
> 允许真实模型请求：每个自动任务由用户显式创建并确认预算  
> 允许修改第三方数据：仅通过对应 CLI 在所选工作目录正常执行

## 目标

交付持久化的一次性/Cron 自动任务，能够在指定时间新建或续接会话，按顺序提交多个独立 prompt，实时展示运行、处理审批、支持错过任务策略、重试、取消和应用重启恢复。

## 非目标

- 不实现任意系统命令调度器；任务必须通过 AI 工具 adapter。
- 不自动跨账号迁移会话。
- 不默认唤醒已关机设备。
- 不允许未受限的危险自动批准。
- 不保证应用服务未运行时由内部 scheduler 自己执行。

## 交付物

- automations、steps、schedules、leases、runs 数据模型。
- Scheduler Worker 和 misfire/retry/concurrency 策略。
- 自动任务列表、日历、编辑器和运行历史。
- 安全权限模板、预算和审批等待。
- Windows 开机自启/服务方案；可选 Task Scheduler 桥接设计。

## 任务

### P4-01：任务数据模型

- [ ] automations、automation_steps、schedule spec、next_run_at。
- [ ] 保存 tool/profile/project/session action/model/permission/budget 快照。
- [ ] step 保存 order、prompt、delay、timeout、retry、on_error 和 override。
- [ ] 版本化任务修改，已开始 run 使用不可变 snapshot。

### P4-02：Scheduler Worker

- [ ] SQLite 为事实来源，内存 timer 只负责唤醒。
- [ ] claim lease、heartbeat、lease expiry 和幂等键。
- [ ] 一次性、Cron、时区、DST 和 next-run 计算。
- [ ] 任务级、tool/profile/session 级并发限制。
- [ ] 多 worker 情况下只执行一次。

### P4-03：Misfire 和恢复

- [ ] 定义 skip/run-now/ask 三种错过策略。
- [ ] 服务启动时扫描 overdue schedule。
- [ ] interrupted run 默认不自动重复发送 prompt，按任务策略处理。
- [ ] Step 级幂等记录避免重启后重复提交已完成 Turn。
- [ ] 时钟回拨和时区修改有确定行为。

### P4-04：多 Step 执行器

- [ ] 每个 Step 对应独立原生 Turn。
- [ ] 上一步完成后才开始下一步。
- [ ] 支持 delay、timeout、retry/backoff、stop/continue。
- [ ] 支持暂停后续 Step、只重跑失败 Step。
- [ ] 保存每步 session id、turn id、usage、输出和错误。

### P4-05：新建与续接策略

- [ ] New：按 profile/project 创建 session，后续 Step 复用新 id。
- [ ] Resume：运行前重新确认物理 session copy、profile 和 writer lease。
- [ ] Fork：创建新 id 并记录 lineage。
- [ ] 会话已移动/分叉/不存在时停止并要求选择，不猜测目标。

### P4-06：权限与预算模板

- [ ] 提供 read-only/plan、workspace-write/manual 等安全模板。
- [ ] 危险 bypass 不作为可见默认模板。
- [ ] 每任务 max budget、max duration、max turns。
- [ ] 等待审批不占用无限 worker；支持审批超时。
- [ ] 保存批准范围和审计记录。

### P4-07：自动任务 UI

- [ ] 列表/日历、启停、下一次运行和最近结果。
- [ ] 页面或侧栏编辑，不用大型 modal。
- [ ] Step 拖动排序、逐步启用、单步测试和 dry-run 摘要。
- [ ] 显示 profile、项目、session、权限、预算和 misfire。
- [ ] 删除采用可恢复停用/软删除。

### P4-08：运行中心扩展

- [ ] 展示 scheduled/queued/claimed/running/waiting/missed。
- [ ] 任务与 run/step 双向跳转。
- [ ] 支持 cancel current、pause remaining、approve、retry。
- [ ] 通知错误、错过、等待审批和预算耗尽。

### P4-09：后台运行

- [ ] 首版记录“FastAPI 服务必须运行”的限制。
- [ ] Windows 开机自启或服务模式，确保单实例 worker。
- [ ] 设计可选 Windows Task Scheduler 桥接用于启动/唤醒。
- [ ] 如果支持 Linux，设计 systemd user/service unit。
- [ ] 安装/卸载后台组件必须可逆并有状态诊断。

### P4-10：原 auto_resume.ps1 迁移

- [ ] 将原脚本作为行为参考，不作为运行时依赖。
- [ ] 把已有 prompt file、等待和 resume 场景映射到 automation/steps。
- [ ] 提供迁移说明或一次性导入器，避免自动读取并执行旧脚本。
- [ ] 标记旧脚本 deprecated 的条件由用户验收后决定。

## 测试矩阵

- 时间：一次性、Cron、DST、时钟回拨、休眠、服务停机后恢复。
- 并发：同任务重复 claim、同 session 两任务、不同 profile 并发。
- Step：成功、失败停止、失败继续、retry、取消、审批等待、预算耗尽。
- 恢复：worker crash、服务重启、Step 已发送但完成事件未持久化。
- 后台：开机自启、重复启动、卸载、无权限、端口占用。

## 退出标准

- 同一 scheduled occurrence 最多执行一次。
- 每句 prompt 是独立可审计 Step，不会被拼成一个大 prompt。
- 同一 session 并发写被可靠阻止。
- 休眠/停机后的行为符合用户选择的 misfire 策略。
- 重启不会无提示重复发送已经提交的 prompt。
- 无人值守任务不会越过未批准权限。
- UI 能从计划追溯到每个 Step 的实时和历史输出。

## 风险与回滚

- 风险：恢复时重复 prompt。措施：不可变 run snapshot、幂等键、提交前后状态和原生 turn id 对账。
- 风险：后台服务扩大攻击面。措施：localhost、认证边界、最小权限和可逆安装。
- 风险：自动批准危险操作。措施：模板白名单、waiting approval、预算/超时。
- 回滚：停用 scheduler worker 和后台服务，保留任务记录；Phase 3 手动运行继续可用。

## 审查记录

- 暂无。

## 执行证据

- 尚未实施。
