# Phase 1：只读统一会话中心

> 状态：实施中  
> 依赖：Phase 0 已完成  
> 允许真实模型请求：否  
> 允许修改第三方数据：否

## 目标

交付可独立运行的 Codex/Claude 统一会话索引和内容查看功能。无论 Cockpit Tools 是否安装或运行，都能扫描原生目录、展示内容、搜索筛选，并正确识别同一 Session ID 的多物理副本和分叉。

## 非目标

- 不发送 prompt。
- 不 resume、fork、归档、删除或复制原生会话。
- 不读取第三方凭据来归属账号。
- 不接入定时任务。
- 不把 CC Switch 数据作为会话事实来源。

## 交付物

- Workbench SQLite 初始 schema 和迁移机制。
- Codex/Claude 增量索引器。
- Profile、项目、会话族、物理副本和分叉模型。
- 会话 REST API、可选本地全文搜索。
- Vue 3 + TypeScript + Vite 应用骨架及三栏会话页。
- 安装与数据源诊断页面。

## 任务

### P1-01：数据库与 Repository

- [x] 创建 `tool_profiles`、`accounts`、`repositories`、`projects`。
- [x] 创建 `conversation_families`、`session_copies`、`session_relations`。
- [x] 创建 `turns`、`events`、`source_checkpoints`。
- [x] 添加唯一键、外键、cursor 查询索引和 schema version。
- [ ] 实现数据库可重建策略和损坏恢复说明。

### P1-02：Profile 发现

- [ ] 支持手动目录、环境变量和默认目录。
- [x] Codex 支持多个 `CODEX_HOME`；Claude 支持多个 `CLAUDE_CONFIG_DIR`。
- [ ] 可选 Cockpit 连接器只读取用户授权的实例路径白名单。
- [x] 对候选目录做特征校验，不递归扫描任意用户目录。
- [ ] 记录 discovery source 和 capability probe。

验收环境：Cockpit 未安装、已安装未启用连接器、已安装已启用、Cockpit 正运行。

### P1-03：增量索引器

- [ ] 实现 watcher + periodic reconcile。
- [x] 保存 file identity、size、mtime、offset、content hash 和 parser version。
- [x] 只提交完整换行事件，容忍正在写入的尾行。
- [ ] 处理文件替换、缩短、移动、归档和暂时占用。
- [ ] 加入每 profile 扫描限速、取消和进度事件。

### P1-04：Codex 解析器

- [ ] 解析 session meta、turn context、messages、tool/command/file、usage 和 error。
- [ ] 识别 archived sessions 和 session index 标题。
- [x] 未知记录降级为 `unknown`。
- [ ] 对 CLI 版本和 parser version 建立兼容测试。

### P1-05：Claude 解析器

- [ ] 解析 user/assistant/system、thinking summary、tool use/result 和 usage。
- [ ] 识别主会话、subagent、attachment 和 file history snapshot。
- [ ] 解析项目目录编码并恢复规范化路径。
- [x] 未知 content type 不使会话失败。

### P1-06：会话族与分叉检测

- [x] 物理唯一键包含 tool、profile root、native id、transcript path。
- [ ] 依据初始指纹和共同事件前缀建立 family。
- [ ] 计算 `in_sync/ahead/diverged/unknown`。
- [x] 不自动合并 divergent 内容。
- [ ] API 提供副本列表和差异摘要。

### P1-07：账号和项目归属

- [ ] 实现 `exact/likely/unknown` 可信度。
- [x] 历史无证据时显示账号未知。
- [ ] 项目保存原 cwd、canonical path、repo root、worktree 和存在状态。
- [x] 不持久化 credential content。

### P1-08：API

- [ ] 会话列表支持 cursor、工具、profile、项目、时间、归档、分叉和搜索过滤。
- [x] 详情按事件分页，不返回无限事件数组。
- [x] 提供 profile 诊断、扫描状态、失败重试和数据源信息。
- [x] 定义稳定 DTO，禁止直接返回 raw tool schema。

### P1-09：前端工程迁移

