# Phase 1：只读统一会话中心

> 状态：已批准（2026-07-24，本轮修订范围：P1-12 → P1-14 → P1-13，按此顺序实施）  
> 依赖：Phase 0 已完成  
> 允许真实模型请求：否  
> 允许修改第三方数据：否  
> 验证映射：`docs/verification-and-boundaries.md` §3.2（原生目录/Cockpit/增量索引并发，含 IO-01–06 当前空白清单）、§3.3 CC-01/03（CC Switch 只读边界）、§3.4（Adapter/事件/DTO）、§3.6 SEC-01–03（网络边界、凭据、FTS consent）、§3.7 DEP-01/02（部署与构建一致性）

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
- [x] 实现数据库可重建策略和损坏恢复说明。

### P1-02：Profile 发现

- [x] 支持手动目录、环境变量和默认目录。
- [x] Codex 支持多个 `CODEX_HOME`；Claude 支持多个 `CLAUDE_CONFIG_DIR`。
- [x] 可选 Cockpit 连接器只读取用户授权的实例路径白名单。
- [x] 对候选目录做特征校验，不递归扫描任意用户目录。
- [x] 记录 discovery source 和 capability probe。

验收环境：Cockpit 未安装、已安装未启用连接器、已安装已启用、Cockpit 正运行。

### P1-03：增量索引器

- [x] 实现 watcher + periodic reconcile。
- [x] 保存 file identity、size、mtime、offset、content hash 和 parser version。
- [x] 只提交完整换行事件，容忍正在写入的尾行。
- [x] 处理文件替换、缩短、移动、归档和暂时占用（全量扫描通过整文件重建正确处理这些场景）。
- [x] 加入每 profile 扫描限速、取消和进度事件。
- [ ]（2026-07-24 重开）实现真正的按 byte offset 增量读取：从 `source_checkpoints.parsed_offset` 续读新增内容，不整文件 `read_text()` 重读、不 `DELETE FROM events` 后全量重插。当前 `scanner.py::_index_transcript` 每次都是全量重读重建，与架构 §5.3"只在换行完成后提交新事件"的增量语义不符，虽然功能结果目前正确，但性能和并发安全属性不达标。
- [ ]（2026-07-24 重开）读取前后二次 stat 复核：`_index_transcript` 目前只在读取前 `stat()` 一次，读取后不比较文件长度和 mtime 是否发生变化；架构 §5.3 明确要求"读取前后比较文件长度和 mtime；变化时重新验证尾部"。
- [ ]（2026-07-24 重开）对暂时被占用的文件实现指数退避，不标记为损坏：当前 `scan_sessions` 捕获 `OSError` 后直接记录错误继续，`watcher.py::run_forever` 只有固定 15 秒轮询间隔，没有单文件级别的指数退避状态机。
- [ ]（2026-07-24 新增，实现缺口非仅测试缺口）`changed_only`/reconcile 模式的内容哈希判断缺失：`scanner.py::_needs_reindex`（第 539–547 行）只比较 `file_size`、`mtime_ns`、`parser_version`，不比较内容哈希。若文件内容被替换但 size 和 mtime 恰好不变（例如某些同步/备份工具的行为），reconcile 会直接跳过该文件，数据库保留过期内容，不符合架构 §5.3"哈希不匹配时重新解析"的要求。需要在 `_needs_reindex` 中补充内容哈希比较（或至少在哈希未知时保守触发重索引），并覆盖 hash-only replacement、file identity 变化场景。

验收：本节新增四项按架构 §5.3 逐条验证，见 `docs/verification-and-boundaries.md` IO-03/IO-04/IO-05/IO-06。

### P1-04：Codex 解析器

- [x] 解析 session meta、turn context、messages、tool/command/file、usage 和 error。
- [x] 识别 archived sessions 和 session index 标题。
- [x] 未知记录降级为 `unknown`。
- [x] 对 CLI 版本和 parser version 建立兼容测试。

### P1-05：Claude 解析器

- [x] 解析 user/assistant/system、thinking summary、tool use/result 和 usage。
- [x] 识别主会话、subagent、attachment 和 file history snapshot。
- [x] 解析项目目录编码并恢复规范化路径。
- [x] 未知 content type 不使会话失败。

### P1-06：会话族与分叉检测

