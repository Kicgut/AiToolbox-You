# Phase 2：统计中心与 CC Switch 可选增强

> 状态：待审查  
> 依赖：Phase 1 已完成  
> 允许真实模型请求：否  
> 允许修改第三方数据：否；本项目不升级 CC Switch，连接器始终只读  
> 验证映射：`docs/verification-and-boundaries.md` §3.3（CC Switch 只读连接器/回退/去重/pricing source，含 CC-01–05 当前空白清单）、§3.4 EVT-04（数据质量传播）

## 目标

在所有部署环境中用原生会话日志提供一致的基础统计，并在 CC Switch 存在时用只读代理观测补充 provider、HTTP 状态、TTFT、延迟和已记录成本。所有指标展示来源和数据质量，且不重复计数。

## 非目标

- 不让 CC Switch 成为依赖。
- 不从本项目写入或迁移 CC Switch 数据库。
- 不升级、降级、重装、修复或调用 CC Switch updater。
- 不把订阅 token 估算称为实际账单。
- 不用“退出码 0”或 AI 自述定义任务成功。
- 不在本 Phase 发送真实模型 prompt。

## 交付物

- `usage_records`、统计聚合和数据质量模型。
- Codex/Claude 原生日志 usage 解析。
- CC Switch 只读 connector。
- 观测去重与来源合并。
- 统计 API 和统计页面。
- CC Switch 未安装、v10、v16 和未知未来版本的只读兼容报告。

## 任务

### P2-00：升级本项目的 CC Switch 兼容层

- [ ] 只读探测本机安装版本、`PRAGMA user_version` 和所需表/列能力。
- [ ] 使用脱敏 fixture 覆盖未安装、v10、v16 和未知未来 schema。
- [ ] 记录版本差异对统计字段、去重和数据质量的影响，不把“版本较旧”当成启动失败。
- [ ] 若升级可能改善数据质量，只向用户展示建议；不得调用安装器、包管理器、内置 updater 或 schema migration。
- [ ] 建议用户从 CC Switch 自身软件界面执行完整更新；用户确认更新完成后，才重新探测并重跑兼容测试。
- [ ] 保留 v10 脱敏 schema fixture，不能只测试当前开发机器。
- [ ] （2026-07-23 新增）schema 探测与实际查询绑定同一个短生命周期只读事务，避免 CC Switch 并发写入时读到跨时点不一致数据；探测期间 schema 发生变化时中止本轮，不提交部分结果。
- [ ] （2026-07-23 新增）区分"暂时忙"（`busy_timeout` 重试退避）、"长期不可用"（关闭增强并诊断）、"schema 不兼容"（关闭增强并说明差异）三种状态，分别给出不同 UI 提示，不能只有一种通用错误。
- [ ] （2026-07-23 新增）建立 schema capability 探测结果的缓存和 TTL/失效策略，避免每次查询都重新探测带来的性能开销；价格内容本身的刷新与 schema capability 缓存分离处理。
- [ ] （2026-07-23 新增）明确多个自定义 CC Switch 数据库路径的注册规则，避免重叠数据被重复计数；测试矩阵补充 WAL 模式、文件权限不足、伴随文件（`-wal`/`-shm`）缺失或损坏的场景。
- [ ] （2026-07-23 新增）CC Switch 升级替换数据库文件后，绑定文件身份（如 inode/hash）+ schema version 的 checkpoint，检测到文件被替换时使旧同步游标失效并重新对齐，不盲目继续增量读取。
- [ ] （2026-07-23 新增）对读取到的字段做合法性校验（空值、负数、异常数量级、别名歧义），错误信息经过脱敏后再展示给 UI，不直接暴露本机路径等敏感细节。

CC Switch 是否升级不属于本 Phase 的执行范围，也不是本 Phase 的阻塞项。

### P2-01：统计数据模型

- [ ] 创建 usage records、observations、daily rollups 和 pricing snapshots。
- [ ] 区分 session observation、supervised run observation、proxy observation。
- [ ] 每字段保存 source、quality、observed_at 和 parser version。
- [ ] 设计可重建 rollup 和时区边界。

### P2-02：Codex usage 解析

- [ ] 处理累计 token snapshot 的差分。
- [ ] 识别 input/output/cache/reasoning 语义。
- [ ] 处理 fork、subagent、重放和父子重复。
- [ ] 使用 CC Switch v3.18 修复思路作为测试参考，但实现独立去重。
- [ ] 为 CLI 版本变化保留 token semantics 字段。

### P2-03：Claude usage 解析

- [ ] 解析 input/output/cache read/cache creation。
- [ ] 按 message id/content fingerprint 去重。
- [ ] 区分 main/subagent/workflow。
- [ ] 可用时交叉校验 `stats-cache.json`，但不把缓存文件作为唯一事实源。

### P2-04：CC Switch 只读连接器

- [ ] 默认发现 `~/.cc-switch/cc-switch.db`，支持自定义路径。
- [ ] 使用 `mode=ro`、短事务、busy timeout。
- [ ] 先探测 `user_version/sqlite_master/table_info`，再构造白名单查询。
- [ ] 禁止读取 provider 凭据配置和敏感 JSON。
- [ ] 数据库缺失、忙、损坏、未来 schema 时关闭增强并给出诊断。
- [ ] 记录连接状态、版本、最后同步游标和错误，不复制整个第三方 DB。

`model_pricing` 接入 pricing source（2026-07-23 确认，方案 C：只读探测为候选来源，默认不启用，用户显式信任后才生效；只产生 API-equivalent estimate，不得改写 token/会话/实际成本事实；用户自建 snapshot 优先级高于此来源，冲突需显式展示不能静默覆盖）：

