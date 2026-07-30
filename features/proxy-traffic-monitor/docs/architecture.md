# Proxy Traffic Monitor — 技术架构文档

## 项目概述

Proxy Traffic Monitor 是一个本地代理流量监控面板，用于实时统计 Clash/Mihomo 的代理（proxy）与直连（direct）流量。通过 WebSocket 连接 Clash API 获取实时连接数据，结合 SQLite 持久化存储，提供流量趋势图表、Top 排行、实时连接监控等功能。

## 技术栈

### 后端

| 技术 | 版本/说明 | 用途 |
|------|-----------|------|
| Python | 3.12+ | 运行环境 |
| FastAPI | Web 框架 | HTTP API + WebSocket 服务 |
| Uvicorn | ASGI 服务器 | 运行 FastAPI 应用 |
| aiosqlite | 异步 SQLite | 数据持久化 |
| websockets | WebSocket 客户端 | 连接 Clash API |
| PyYAML | YAML 解析 | 读取配置文件 |
| pytest | 测试框架 | 单元测试 |

### 前端

| 技术 | 版本/说明 | 用途 |
|------|-----------|------|
| Vue 3 | ESM 浏览器直引版 | 响应式 UI 框架（零构建） |
| Chart.js | 图表库 | 流量趋势图表 + sparkline |
| 原生 ESM | `<script type="module">` | 模块化加载，无需打包工具 |
| CSS Variables | 主题系统 | 亮色/深色模式切换 |

**设计约束**：不依赖 Node.js、不使用 Vite/Webpack 等构建工具；作为辅助功能挂载进仓库根的主应用（AI Coding Workbench），随主应用一起用根目录的 `run.bat` 一键启动，不再独立运行。

2026-07-24 起，本功能已从仓库根 `proxy-traffic-monitor/` 迁移到 `features/proxy-traffic-monitor/`，以"进程内模块"方式挂载进主应用，见 `docs/adr/0002-workbench-root-and-feature-module-layout.md`。原来独立的 `app/main.py`/`run.bat`/`requirements.txt` 已废弃，主应用的依赖清单（根目录 `requirements.txt`）已包含本功能所需的 `websockets`/`aiosqlite`/`pyyaml`。

## 项目结构

```
features/proxy-traffic-monitor/
├── proxy_traffic_monitor/        # 后端模块（挂载进主应用，不再有自己的 main.py）
│   ├── __init__.py               # mount(app)/lifespan(app) 公开接口
│   ├── config.py                 # 配置加载（YAML → dataclass）
│   ├── clash_client.py           # Clash API WebSocket 客户端
│   ├── collector.py              # 数据采集核心逻辑
│   ├── db.py                     # SQLite 初始化 + DDL
│   ├── repository.py             # 数据库 CRUD 操作
│   └── routes/                   # API 路由层
│       ├── __init__.py
│       ├── live.py               # WebSocket 实时推送
│       ├── stats.py              # 统计查询 API
│       └── status.py             # 连接状态 API
├── tests/                        # 测试
│   ├── conftest.py               # 路径配置（把本目录加入 sys.path）
│   └── test_collector.py         # 采集器单元测试
├── data/                         # 数据目录
│   └── traffic.db                # SQLite 数据库（gitignore）
├── config.yaml                   # 运行时配置（gitignore）
├── config.yaml.example           # 配置示例
├── docs/architecture.md          # 本文档
└── README.md
```

主应用如何挂载本功能：仓库根 `app/main.py` 在启动时把 `features/proxy-traffic-monitor/` 加入 `sys.path`，导入 `proxy_traffic_monitor` 包，调用 `proxy_traffic_monitor.mount(app)` 注册流量 API 与 WebSocket 路由，并在主应用的 `lifespan` 里用 `async with proxy_traffic_monitor.lifespan(app):` 包裹，让 Collector 的后台采集任务随主进程生命周期启停。`/traffic` 的页面由 Workbench SPA 提供。

## 后端架构

### 分层设计