- [x] 物理唯一键包含 tool、profile root、native id、transcript path。
- [x] 依据初始指纹和共同事件前缀建立 family。
- [x] 计算 `in_sync/ahead/diverged/unknown`。
- [x] 不自动合并 divergent 内容。
- [x] API 提供副本列表和差异摘要。

### P1-07：账号和项目归属

- [x] 实现 `exact/likely/unknown` 可信度。
- [x] 历史无证据时显示账号未知。
- [x] 项目保存原 cwd、canonical path、repo root、worktree 和存在状态。
- [x] 不持久化 credential content。

### P1-08：API

- [x] 会话列表支持 cursor、工具、profile、项目、时间、归档、分叉和搜索过滤。
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

- [x] 左栏筛选和虚拟会话列表。
- [x] 中栏 Turn 时间线、Markdown、代码、tool、command、diff、unknown raw view。
- [x] 右栏元数据、关系和副本状态。
- [x] 窄屏转换为列表/详情路由和检查器抽屉。
- [x] 支持 reduced motion。

### P1-11：全文搜索与隐私

- [x] 全文索引可配置开关；未确认前默认关闭。
- [x] 建立 FTS5 重建和清除路径。
- [x] 写入索引前执行最小密钥模式脱敏。
- [x] UI 明确显示搜索覆盖范围。

### P1-12：主页信息架构调整（2026-07-23 新增，修订中）

背景：用户审查确认 workbench 应作为前端主壳，而不是现有的代理流量监控页面；架构文档 §13.2 已同步更新决策记录。本任务范围限定为“最小改动”路由调整，不包含 §13.7 列出的前端结构重构、样式统一等独立技术债。

- [ ] 新增“总览”路由，作为 workbench SPA 的默认首页，包含跳转卡片：会话中心、代理流量，并为用量统计/自动任务/运行中心/设置预留占位入口（已实现功能可点击，未实现功能显示禁用占位并标注 Phase）。
- [ ] FastAPI 路由对调：根路径 `/` 改为提供 workbench SPA（含总览首页），代理流量监控迁移到新路径 `/traffic`。
- [ ] 代理流量页面本身实现不变（继续沿用现有静态资源和 Vue ESM 直引），只调整可访问路径和入口方式；按 2026-07-24 确认追加一个最小的“返回总览”链接指向 `/`（普通 `<a>` 链接，不接入 Vue Router/workbench 组件体系）。
- [ ] 按下方“FastAPI 路由与受约束 SPA fallback 契约”实现受约束 catch-all，确保 workbench SPA 使用的 history 路由模式下，`/`、`/sessions` 等路径在浏览器直接刷新时仍能正确返回 SPA `index.html`，同时不吞掉 `/api/*`、`/static/*`、`/ws/live`、`/traffic` 和未知资源请求。
- [ ] `/workbench` 旧路径改为 `307 Temporary Redirect` 到 `/sessions`，不做 404 下线，保留旧书签兼容性。
- [ ] Vue Router 新增 `/` 总览、`/sessions` 会话中心两条路由，并保留一条前端内部 404 兜底（不静默重定向到总览）。
- [ ] 更新 `README.md`（如涉及使用说明中的默认访问地址）。
- [ ] 更新本 Phase 的执行证据和测试矩阵条目。

验收环境：直接访问 `/`、访问总览页后点击跳转、浏览器刷新已跳转到的子路径、访问旧路径 `/workbench`。

#### P1-12 FastAPI 路由与受约束 SPA fallback 契约（2026-07-24 设计细化）

路由注册顺序固定如下，SPA fallback 必须最后注册：

1. `app.mount("/static", ...)`；
2. `/ws/live`；
3. 全部 `/api/*` 子路由，包括 `/api/ai-workbench/*`；
4. `/traffic` 代理流量页面及其现有 `/static/*` 静态资源；
5. `/workbench` → `/sessions` 旧路径兼容重定向；
6. workbench SPA 根路由 `/`；
7. 最后的受约束 `/{spa_path:path}` fallback。

改动前/改动后路由表：

| 路径 | 改动前 | 改动后 |
|---|---|---|
| `/` | 代理流量页面 | workbench SPA 总览 |
| `/workbench` | workbench SPA 会话中心 | `307 Temporary Redirect` 到 `/sessions` |
| `/sessions` | 404 | workbench SPA 会话中心，由受约束 fallback 返回 SPA `index.html` |
| `/traffic` | 404 | 现有代理流量页面 |
| `/static/*` | 现有静态资源 | 保持不变，包括 `/static/workbench/*` |
| `/api/*` | API | 保持 API 语义，不得进入 SPA fallback |
| `/ws/live` | WebSocket | 保持不变，不得进入 SPA fallback |