- [ ] 把 `model_pricing` 实现为独立的 pricing adapter，与 `proxy_request_logs`/UsageRecord 的事实导入流程完全分离。
- [ ] 按 CC Switch schema 版本（v10/v16/未知未来）为 `model_pricing` 建立脱敏 fixture，验证列结构、类型和单位语义；验证完成前不得自动启用此来源。
- [ ] 设立准入规则：记录缺少价格数值、币种或计价单位时拒绝进入可计算集，不得用推测值补齐。
- [ ] 明确区分并分别标注四个时间概念：`effective_at`（价格生效时间，无明确字段/语义时标记未知）、价格本身的更新时间（无字段时不得使用 mtime 冒充）、本项目的导入时间、本项目的观察/读取时间。
- [ ] 定义来源优先级和冲突展示规则：用户手动配置的价格 snapshot 优先于 CC Switch 来源；两者都存在且不一致时并排显示，不静默选择。
- [ ] 建立模型名到 CC Switch 价格记录的显式、可审计别名映射，不做隐式模糊匹配。
- [ ] 来源被用户禁用或移除后，历史已生成的估算保持可审计（不删除、不静默改写），但不得继续用于新估算，也不得回填为实际成本。

### P2-05：去重和观测合并

- [ ] `session_log/codex_session` 默认只用于交叉校验，不二次计 token。
- [ ] `proxy` observation 补充 TTFT、status、provider、latency、recorded cost。
- [ ] 优先 request id；缺失时使用 session/time/model/token fingerprint。
- [ ] 保留冲突观测并标记，不静默选择更好看的数字。
- [ ] 为 CC Switch v3.17 双计样本建立回归测试。

### P2-06：成本语义

- [ ] 区分 recorded actual、API-equivalent estimate 和 unavailable。
- [ ] 2026-07-23 确认：项目不维护内置权威价格表，只实现可插拔 pricing source；价格来自用户导入/配置的本地 snapshot，每条估算附带来源、生效时间、更新时间和币种；没有价格源时成本显示为不可用，不得显示 0 或误导性默认值。CC Switch 的 `model_pricing` 可作为默认不启用的候选来源，见 P2-04。
- [ ] 价格按生效时间保存 snapshot，不用今天价格重写历史。
- [ ] 订阅登录仅显示估算，不能显示“已花费”。

### P2-07：统计 API

- [ ] overview、timeseries、breakdown、reliability、data-quality。
- [ ] 统一日期、工具、profile、项目、模型、provider、source 过滤器。
- [ ] 对大范围查询使用 rollup 和查询上限。
- [ ] 返回 metric availability，不用 0 代替缺失。

### P2-08：统计 UI

- [ ] 紧凑 KPI、趋势、breakdown 表和可靠性区。
- [ ] 每项显示 exact/estimated/unavailable。
- [ ] 可展开数据来源、公式和缺失原因。
- [ ] CC Switch 连接器关闭时保持相同布局。
- [ ] 支持 CSV 导出原始数值及质量字段。

### P2-09：维护与重建

- [ ] 支持只重建 Workbench usage 和 rollup。
- [ ] 重建不触碰 CC Switch DB。
- [ ] 提供 parser version 迁移、进度、取消和失败恢复。
- [ ] 重建前后生成数量与总量审计摘要。

## 测试矩阵

- CC Switch：未安装、v10、v16、future version、busy、corrupt、无 proxy rows。
- 来源：仅原生日志、仅 proxy fixture、两者重叠、冲突、重复。
- 统计：缓存 token、累计差分、fork/subagent、时区/DST、模型切换。
- UI：exact/estimated/unavailable 混合、空时间段、大数量、connector 失败。

## 退出标准

- 未安装 CC Switch 时基础 token、会话、Turn、工具统计完整可用。
- 安装 CC Switch 时只增加可证明的丰富字段，不改变基础计数。
- v10/v16 和缺失数据库均通过测试。
- CC Switch 数据库在连接器测试前后哈希不因本项目改变。
- fork/subagent 重放不造成重复 token。
- recorded cost 和 estimate 在 API、UI、导出中始终分离。
- 所有不可用指标显示 `—` 和原因，不显示 0。

## 风险与回滚

- 风险：外部软件版本差异改变字段或统计语义。措施：只读能力探测、版本化 fixture、数据质量标签和兼容降级；本项目不执行外部升级。
- 风险：第三方 schema 继续变化。措施：字段探测、白名单、未来版本 fallback。
- 风险：观测去重误合并。措施：保留 observation、可审计匹配原因、冲突不覆盖。
- 回滚：禁用 CC Switch connector 后重新从原生日志构建；没有由本项目触发的外部软件升级需要回滚。

## 审查记录

- 2026-07-23：经 Codex 头脑风暴确认模型价格表方案（不维护内置权威价格表，只做可插拔 pricing source），已同步到 P2-06 和架构文档 §19 决策记录。本 Phase 状态仍为 `待审查`，此次只是补充范围，未批准实施。
- 2026-07-23：经 Codex 仔细评估 CC Switch `model_pricing` 接入方案（方案 C：只读探测为候选来源，默认不启用）和 P2-00/P2-04 的兼容性设计缺口，已把具体子项补进 P2-00（一致性读取、锁状态区分、schema 缓存、多数据库路径、文件替换游标失效、字段校验脱敏）和 P2-04（pricing adapter 分离、版本 fixture、准入规则、时间字段区分、来源优先级、别名映射、禁用后可审计）。本 Phase 状态仍为 `待审查`。

## 执行证据

- 规划时验证：本机 CC Switch 3.15.0/schema v10；官方 3.18.0/schema v16。