```
┌─────────────────────────────────────────────┐
│    __init__.py (mount/lifespan 接口)         │  被主应用显式注册
├─────────────────────────────────────────────┤
│         API 层 (routes/*.py)                 │  路由 + 参数校验
├─────────────────────────────────────────────┤
│       Collector (collector.py)              │  数据采集 + 聚合
├─────────────────────────────────────────────┤
│    ClashClient (clash_client.py)            │  WebSocket 通信
├─────────────────────────────────────────────┤
│    Repository (repository.py)               │  数据库操作
├─────────────────────────────────────────────┤
│         DB (db.py) + Config (config.py)     │  基础设施
└─────────────────────────────────────────────┘
```

### 核心模块说明

#### `__init__.py` — 挂载接口
- 不再是独立的 FastAPI 应用入口；暴露 `mount(app)` 和 `lifespan(app)` 两个函数供主应用（仓库根 `app/main.py`）显式调用。
- `mount(app)`：注册 API 与 WebSocket 路由；不再挂载静态资源或注册页面路由，`/traffic` 由 Workbench SPA history fallback 提供。
- `lifespan(app)`：异步上下文管理器，启动时加载配置 → 初始化数据库 → 创建 Clash 客户端 → 启动采集器；退出时停止采集器 → 关闭数据库连接。主应用的 lifespan 用 `async with proxy_traffic_monitor.lifespan(app):` 包裹自己的逻辑来组合。

#### `config.py` — 配置管理
- 从 `config.yaml` 加载配置，支持默认值
- 配置项结构：
  - `clash_api`：Clash API 地址和密钥
  - `server`：Web 服务端口（默认 8899）
  - `storage`：数据库路径和数据保留天数
  - `collector`：采集间隔、重连退避策略

#### `clash_client.py` — Clash API 客户端
- 通过 WebSocket 连接 Clash 的 `/connections` 端点
- 支持 Bearer Token 认证
- 使用 `async for` 迭代接收实时连接数据

#### `collector.py` — 数据采集核心
- 维护三个核心数据结构：
  - `conn_states`：连接状态追踪（用于计算增量）
  - `minute_agg`：分钟级流量聚合
  - `live_map`：实时连接快照
- 关键逻辑：
  - `_process_snapshot()`：处理每次 WebSocket 消息
  - `classify_direction()`：根据 chains 判断代理/直连
  - `_parse_start_ts()`：解析 ISO-8601 时间戳
- 后台任务：
  - `_flush_minute_loop()`：每 60 秒写入分钟统计
  - `_flush_connlog_loop()`：每 10 秒写入连接日志
  - `_cleanup_loop()`：每 24 小时清理过期数据

#### `db.py` — 数据库层
- SQLite 异步连接管理
- 表结构：
  - `traffic_minute_app`：分钟级流量统计（按应用+方向聚合）
  - `connection_log`：连接日志（含完整连接信息）
- 使用 `asyncio.Lock` 保护并发写入