受约束 SPA fallback 只在以下条件全部满足时返回 `app/static/workbench/index.html`：

- 请求方法是 `GET` 或 `HEAD`；
- `Accept` header 按逗号拆分并去除参数后，至少有一个媒体类型精确等于 `text/html`，比较时不区分大小写；
- 请求路径的首个完整路径段不属于保留段 `{api, static, traffic, ws}`；
- 最后一个非空路径段没有文件扩展名。

路径排除必须按完整路径段判断，不得使用宽字符串前缀。例如：

- `/api`、`/api/status` 排除；`/apiary` 不因以 `/api` 开头而排除；
- `/traffic`、`/traffic/assets/x` 排除；`/traffic-report` 不因以 `/traffic` 开头而排除。

以下请求必须返回真实 404，不得返回 SPA HTML：

- `Accept` 不包含 `text/html` 的未知路径；
- `/favicon.ico`、`/assets/x.js`、`/sessions/export.csv` 这类带扩展名的未知路径；
- 任意未知的 `/api/*`、`/static/*`、`/traffic/*` 或 `/ws/*` 路径。

`/` 使用明确注册的 SPA 根路由；`/sessions` 及未来无扩展名的 workbench history 路由使用同一个受约束 fallback。FastAPI 只负责返回 SPA 应用壳，实际页面匹配由 Vue Router 完成。

验收断言：

- `GET /` + `Accept: text/html` 返回 workbench SPA；
- `GET /sessions` + `Accept: text/html` 返回同一 SPA `index.html`；
- `HEAD /sessions` 返回相同状态和响应头且无响应体；
- 浏览器直接刷新 `/sessions` 不返回 404；
- `GET /traffic` 返回现有代理流量页面；
- `/static/*`、`/api/*`、`/ws/live` 行为不变；
- `/apiary` 可进入 SPA fallback，但 `/api/unknown` 不可；
- `/favicon.ico`、`/assets/x.js` 返回 404；
- 非 HTML Accept 的未知无扩展名路径返回 404；
- `/workbench` 返回到 `/sessions` 的 307 重定向。

### P1-13：前端基础整理门禁（2026-07-23 新增，修订中）

背景：架构复审（§13.7）确认 `frontend/src/main.ts` 是单文件模板字符串实现，缺少 `.vue` SFC 和 `views/components/stores/router` 拆分。2026-07-23 决定：不并入 P1-12，也不作为 Phase 2 内部任务，而是 P1-12 验收后单独设立的门禁——完成本任务前不批准 Phase 2。

进入条件：P1-12 完成并通过对应路由验收。

实施顺序（2026-07-24 确认）：P1-13 的行为回归清单包含 FTS consent 相关项（见下方回归清单），但 consent 状态模型要到 P1-14 才实现。因此实际执行顺序为 **P1-12 → P1-14 → P1-13**，P1-13 作为包含最终 FTS consent 行为的最后一道全量回归门禁执行，而不是按任务编号顺序执行。若确有理由必须先做 P1-13 再做 P1-14，则 P1-14 完成后必须重新跑一遍 P1-13 的完整 17 项回归清单和严格构建比较，不能只增量验证新增部分。

范围严格限定为结构迁移，不改变现有业务行为：

- [ ] 把 `main.ts` 拆分为入口、`router/`、`views/`、`components/`、`stores/` 和类型/API 模块。
- [ ] 总览和会话中心改写为 `.vue` SFC，路由、API、store 状态和页面行为保持不变。
- [ ] 建立供 Phase 2 起后续页面复用的最小 workbench 基础样式 token（颜色、间距、字体、控件状态）。
- [ ] 不重写 `/traffic`（代理流量监控）；跨两套页面的视觉统一只做到明确批准的最小 token 层级。
- [ ] 不提前实现统计、运行中心、自动任务或跨 profile 迁移的任何 UI。
- [ ] 补一次构建产物与源码一致性检查（呼应 §13.7 第 4 项技术债），按下方“构建产物一致性与行为回归契约”执行。
- [ ] 完成后做一次行为回归（会话列表、筛选、扫描、全文索引控制等 P1-10/P1-11 已验收功能不能因重构而退化），使用下方回归清单逐项勾选。