- [x] 建立 Vue 3 + TypeScript + Vite、Router、Pinia。
- [x] 保留现有代理流量页面并纳入主导航。
- [x] 构建产物由 FastAPI 静态托管。
- [x] 发布/启动路径不要求 Node.js。
- [x] 建立主题、语义状态、focus、loading、empty 和 error 组件规范。

### P1-10：会话 UI

- [ ] 左栏筛选和虚拟会话列表。
- [ ] 中栏 Turn 时间线、Markdown、代码、tool、command、diff、unknown raw view。
- [x] 右栏元数据、关系和副本状态。
- [ ] 窄屏转换为列表/详情路由和检查器抽屉。
- [x] 支持 reduced motion。

### P1-11：全文搜索与隐私

- [x] 全文索引可配置开关；未确认前默认关闭。
- [ ] 建立 FTS5 重建和清除路径。
- [ ] 写入索引前执行最小密钥模式脱敏。
- [ ] UI 明确显示搜索覆盖范围。

## 测试矩阵

- Codex/Claude：正常、归档、子代理、未知记录、截断尾行、路径失效。
- 多 profile：同 ID 同步、一个领先、双方分叉、相同 ID 假碰撞。
- 外部工具：Cockpit/CC Switch 均无、仅一个存在、均运行。
- 数据规模：至少用本机数量级验证索引与虚拟列表；测试目标 1,000 会话、100,000 事件。
- 平台：按 P0 ADR 覆盖 Windows，若首版承诺 Linux 则同步覆盖路径和 watcher。

## 退出标准

- 不安装 Cockpit/CC Switch 时会话中心功能完整。
- 只读扫描期间第三方目录哈希不变。
- 两种工具主要事件可读，未知事件有 raw fallback。
- 同 ID 多副本不会被错误覆盖或静默拼接。
- 首次扫描、增量更新、重启恢复和大数据分页通过。
- 前端构建后由 FastAPI 提供，部署机器无需 Node.js。
- 无 resume、fork 或第三方写操作入口。

## 风险与回滚

- 风险：内部 JSONL schema 变化。措施：parser version、fixture、unknown fallback。
- 风险：全文索引泄露敏感内容。措施：默认关闭、可清空、脱敏和本地限定。
- 风险：新前端影响现有流量页。措施：路由隔离和现有 API 回归测试。
- 回滚：删除 Workbench 自有 DB 可完全重建；原生会话从未修改。

## 审查记录

- 暂无。

## 执行证据

- 2026-07-22：Phase 0 视为用户验收通过，状态改为 `已完成`；Phase 1 按用户“继续下一阶段”进入 `实施中`。
- 2026-07-22：新增 Workbench SQLite schema v1 和迁移初始化，数据库默认位于 `proxy-traffic-monitor/data/ai_workbench/workbench.db`，该目录已由 `.gitignore` 排除。
- 2026-07-22：新增只读 profile discovery，支持 `CODEX_HOME`、`CLAUDE_CONFIG_DIR` 多路径和默认 `~/.codex` / `~/.claude`。
- 2026-07-22：新增 Codex/Claude JSONL 索引垂直切片：只提交完整换行事件、未知事件降级、保存 source checkpoint。
- 2026-07-22：新增 `/api/ai-workbench/profiles`、`/scan`、`/sessions`、`/sessions/{copy_id}`。
- 2026-07-22：新增 Vue 3 + TypeScript + Vite + Router + Pinia 前端，构建产物由 FastAPI `/workbench` 和 `/static/workbench/` 托管；原 `/` 代理流量页保留。
- 2026-07-22：`impeccable` hook 指出 `Inter` 字体过度常见，已改为系统 UI 字体栈；未添加忽略规则。
- 2026-07-22：验证命令 `python -m pytest tests\ai_workbench\phase1 -q`，结果 `5 passed`。
- 2026-07-22：验证命令 `python -m pytest -q`，结果 `23 passed`。
- 2026-07-22：验证命令 `npm run build`，结果 Vite build succeeded。
- 当前未完成：watcher、手动目录 API、Cockpit 白名单连接器、完整 ahead/diverged 差异摘要、Markdown/diff 渲染、虚拟列表、FTS5 重建与清除。
