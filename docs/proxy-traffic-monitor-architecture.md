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

**设计约束**：双击 `run.bat` 即用，不依赖 Node.js、不使用 Vite/Webpack 等构建工具。

## 项目结构

```
proxy-traffic-monitor/
├── app/                          # 后端应用
│   ├── __init__.py
│   ├── main.py                   # FastAPI 入口，lifespan 管理
│   ├── config.py                 # 配置加载（YAML → dataclass）
│   ├── clash_client.py           # Clash API WebSocket 客户端
│   ├── collector.py              # 数据采集核心逻辑
│   ├── db.py                     # SQLite 初始化 + DDL
│   ├── repository.py             # 数据库 CRUD 操作
│   ├── api/                      # API 路由层
│   │   ├── __init__.py
│   │   ├── live.py               # WebSocket 实时推送
│   │   ├── stats.py              # 统计查询 API
│   │   └── status.py             # 连接状态 API
│   └── static/                   # 前端静态资源
│       ├── index.html            # 入口页面
│       ├── main.js               # Vue 应用入口
│       ├── App.js                # Vue 根组件
│       ├── style.css             # 全局样式（含深色模式）
│       ├── components/           # Vue 组件
│       │   ├── StatusBar.js      # 状态栏 + KPI 卡片
│       │   ├── LiveTable.js      # 实时连接表格
│       │   ├── TrafficChart.js   # 流量趋势图表
│       │   └── TopTable.js       # Top 排行表格
│       ├── utils/                # 前端工具函数
│       │   ├── format.js         # 字节/速度/时间格式化
│       │   └── labels.js         # 中文字段映射
│       └── vendor/               # 第三方库（本地）
│           ├── chart.min.js      # Chart.js
│           └── vue.esm-browser.prod.js  # Vue 3 ESM
├── tests/                        # 测试
│   ├── conftest.py               # 路径配置
│   └── test_collector.py         # 采集器单元测试
├── data/                         # 数据目录
│   └── traffic.db                # SQLite 数据库（gitignore）
├── config.yaml                   # 运行时配置（gitignore）
├── config.yaml.example           # 配置示例
├── requirements.txt              # 生产依赖
├── requirements-dev.txt          # 开发依赖（pytest）
├── run.bat                       # 一键启动脚本
└── .gitignore
```

## 后端架构

### 分层设计

```
┌─────────────────────────────────────────────┐
│                   main.py                   │  入口 + 生命周期
├─────────────────────────────────────────────┤
│         API 层 (api/*.py)                   │  路由 + 参数校验
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

#### `main.py` — 应用入口
- 使用 FastAPI `lifespan` 管理启动/关闭
- 启动时：加载配置 → 初始化数据库 → 创建 Clash 客户端 → 启动采集器
- 关闭时：停止采集器 → 关闭数据库连接
- 挂载静态文件目录，注册 API 路由

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
| GET | `/` | 前端页面 |
| GET | `/api/status` | 连接状态（connected, live_count） |
| WS | `/ws/live` | 实时连接数据推送（每秒） |
| GET | `/api/timeseries` | 流量趋势数据 |
| GET | `/api/top` | Top 排行（支持多维度） |
| GET | `/api/apps` | 已知应用列表 |
| GET | `/api/export` | CSV 导出 |

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

`config.yaml` 示例：

```yaml
clash_api:
  base_url: "127.0.0.1:9090"    # Clash API 地址
  secret: ""                     # API 密钥（可选）

server:
  listen_port: 8899              # Web 服务端口

storage:
  db_path: "./data/traffic.db"   # 数据库路径
  retention_days: 30             # 数据保留天数

collector:
  minute_flush_interval_sec: 60      # 分钟统计写入间隔
  connlog_flush_interval_sec: 10     # 连接日志写入间隔
  cleanup_interval_hours: 24         # 数据清理间隔
  ws_reconnect_backoff_sec: [1, 2, 5, 10, 30]  # 重连退避策略
```

## 启动方式

### Windows
```batch
双击 run.bat
```

### 命令行
```bash
cd proxy-traffic-monitor
python -m app.main
```

启动后访问 http://127.0.0.1:8899

## 开发指南

### 环境准备
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # 测试依赖
```

### 运行测试
```bash
pytest
```

### 前端开发
- 前端文件位于 `app/static/`
- 修改后刷新浏览器即可（无需构建）
- Vue 组件使用 ESM 模块，浏览器原生支持

## Clash 前置配置

1. 启用 `external-controller`（默认 `127.0.0.1:9090`）
2. 如有密钥，在 `config.yaml` 中设置 `clash_api.secret`
3. 设置 `find-process-mode: always` 以获取进程名
4. 重启 Clash 客户端使配置生效