退出标准：结构迁移完成、行为回归通过、构建产物一致性检查建立，之后才能批准 Phase 2。

#### P1-13 构建产物一致性与行为回归契约（2026-07-24 设计细化）

构建一致性检查必须使用干净的临时构建环境，不得依赖工作区现有 `node_modules`：

1. 把 `frontend/package.json`、`package-lock.json`、`tsconfig.json`、`vite.config.ts`、`index.html` 和 `frontend/src/**` 复制到临时目录；
2. 保留 `frontend/` 与 `app/static/workbench/` 的相对目录关系；
3. 在临时 `frontend/` 中运行 `npm ci`（不复用已有 `node_modules`）；
4. 记录 `node --version` 和 `npm --version`；
5. 运行 `npm run build`；
6. 严格递归比较临时输出与仓库中的 `app/static/workbench/`。

通过标准：

- 两个输出目录的相对文件路径集合完全一致；
- 每个对应文件的字节内容完全一致；
- 没有旧 hash asset 残留；
- `index.html` 引用的 asset 全部存在；
- asset URL 继续以 `/static/workbench/` 为 base；
- 未产生待提交的 `node_modules`、cache 或临时文件。

Vite hash 文件名不视为可忽略差异：相同源码、lockfile、配置和规范化工具链应产生相同输出；hash 文件名、`index.html` 引用或文件内容发生变化，均表示已提交产物与当前构建输入不一致。若差异来自 Node/npm 工具链漂移，应先固定并记录规范工具链版本，不得以“语义等价”为由跳过严格比较。

行为回归清单：

- [ ] `/` 显示总览，功能入口和禁用占位正确；
- [ ] `/sessions` 显示会话中心，浏览器直接刷新成功；
- [ ] `/traffic` 仍显示原代理流量页面；
- [ ] `/workbench` 兼容重定向到 `/sessions`；
- [ ] 工具筛选和搜索条件仍能刷新会话列表；
- [ ] profile 诊断和手动添加 Codex/Claude 目录仍可用；
- [ ] 全量扫描仍可执行并刷新 profile、会话和扫描摘要；
- [ ] reconcile 增量扫描仍可执行；
- [ ] 会话列表保持现有固定窗口裁剪和滚动行为；
- [ ] 选择会话后正确加载详情；
- [ ] Turn 时间线保持 user、assistant、Markdown、代码、tool、command、diff 和 unknown raw view；
- [ ] 右侧检查器保持元数据、关系、副本状态和差异摘要；
- [ ] 窄屏检查器抽屉和列表/详情导航不退化；
- [ ] FTS 状态、consent、rebuild、关闭未来索引和清空已有索引入口可用；
- [ ] loading、empty、error 和 focus 状态保持可辨识；
- [ ] `prefers-reduced-motion` 行为保持；
- [ ] 生产运行仍只需要 FastAPI 和已构建静态产物，不依赖 Node.js。

退出标准：严格构建比较通过，上述回归项全部通过，并把命令、Node/npm 版本、比较结果和已知限制写入本 Phase 执行证据。

### P1-14：全文索引默认值调整（2026-07-23 新增，修订中）

背景：P1-11 已实现"全文索引可配置开关，未确认前默认关闭"。2026-07-23 复审确认：单用户本地场景配得上"默认可用"的搜索体验，但全文复制仍需要一次真实、可拒绝的知情选择，因此改为"新实例默认建议开启，但首次构建索引前明确提示（说明本地存储位置、脱敏局限、关闭和清空方式）并允许拒绝；已有安装不自动改变现有设置"。

- [ ] 新增首次使用提示：在首次触发全文索引构建前弹出说明（存储位置、脱敏局限、如何关闭/清空），用户可选择继续或拒绝。
- [ ] 新实例默认值改为"建议开启"，但必须等用户在首次提示中确认后才真正开始写入索引；用户拒绝则保持关闭，行为等同现状。
- [ ] 已有安装升级后不自动改变当前设置，也不重新弹出首次提示。
- [ ] 更新 UI 文案，明确区分"关闭未来索引"和"清空已有索引"两个动作（P1-11 已有的两个入口不变，只调整默认值和首次提示）。
- [ ] 按下方"consent 持久化与 API 契约"实现状态模型，替换当前用 FTS 行数推导 enabled 的实现。