#### `repository.py` — 数据访问层
- 提供所有数据库操作的封装：
  - `upsert_minute_stats()`：分钟统计写入
  - `upsert_connection_log()`：连接日志写入
  - `query_timeseries()`：时间序列查询
  - `query_top_apps()`：应用排行查询
  - `query_top_connections()`：连接排行查询
  - `query_top_chains()`：节点排行查询
  - `query_top_hosts()`：目标主机排行查询
  - `delete_older_than()`：过期数据清理

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/traffic` | Workbench SPA 前端页面 |
| GET | `/api/status` | 连接状态（connected, live_count） |
| WS | `/ws/live` | 实时连接数据推送（每秒） |
| GET | `/api/timeseries` | 流量趋势数据 |
| GET | `/api/top` | Top 排行（支持多维度） |
| GET | `/api/apps` | 已知应用列表 |
| GET | `/api/export` | CSV 导出 |

以上路径由 `mount(app)` 注册进主应用，与迁移前完全一致（结构迁移不改变路由语义）。`/` 会在 Phase 1 的 P1-12 任务实施后改为 `/traffic`（届时 `/` 交给 workbench SPA 总览页），这是单独批准的 Phase 1 工作，不随本次结构迁移变化。

> 更新（2026-07-31）：页面入口 `/traffic` 已迁移到 Workbench SPA。`mount()` 现只注册本功能的 API 与 WebSocket；Collector、数据库与数据合同不因此改变。本段前的旧路由说明仅保留为结构迁移历史。

### 数据库表结构

#### `traffic_minute_app` — 分钟级流量统计
```sql
CREATE TABLE traffic_minute_app (
    minute_ts INTEGER,        -- 分钟时间戳
    process_name TEXT,        -- 进程名
    direction TEXT,           -- proxy / direct
    upload_bytes INTEGER,
    download_bytes INTEGER,
    PRIMARY KEY (minute_ts, process_name, direction)
);
```

#### `connection_log` — 连接日志
```sql
CREATE TABLE connection_log (
    id TEXT PRIMARY KEY,      -- 连接 ID
    process_name TEXT,        -- 进程名
    host TEXT,                -- 目标主机
    dest_port INTEGER,        -- 目标端口
    network TEXT,             -- tcp / udp
    direction TEXT,           -- proxy / direct
    chain TEXT,               -- 代理链
    rule TEXT,                -- 匹配规则
    start_ts INTEGER,         -- 连接开始时间
    last_seen_ts INTEGER,     -- 最后活跃时间
    upload_bytes INTEGER,
    download_bytes INTEGER
);
```

## 前端架构

### 组件结构

```
App.js (根组件)
├── StatusBar.js    (状态栏)
├── TrafficChart.js (流量图表)
├── TopTable.js     (Top 排行)
└── LiveTable.js    (实时连接)
```

### Vue 3 使用方式

- 使用 Vue 3 ESM 浏览器直引版本（`vue.esm-browser.prod.js`）
- 组件使用 Options API 的 `setup()` 函数
- 通过 `<script type="module">` 加载，浏览器原生支持
- 无需构建工具，保持零配置

### 组件说明

#### `App.js` — 根组件
- 管理全局状态：实时数据、深色模式、断连缓冲
- 建立 WebSocket 连接并分发数据给子组件
- 实现深色模式切换（localStorage 持久化）

#### `StatusBar.js` — 状态栏
- 显示连接状态指示灯
- 显示活跃连接数和当前总速率
- 60 秒速率 sparkline 迷你图表
- 进程名检测警告（>90% 为"未知"时提示）

#### `TrafficChart.js` — 流量图表
- Chart.js 柱状图，堆叠显示代理/直连的上传/下载
- 支持小时/天/周三种粒度切换
- 空数据和加载状态处理

#### `TopTable.js` — Top 排行
- 支持四种维度：应用、连接、节点、目标主机
- 支持时间范围：1 小时、今天、7 天、30 天
- 支持方向过滤和排序方式
- 点击行可下钻到实时连接
- CSV 导出功能

#### `LiveTable.js` — 实时连接
- 实时显示活跃连接列表
- 支持排序和方向过滤
- 断连缓冲：断开的连接保留 10 秒（渐隐样式）
- 空状态提示

### 工具模块

#### `utils/format.js` — 格式化函数
- `formatBytes()`：字节 → 人类可读（B/KB/MB/GB）
- `formatSpeed()`：速度格式化（B/s, KB/s...）
- `formatDuration()`：时长格式化（时分秒）
- `formatTimestamp()`：时间戳 → 本地时间字符串

#### `utils/labels.js` — 中文映射
- 字段名 → 中文标签映射表
- 支持表头和 UI 元素的本地化

### 样式系统

- 使用 CSS Variables 实现主题切换
- 亮色/深色两套配色方案
- 响应式设计（<768px 移动端适配）
- 卡片式布局，圆角阴影

## 数据流

```
Clash API (WebSocket)
       │
       ▼
  ClashClient ──► Collector
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
    live_map     minute_agg   connection_log
   (内存实时)    (内存聚合)    (SQLite)
         │
         ▼
  /ws/live (WebSocket)
         │
         ▼
    Vue 前端组件
         │
         ▼
    用户界面
```

## 配置说明

配置文件位于本功能目录下（`features/proxy-traffic-monitor/config.yaml`，由 `load_config()` 默认读取），路径相对于主应用进程的工作目录（仓库根）解析：

```yaml
clash_api:
  base_url: "127.0.0.1:9090"    # Clash API 地址
  secret: ""                     # API 密钥（可选）

