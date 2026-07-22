# 代理/直连流量统计面板 — V2 规划指示文档（前端重做 + 体验完善）

> 承接 `proxy-traffic-monitor-plan.md`（V1）。V1 已实现完毕并跑通，本轮修复已发现的 bug、并针对前端做较大改造。面向负责实现代码的 agent，无需再讨论方案，直接按本文实现。

## 0. V1 代码审查结论（背景，供实现时参考）

用已接入的真实 Clash 实例验证过（`GET /api/status` 返回 `connected:true`，`GET /api/timeseries`、`/api/top` 返回了真实非零流量），后端架构与 V1 文档设计高度一致，5 个采集单测全部通过。发现问题如下：

**必须修复的 bug：**

1. `app/collector.py` 的 `_process_snapshot` 里，`start_ts=int(metadata.get("start", now))` 取错了字段。用真实 Clash API 响应核对过，`start` 是连接对象的**顶层字段**（与 `upload`/`download`/`chains` 同级），不在 `metadata` 里；`metadata.get("start", ...)` 永远取不到值，导致每条连接的 `start_ts` 每次快照都被重置成当前时间，实时表格里的"持续时长"永远显示接近 0，这是本工具明确要做的"仿 VPN 工具"核心功能之一，必须修。且真实值是 ISO-8601 字符串（如 `2026-07-03T02:10:45.28-07:00`），要解析成 epoch 秒，不能直接当数字用。

**需要用户配合但工具应主动提示的问题：**

2. 当前真实环境下 `process_name` 100% 是"未知"（`/api/apps` 只返回 `["未知"]`）。原因是 Clash 侧还没开 `find-process-mode: always`，README 里虽然写了这个前提条件，但工具本身没有任何提示，用户很容易看着面板一直是"未知"却不知道原因。这是当前"按应用排查流量"这个核心诉求实际不可用的根源，本轮要在前端加检测提示。

**代码规范性：** 分层结构（collector / repository / clash_client / db / config / api）严格对应 V1 文档拆分，职责边界清晰；`chains[-1]=='DIRECT'` 的方向判定逻辑用真实多跳数据（如 `["节点名","策略组名"]`）验证过是对的；SQLite 写锁、批量 upsert、退避重连都按文档实现，没有偷工减料。`config.yaml`（含真实 secret）正确被 `.gitignore`，只提交了 `.example`。小问题：`requirements.txt` 里没有 `pytest`（测试能跑但依赖没声明），`main.py` 的 `on_event` 已过时（FastAPI 提示改用 lifespan，暂不影响运行）。

**前端问题（用户已指出，审查确认属实）：**

3. 所有字节数（`total_up`/`speed_up`/`upload_bytes` 等）都是原始数字直接 `textContent` 显示，没有 B/KB/MB/GB 自动换算。
4. `<canvas height="200">` 只设置了初始高度，Chart.js 默认 `maintainAspectRatio:true`（宽高比 2:1）会随容器宽度把图表撑得很高，没有外层固定高度容器、也没关 `maintainAspectRatio`，这就是"小时/天/周图表占地太大"的直接原因。
5. 表格表头直接用 `process_name`、`dest_port` 等英文字段名当中文界面里的列标题，风格不统一。
6. 时间戳（`start_ts`）也是原始 epoch 数字直接展示，不可读。
7. 整体视觉是浏览器默认样式（Arial + 纯边框表格），没有配色体系、间距节奏、卡片层级。

## -1. 版本管理要求（延续 V1 规则）

继续本地 Git，按下面第 1-8 节的粒度分批提交，commit message 用简洁祈使句。仍然只做本地提交，不 push、不建分支。

## 1. Bug 修复（最高优先级，先做，其他都排在后面）

- 修 `collector.py`：`start_ts` 改为从连接对象顶层取 `conn.get("start")`，用 `datetime.fromisoformat(...).timestamp()` 解析成 epoch 秒；解析失败（字段缺失或格式异常）时兜底用 `now`，不要抛异常中断整个快照处理。
- `requirements.txt` 旁新增 `requirements-dev.txt`，内容 `pytest`，README 补一行"跑测试前先 `pip install -r requirements-dev.txt`"。
- `main.py` 的 `@app.on_event` 顺手改成 `lifespan` 写法（`@asynccontextmanager` 包住 startup/shutdown 逻辑），消除弃用警告，行为不变。

## 2. 前端技术栈：改用 Vue 3（不引入构建工具）

现状前端已经出现手写 DOM 拼接 + 状态耦合的问题（比如 `renderTopTable` 里点击一行要直接伸手改另一个 `<select>` 的 `.value` 再手动调用别的渲染函数），接下来还要加格式化、KPI 卡片、深色模式、下钻筛选联动，继续手写 DOM 只会越来越难维护。改用 Vue 3 的响应式数据绑定能显著减少这类手动同步代码。