#### P1-14 FTS consent 持久化与 API 契约（2026-07-24 设计细化）

FTS consent 保存在 Workbench 自有 SQLite，新增单例表 `fts_settings`：

| 字段 | 类型 | 约束与含义 |
|---|---|---|
| `id` | INTEGER | 固定为 1 |
| `consent_state` | TEXT | `recommended_pending`、`user_enabled`、`user_declined`、`legacy_preserved` |
| `indexing_enabled` | INTEGER | 0/1；表示是否允许未来写入全文索引，不得由 FTS 行数推导 |
| `notice_version` | INTEGER | 最近明确接受/拒绝的提示版本，未决定为 0 |
| `decision_at` | INTEGER NULL | 最近接受或拒绝时间 |
| `origin_schema_version` | INTEGER NULL | 初始化前读到的旧 schema version |
| `updated_at` | INTEGER | 最近变更时间 |

全新数据库初始化：`consent_state = recommended_pending`、`indexing_enabled = 0`，UI 显示"建议开启"但在明确接受前不得写入 FTS，不自动 rebuild。

"全新数据库"判定规则（穷举，2026-07-24 补全）：数据库文件不存在，或数据库文件存在但既没有 `schema_meta` 表也没有任何旧业务表（`tool_profiles`/`session_copies`/`events_fts` 等）——两种情况都归类为全新实例，初始化为 `recommended_pending`。除此之外的情况（存在 `schema_meta` 或任一旧业务表）一律归类为已有安装升级，走下方 v1→v2 迁移规则。字段不存在不能直接等同于新实例，因为旧数据库升级时同样没有该字段；必须先判断数据库文件本身是否是全新创建的，再决定迁移路径。

schema v1 升级到 v2：迁移前先读取旧 `schema_version` 和 `events_fts` 行数；旧 FTS 有行则 `legacy_preserved`、`indexing_enabled = 1`；旧 FTS 无行则 `legacy_preserved`、`indexing_enabled = 0`；两种情况都不改变旧 FTS 内容、不自动 rebuild、不自动 clear、不重新弹首次提示。当前旧实现没有持久化开关，只能通过升级前 FTS 行数保留可观察到的有效行为，该限制须写入迁移说明和执行证据。

状态转换：

| 当前状态 | 动作 | 结果 |
|---|---|---|
| `recommended_pending` | 接受 | `user_enabled`，enabled=1 |
| `recommended_pending` | 拒绝 | `user_declined`，enabled=0 |
| `user_declined` | 设置页再次查看说明并接受 | `user_enabled`，enabled=1 |
| `user_enabled` | 关闭未来索引 | 状态保持，enabled=0，已有索引保留 |
| `user_enabled` 且关闭 | 再次开启 | 提示版本未变时直接 enabled=1；版本变化时重新确认 |
| 任意状态 | 清空已有索引 | consent 和 enabled 不变，只删除 FTS 行 |
| `legacy_preserved` 且关闭 | 用户主动开启 | 显示当前说明，确认后转为 `user_enabled` |

API：

- `GET /api/ai-workbench/search/status` 返回：`consent_state`、`indexing_enabled`、`recommended`、`notice_version`、`indexed_events`；
- `POST /api/ai-workbench/search/consent` 接受 `{decision: accept|decline, notice_version}`；
- `PATCH /api/ai-workbench/search/settings` 设置 `{indexing_enabled: boolean}`；
- `POST /api/ai-workbench/search/rebuild` 不得把调用本身视为 consent；consent 不足时返回 HTTP 409 `code = fts_consent_required`；已有 consent 但当前关闭时返回 HTTP 409 `code = fts_indexing_disabled`；
- `POST /api/ai-workbench/search/clear` 始终允许，且不改变 consent 或 enabled。

拒绝首次提示后仍允许用户从设置页主动开启，但必须再次显示当前版本的完整说明并获得明确确认，不能因点击 rebuild 或普通开关而隐式同意。

## 测试矩阵

- Codex/Claude：正常、归档、子代理、未知记录、截断尾行、路径失效。
- 多 profile：同 ID 同步、一个领先、双方分叉、相同 ID 假碰撞。
- 外部工具：Cockpit/CC Switch 均无、仅一个存在、均运行。
- 数据规模：至少用本机数量级验证索引与虚拟列表；测试目标 1,000 会话、100,000 事件。
- 平台：按 P0 ADR 覆盖 Windows，不承诺 Linux，见架构文档 §19。