server:
  listen_port: 8899              # Web 服务端口（仅文档用途；实际监听端口由主应用 uvicorn 启动参数决定）

storage:
  db_path: "./features/proxy-traffic-monitor/data/traffic.db"   # 数据库路径
  retention_days: 30             # 数据保留天数

collector:
  minute_flush_interval_sec: 60      # 分钟统计写入间隔
  connlog_flush_interval_sec: 10     # 连接日志写入间隔
  cleanup_interval_hours: 24         # 数据清理间隔
  ws_reconnect_backoff_sec: [1, 2, 5, 10, 30]  # 重连退避策略
```

## 启动方式

本功能不再独立启动，随主应用（仓库根 `app/main.py`）一起运行：

### Windows
```batch
双击仓库根目录的 run.bat
```

### 命令行
```bash
cd E:\statistics-toolbox-You
python -m app.main
```

启动后访问 http://127.0.0.1:8899

## 开发指南

### 环境准备
在仓库根目录（不是本功能目录）安装依赖，本功能所需的 `websockets`/`aiosqlite`/`pyyaml` 已合并进根 `requirements.txt`：
```bash
uv venv .venv --python 3.12
uv pip install -r requirements.txt -r requirements-dev.txt --python .venv
```

### 运行测试
在仓库根目录运行；也可只运行本功能自己的测试：
```bash
python -m pytest features/proxy-traffic-monitor/tests -q
```

### 前端开发
- 前端视图位于 `frontend/src/views/TrafficView.vue`，随 Workbench Vite 构建输出到 `app/static/workbench/`
- 修改后运行 `npm run build`，由 FastAPI 分发构建产物

## 视觉与交互设计提案（2026-07-31，待审查）

页面仍作为 `/traffic` 的独立辅助功能，但 2026-07-31 经用户授权，视图迁移到 Workbench SPA 的 Vue Router，以复用左侧导航、主题令牌、图标和响应式布局。Collector、SQLite、REST/WebSocket 接口与 `mount()`/`lifespan()` 生命周期仍由本功能维护；页面不访问 Workbench 的会话、运行或统计存储。

推荐的页面层级如下：

```text
返回工作台 / 标题 / Clash-Mihomo 与采集器状态 / 主题
总流量、代理占比、直连占比、实时连接数
流量趋势（小时、天、周；上传、下载；代理、直连） / 状态摘要
排行（应用、主机、链路、连接） / 实时连接表
```

- 头部必须显示“返回工作台”、最近刷新时间和当前 WebSocket/采集器状态。已连接、重连中、已断开、数据滞后均使用文字、图标和颜色。
- 流量趋势继续使用现有 `hour`、`day`、`week` 粒度和 `/api/timeseries` 数据；四条序列固定为直连上传、直连下载、代理上传、代理下载，并通过一致图例区分。加载、空数据和请求错误分别呈现。
- `/api/top` 已支持应用、主机、链路、连接四种维度。前端以 tabs 展示，并在一次钻取后只过滤实时连接表；历史统计范围不因钻取而被隐式改变。
- 实时连接表以 `/ws/live` 为唯一实时来源。短暂保留的断开连接必须标为“已断开”，不得伪装为活跃；方向筛选、当前连接数和重连提示放在表格标题区域。
- 导出按钮必须继承可见的粒度、范围、方向、应用与排行维度条件；不导出未显示或未声明的数据。
- 未识别的进程、主机或链路显示“未知”及其来源限制；页面不展示、不记录、也不要求用户输入 Clash API 密钥。

完整的跨页面视觉规范见 `docs/ai-coding-workbench-visual-design.md`。本节是设计沟通材料，不代表页面功能已经通过验收。

## Clash 前置配置

1. 启用 `external-controller`（默认 `127.0.0.1:9090`）
2. 如有密钥，在 `config.yaml` 中设置 `clash_api.secret`
3. 设置 `find-process-mode: always` 以获取进程名
4. 重启 Clash 客户端使配置生效