**做法（保持"双击 run.bat 即用、不装 Node、不跑构建"这个约束不变）：**

- 从 Vue 官方下载 `vue.esm-browser.prod.js`（ESM 版本，非 UMD），放进 `app/static/vendor/vue.esm-browser.prod.js`，和现在 `chart.min.js` 的 vendor 方式一致，只是本地文件，不接 CDN。
- 前端不使用 `.vue` 单文件组件（那需要构建工具），改成用原生 `<script type="module">` + `defineComponent({...})` 的写法，一个组件一个 `.js` 文件，用 ES module `import`/`export` 相互引用，浏览器原生支持，不需要打包。
- `index.html` 只保留一个 `<div id="app"></div>` 挂载点 + `<script type="module" src="/static/main.js"></script>`。

**组件拆分：**

```
app/static/
  main.js                 # createApp(App).mount('#app')
  App.js                  # 根组件，布局 + 顶层状态（当前筛选条件、深色模式开关）
  components/
    StatusBar.js           # 连接状态 + KPI 概览卡片
    TrafficChart.js         # 趋势图（封装 Chart.js 调用）
    TopTable.js              # Top 排行表 + 维度/范围/方向筛选
    LiveTable.js              # 实时连接表
  utils/
    format.js                 # formatBytes / formatSpeed / formatDuration / formatDatetime
    labels.js                  # 字段名 -> 中文表头 映射
  vendor/
    vue.esm-browser.prod.js
    chart.min.js
```

- 组件间通信：`App.js` 持有筛选状态（当前选中的应用/连接下钻目标），通过 props 传给 `LiveTable`/`TopTable`，`TopTable` 点击某行通过 `emit` 事件通知 `App.js` 更新下钻状态，不再直接操作别的组件的 DOM。
- 实时数据：`LiveTable.js` 内部用 `onMounted` 建 WebSocket 连接，收到消息更新一个 `ref` 数组，模板里用 `v-for` 渲染，排序/筛选用 `computed` 代替手写 `sort()`+ 全量重建表格。

## 3. 数值与时间格式化（`utils/format.js`）

- `formatBytes(bytes: number): string`：按 1024 进制自动选择单位，`< 1024` 显示整数 `B`，其余保留 1-2 位小数，选到 `KB/MB/GB/TB`（如 `653.8 MB`）。
- `formatSpeed(bytesPerSec: number): string`：复用 `formatBytes` 加 `/s` 后缀（如 `1.2 MB/s`）。
- `formatDuration(seconds: number): string`：转成 `Xh Ym`、`Ym Zs` 或 `Zs` 这种就近两级单位的可读格式。
- `formatDatetime(ts: number): string`：本地时区，格式 `MM-DD HH:mm:ss`；今天的时间可以只显示 `HH:mm:ss`。
- **应用范围**：实时连接表的速度/总量/持续时长列、Top 排行表的上传/下载/总量列、图表的 Y 轴刻度（Chart.js `scales.y.ticks.callback`）和 tooltip（`plugins.tooltip.callbacks.label`）都要过这几个函数。
- **例外**：CSV 导出 (`/api/export`) 继续导出原始字节数整数，不做单位换算，方便用户拿去做二次计算/存档。

## 4. 图表尺寸与内容优化

- `TrafficChart.js` 的画布外包一层 `.chart-wrap`，CSS 固定 `height: 280px`（桌面）/`220px`（窄屏），Chart.js 配置里显式设置 `maintainAspectRatio: false`。这是解决"图表占地太大"的直接手段，必须做。
- 时间粒度切换（小时/天/周）从现在跨满一行的大按钮组，改成图表卡片右上角的小型分段控件（tab 样式，紧凑排列）。
- 默认展示简化为两个系列（代理合计 / 直连合计的堆叠柱），旁边加一个"展开上传/下载明细"开关，打开后再显示当前的四系列（直连上传/下载、代理上传/下载），避免默认视图信息过密。

## 5. 视觉风格改版

- 建立一套简单的设计变量（CSS 自定义属性放 `:root`）：主背景色、卡片背景、主文字色、次要文字色、边框色、代理色（如橙色系）、直连色（如青色系）、圆角（`8px`）、卡片阴影。
- 字体栈改为系统字体优先：`-apple-system, "Segoe UI", "Microsoft YaHei", sans-serif`（不额外引入 Web 字体，保持零依赖）。
- 顶部状态条改造成一组 KPI 卡片（横排 4 个）：**今日代理流量**、**今日直连流量**、**当前活跃连接数**、**当前总速率**（上传+下载合计），数字用第 3 节的格式化函数，卡片式布局，一眼看到关键指标，仿照 VPN 工具首页的信息密度。
- 表格样式：斑马纹、行 hover 高亮、更紧凑的 padding、表头用第 6 节的中文映射、整体包在圆角卡片容器里，替换现在纯边框表格的观感。
- 深色模式：右上角一个切换按钮，用 CSS 变量切换亮/暗两套取值 + `localStorage` 记住用户选择；不依赖系统 `prefers-color-scheme` 自动切换（避免和用户手动选择冲突），默认跟随系统一次，之后以用户手动选择为准。