P1-12/P1-13/P1-14 新增测试矩阵（2026-07-24）：

| 场景 | 前置条件 | 预期结果 |
|---|---|---|
| SPA 根路径 | `GET /`，Accept 含 `text/html` | 返回 workbench SPA 总览 |
| 会话路由直接刷新 | `GET /sessions`，Accept 含 `text/html` | 返回 SPA index，Vue Router 显示会话中心 |
| HEAD 路由 | `HEAD /sessions` | 状态和响应头正确，无响应体 |
| 旧路径兼容 | 访问 `/workbench` | 307 重定向到 `/sessions` |
| 代理流量迁移 | 访问 `/traffic` | 原页面、静态资源和 API 行为不变，新增返回总览链接可用 |
| API/WS/static 排除 | 请求保留路径 | 不进入 SPA fallback |
| 路径段精确排除 | 比较 `/apiary` 与 `/api/x` | 前者不被 `/api` 规则误伤，后者排除 |
| 未知文件 | `/favicon.ico`、`/assets/x.js` | 返回真实 404 |
| 非 HTML Accept | 未知无扩展名路径 | 返回真实 404 |
| P1-13 行为回归 | 完成 SFC 和模块拆分 | P1-10/P1-11 回归清单全部通过 |
| 干净构建一致性 | 临时目录 `npm ci` 后构建 | 文件路径集合和字节内容与提交产物完全一致 |
| 旧 hash 残留 | 输出目录包含旧 asset | 一致性检查失败 |
| 新实例 FTS | 全新 schema v2 DB | recommended_pending、enabled=0、不自动构建 |
| 未 consent rebuild | recommended_pending | 409 fts_consent_required，无 FTS 写入 |
| 接受/拒绝 | 分别提交 accept/decline | 状态和 enabled 正确持久化 |
| 拒绝后主动开启 | user_declined | 再次说明并确认后允许开启 |
| 关闭未来索引 | 已接受且已有索引 | 停止未来写入，已有行保留 |
| 清空已有索引 | 任意状态 | 索引行清零，consent/enabled 不变 |
| v1 有索引升级 | 旧 FTS 有行 | legacy_preserved、enabled=1、不重新提示 |
| v1 无索引升级 | 旧 FTS 无行 | legacy_preserved、enabled=0、不重新提示 |
| notice 版本升级 | 已接受旧 `notice_version`，当前版本提高 | 再启用/继续使用前要求重新确认新版本说明，不得沿用旧版本的接受记录 |

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
- 风险：全文索引会在 Workbench 自有数据库中复制 transcript 文本，最小模式脱敏不能保证识别所有敏感内容。措施：新实例仅"建议开启"，明确 consent 前有效状态保持关闭；首次提示说明存储位置、脱敏局限、关闭未来索引和清空已有索引的区别；用户可拒绝；已有安装升级时保留原有效状态且不重新提示。
- 风险：SPA catch-all 吞掉 API、WebSocket、静态资源或未知文件请求。措施：所有具体路由先注册；fallback 仅接受 GET/HEAD 和 `Accept: text/html`；按完整路径段排除 `api/static/traffic/ws`；带文件扩展名的未知路径保持 404。
- 风险：前端结构迁移改变已验收行为。措施：P1-13 只做结构迁移；使用 P1-10/P1-11 行为回归清单；不提前实现 Phase 2–5 功能。
- 风险：提交的 hash 静态产物落后于源码。措施：使用 `npm ci` 在干净临时目录构建，并对 `app/static/workbench/` 执行严格文件树和字节比较；hash 文件名差异不自动忽略。
- 风险：新前端入口影响现有代理流量页。措施：`/traffic` 与 workbench SPA 路由隔离，代理流量现有静态资源和 API 保持不变并执行回归测试。
- 回滚：P1-12 可恢复 `/` 代理流量页与 `/workbench` SPA 旧映射；P1-13 为行为不变的结构迁移，可回退到迁移前前端源码和对应构建产物；P1-14 可把 `indexing_enabled` 设为 0 并清空 FTS，不能回滚或覆盖原生 transcript。
- 回滚：删除 Workbench 自有 DB 可完全重建；原生会话和第三方目录从未修改。删除 DB 后会被视为全新实例，下一次启用全文索引仍必须重新 consent。
- 已知限制（2026-07-23 复审记录）：会话列表当前是固定窗口裁剪（渲染 70 行），不是感知容器高度的标准虚拟滚动；大规模会话下的滚动体验尚未用接近测试矩阵目标（1,000 会话）的数据量实测。验收前建议补测，不影响功能正确性。

## 审查记录

- 2026-07-23：架构复审确认 workbench 应作为前端主壳，代理流量监控迁移为子页面；新增 P1-12 描述最小改动范围的主页信息架构调整任务，状态改为 `修订中`。前端结构重构、样式统一、构建产物一致性校验列为独立技术债（见架构文档 §13.7），不纳入本次修订范围。
- 2026-07-23：确认前端结构重构的时间点——不并入 P1-12，也不作为 Phase 2 内部任务，新增 P1-13 作为 P1-12 验收后、Phase 2 批准前的独立门禁，范围限定为结构迁移且不改变现有业务行为。同批确认 Windows/Linux 支持范围（Windows 正式支持并验收，Linux 设计上可迁移但不作兼容承诺），已同步到架构文档 §10.3/§7.2/§6.3/§11.4/§18/§19、`docs/adr/0001-ai-workbench-placement.md` 和 `plans/ai-coding-workbench/03-interactive-runtime.md` P3-06。
- 2026-07-23：确认全文索引默认值调整方案（新实例默认建议开启、首次提示可拒绝、已有安装不自动改变），新增 P1-14，已同步到架构文档 §19 决策记录。§18 待讨论问题至此全部解决。
- 2026-07-24：经 Codex 分析确认 P1-12/13/14 此前只有结果性描述，缺少可直接实施的具体契约，不足以支撑“批准 Phase 1”。已补齐 P1-12 的受约束 SPA fallback 路由契约、P1-13 的构建一致性检查命令与行为回归清单、P1-14 的 FTS consent 状态模型和 API 契约；同步修正“风险与回滚”中与 P1-14 新决策矛盾的旧表述（原写“全文索引默认关闭”）；测试矩阵补充 20 项 P1-12/13/14 场景。Phase 1 状态仍为 `修订中`，本轮只补充设计细节，未获批准、未开始实施。
- 2026-07-24：经 Codex 复核纠正一处判断——`scanner.py::_needs_reindex` 只比较 size/mtime/parser_version、不比较内容哈希，在 `changed_only`/reconcile 模式下属于真实功能缺口（不只是测试覆盖缺口），已改为 P1-03 下新增的未勾选子项。同时补全 P1-14"新实例"判定规则为穷举条件（数据库文件不存在，或存在但无 `schema_meta` 与任何旧业务表）；在 P1-13 标题下加入进入条件（P1-12 完成）和实际实施顺序说明（P1-12 → P1-14 → P1-13，因 P1-13 回归清单包含 P1-14 才实现的 FTS consent 项）；测试矩阵补充 notice 版本升级重新确认场景。Phase 1 状态仍为 `修订中`。
- 2026-07-24：仓库结构迁移完成（ADR 0002，见架构文档 §19），仓库根成为 Workbench 工程根，代理流量监控迁入 `features/proxy-traffic-monitor/`，26 个测试全部通过，路由行为保持不变。此后用户明确批准 Phase 1，按 P1-12 → P1-14 → P1-13 顺序实施，状态改为 `已批准`。

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
- 2026-07-22：补齐手动目录 API、reconcile 增量扫描、scan_runs、PollingWatcher、Cockpit 白名单读取、FTS5 重建/清空/status、差异摘要和列表过滤。
- 2026-07-22：前端补齐手动 profile 添加、增量扫描、全文索引控制、虚拟会话列表、Markdown/代码/diff 基础渲染、移动端检查器抽屉和差异摘要展示。
- 2026-07-22：验证命令 `python -m pytest tests\ai_workbench\phase1 -q`，结果 `8 passed`。
- 2026-07-22：验证命令 `python -m pytest -q`，结果 `26 passed`。
- 2026-07-22：验证命令 `npm run build`，结果 Vite build succeeded。
- 2026-07-22：验证命令 `python C:\Users\YOU2\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents\skills\ai-coding-workbench`，结果 `Skill is valid!`。
- 2026-07-22：Phase 1 已达到内部退出标准，状态改为 `待验收`；不会自动进入 Phase 2。