## 6. 中文表头映射（`utils/labels.js`）

导出一个 `FIELD_LABELS` 对象，把 `process_name`→"应用"、`host`→"目标主机"、`dest_port`→"端口"、`network`→"协议"、`direction`→"方向"、`chain`→"节点"、`rule`→"规则"、`speed_up`→"↑速度"、`speed_down`→"↓速度"、`total_up`→"↑总量"、`total_down`→"↓总量"、`start_ts`→"开始时间"、`upload_bytes`→"上传"、`download_bytes`→"下载" 等一一映射。`LiveTable.js` 和 `TopTable.js` 渲染表头时统一查这个映射，查不到的字段名原样兜底显示。

## 7. 交互体验补充

- 空状态：实时表无活跃连接时显示"暂无活跃连接"提示行而不是空表格；图表/Top 表无数据时同理显示居中提示文案。
- 首次加载：进入页面到 WebSocket/接口返回数据之间，给一个简单的 loading 占位（骨架条或文字"加载中…"），不要求做骨架屏动画，简单够用即可。
- 响应式：`<768px` 窄屏下表格外层加 `overflow-x: auto` 允许横向滚动，KPI 卡片从横排 4 个改为 `flex-wrap` 自动换行。
- **进程名检测提示**：前端拿到 `/api/apps` 或实时连接数据后，如果发现全部/绝大多数（比如 >90%）连接的 `process_name` 都是"未知"，在状态条下方显示一条黄色提示条："未检测到应用名，请在 Clash 配置中将 `find-process-mode` 设为 `always` 后重启客户端"，帮用户定位第 0 节提到的问题 2。

## 8. 可选新功能（供选择是否本轮一起做，非强制）

- **按节点(chain)维度的 Top 排行**：`connection_log` 已经存了 `chain` 字段，`Top排行` 的维度下拉加一个"节点"选项，复用现有查询模式（`GROUP BY chain`），能看出具体是哪个代理节点扛了大部分流量。
- **按目标主机(host)维度的 Top 排行**：同理，有时流量异常是同一个应用访问了不同域名导致的，按 host 聚合更容易定位，`connection_log` 已有 `host` 字段，加一个维度选项即可。
- **实时总速率迷你趋势**：状态条 KPI 卡片"当前总速率"下面加一条极简 sparkline（用 Chart.js 的最小配置，无坐标轴），滚动展示最近 60 秒总速率，类似 VPN 客户端顶部的实时流量动画。
- **断开连接的短暂保留**：目前连接一从 `live_map` 消失就立刻从实时表格里消失，用户可能想看到"刚断开"的连接留几秒做参照。可以在前端维护一个"最近 10 秒内消失的连接"缓冲列表，渲染时带一个灰色/渐隐样式追加显示，10 秒后彻底移除；后端不需要改，纯前端状态处理。

以上四项按对用户价值排序，建议至少做前两项（节点维度、host 维度），后两项视时间/兴趣决定。

## 9. 明确不做 / 延后

- 仍不做主动阈值告警、系统托盘常驻图标、多用户鉴权（与 V1 结论一致）。
- 不引入 Vite/Webpack/TypeScript/单元测试框架（Vitest 等）：本轮 Vue 化只用浏览器原生 ESM + 官方单文件 build，保持零构建、双击即用的特性。
- 深色模式不做"跟随系统实时切换"，只做进入页面时读一次系统偏好 + 之后以用户手动选择为准，避免过度设计。

## 10. 建议实施顺序（对应 git 提交粒度）

1. 修 `start_ts` bug + 补 `requirements-dev.txt` + `main.py` lifespan 迁移（第 1 节）
2. vendor Vue ESM 文件 + 搭 `main.js`/`App.js` 空壳，先跑通"Vue 挂载但内容不变"（第 2 节前半）
3. `utils/format.js` + `utils/labels.js`，先在旧的 `app.js` 逻辑里过渡验证格式化效果正确，再迁移进 Vue 组件（第 3、6 节）
4. `LiveTable.js` 组件化 + WebSocket 接入（第 2 节后半）
5. `TrafficChart.js` 组件化 + 尺寸修复（第 4 节）
6. `TopTable.js` 组件化 + 下钻联动改用 emit（第 2 节后半）
7. `StatusBar.js` KPI 卡片 + 进程名检测提示（第 5、7 节部分）
8. 整体视觉改版（配色变量、深色模式、响应式）（第 5、7 节剩余）
9. 可选新功能（第 8 节，按优先级挑选实现）
