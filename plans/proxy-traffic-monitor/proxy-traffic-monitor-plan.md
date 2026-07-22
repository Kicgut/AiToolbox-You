# 代理/直连流量统计面板 — 规划指示文档

> 本文档面向负责实现代码的 agent/开发者。已通过需求澄清确认技术选型，无需再讨论方案，直接按本文实现。

## -1. 版本管理要求（最优先，先于一切代码工作）

- 开始实现前，先在项目目录（`proxy-traffic-monitor/`）执行 `git init`，建立本地 Git 仓库。
- 首次提交前先添加 `.gitignore`，至少排除：`venv/`、`__pycache__/`、`*.pyc`、`data/`（SQLite 数据库文件及运行时数据不入库）、`config.yaml` 中若含真实 `secret` 的本地副本可保留示例文件 `config.yaml.example` 入库、真实 `config.yaml` 忽略。
- 之后按开发阶段**及时本地提交**，不要攒到最后一次性提交。建议的提交粒度对应本文档的章节拆分，例如：
  1. 项目骨架 + 配置加载（第 1、3 节）
  2. 数据库表结构 + 数据读写层（第 2、6 节）
  3. Clash 客户端 + 采集核心 Collector（第 4、5 节）
  4. API 层（第 7 节）
  5. 前端面板（第 8 节）
  6. 部署文件 + README（第 10 节）
  7. 测试（第 11 节）
- 每个阶段完成、可运行/可通过测试后再提交，commit message 用简洁祈使句说明这次做了什么（例如 `add collector minute aggregation logic`），不要求遵循特定规范，但不要写空泛的 `update` `fix`。
- 全程只做**本地** Git 管理（`git add` / `git commit`），不涉及远程仓库、不需要 `git push`、不需要创建分支，除非用户后续另行要求。

## 0. 背景与目标

用户本机已运行 Clash Verge / Clash for Windows / Mihomo 作为代理客户端，部分流量走代理、部分走直连（分流规则由 Clash 自己决定）。用户需要一个本地小工具：

1. 按小时/天/周统计走代理与走直连的流量。
2. 不只是总量，要能按**应用（进程）**和**单条连接**拆分，用于排查“是谁/哪个连接导致流量异常”。
3. 展示实时连接列表（仿 VPN 客户端的连接页面）。

技术路线：直接读取 Clash/Mihomo 自带的 RESTful/WebSocket API（`/connections`），**不做任何抓包**。技术栈：Python + FastAPI + SQLite，单进程运行，浏览器打开本地网页查看。

## 1. 项目结构

```
proxy-traffic-monitor/
  app/
    __init__.py
    main.py              # FastAPI 入口，startup/shutdown 生命周期
    config.py            # 配置加载
    clash_client.py       # Clash/Mihomo WebSocket 客户端封装
    collector.py           # 核心采集与内存聚合逻辑
    db.py                    # SQLite 建表与连接管理
    repository.py            # 数据读写函数（upsert / 查询）
    api/
      __init__.py
      live.py               # WS /ws/live
      stats.py               # REST 统计接口
      status.py              # 健康状态接口
    static/
      index.html
      app.js
      style.css
      vendor/chart.min.js   # 本地打包 Chart.js，不依赖 CDN
  tests/
    test_collector.py
  config.yaml
  requirements.txt
  run.bat
  README.md
```

## 2. 数据模型（SQLite，`db.py`）

```sql
CREATE TABLE IF NOT EXISTS traffic_minute_app (
    minute_ts INTEGER,      -- 整分钟 epoch 时间戳
    process_name TEXT,      -- 进程名，取不到时存 '未知'
    direction TEXT,          -- 'direct' | 'proxy'
    upload_bytes INTEGER NOT NULL DEFAULT 0,
    download_bytes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (minute_ts, process_name, direction)
);
CREATE INDEX IF NOT EXISTS idx_minute ON traffic_minute_app(minute_ts);

CREATE TABLE IF NOT EXISTS connection_log (
    id TEXT PRIMARY KEY,     -- Clash 连接 id
    process_name TEXT,
    host TEXT,
    dest_port INTEGER,
    network TEXT,              -- tcp/udp
    direction TEXT,
    chain TEXT,                 -- 实际代理节点/策略名，direct 时为 'DIRECT'
    rule TEXT,                   -- 命中的分流规则
    start_ts INTEGER,
    last_seen_ts INTEGER,
    upload_bytes INTEGER NOT NULL DEFAULT 0,
    download_bytes INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_conn_lastseen ON connection_log(last_seen_ts);
```

`db.py` 需提供：
- `async def init_db(path: str) -> aiosqlite.Connection`：确保目录存在、建表、返回连接（aiosqlite 单连接即可，写操作用锁串行化，避免并发写冲突）。

## 3. 配置（`config.py` + `config.yaml`）

```yaml
clash_api:
  base_url: "127.0.0.1:9090"
  secret: ""
server:
  listen_port: 8899
storage:
  db_path: "./data/traffic.db"
  retention_days: 30
collector:
  minute_flush_interval_sec: 60
  connlog_flush_interval_sec: 10
  cleanup_interval_hours: 24
  ws_reconnect_backoff_sec: [1, 2, 5, 10, 30]   # 重连退避序列，到最后一档后循环
```

`config.py`：
- `@dataclass class Config`：对应上述字段的扁平化属性。
- `def load_config(path="config.yaml") -> Config`：读取 YAML，缺省值兜底，文件不存在则用全默认值启动并给出警告日志。

## 4. Clash 客户端（`clash_client.py`）

- `class ClashClient`
  - `__init__(self, base_url: str, secret: str)`
  - `async def connect_connections_ws(self) -> AsyncIterator[dict]`：连接 `ws://{base_url}/connections`（若 `secret` 非空，按 query param `?token=` 或 `Authorization: Bearer` header 传递，需实现时确认 Mihomo 当前版本的鉴权方式，两种都做兼容尝试），持续 `yield` 每条推送消息（JSON 解析后的 dict，含 `connections: [...]` 和整体 `downloadTotal/uploadTotal`）。
  - 连接失败或中途断开时抛出异常，由上层 `Collector` 负责重连循环；本类不内置重试。

## 5. 采集核心（`collector.py`）— 本项目最核心的模块

### 5.1 数据结构

- `@dataclass class ConnState`：`last_upload: int, last_download: int, first_seen: bool`，per-connection-id 记录上一次快照的累计值。
- `@dataclass class LiveConn`：给前端实时表格用的单条连接展示结构：`id, process_name, host, dest_port, network, direction, chain, rule, speed_up, speed_down, total_up, total_down, start_ts`。

### 5.2 `class Collector`

- `__init__(self, clash_client, db_conn, config)`：初始化内存态：
  - `self.conn_states: dict[str, ConnState] = {}`
  - `self.minute_agg: dict[tuple[int, str, str], list[int, int]] = {}`  # key=(minute_ts, process_name, direction) → [up, down]
  - `self.live_map: dict[str, LiveConn] = {}`
  - `self.connected: bool = False`
  - `self.last_update_ts: float = 0`

- `async def run(self)`：主循环。使用配置里的退避序列反复尝试 `clash_client.connect_connections_ws()`；成功后遍历消息调用 `self._process_snapshot(msg, now=time.time())`；异常时 `self.connected=False`，按退避等待后重连；同时在 `run()` 启动时用 `asyncio.gather` 拉起三个后台循环任务：`_flush_minute_loop`、`_flush_connlog_loop`、`_cleanup_loop`（这三个循环独立于 WS 连接状态常驻运行）。

- `def _process_snapshot(self, msg: dict, now: float) -> None`：核心处理函数，每次收到快照调用一次。
  1. `self.connected = True; self.last_update_ts = now`
  2. `seen_ids = set()`
  3. 遍历 `msg["connections"]`：
     - 取 `cid = conn["id"]`，加入 `seen_ids`
     - `cur_up, cur_down = conn["upload"], conn["download"]`（累计值）
     - `process_name = conn["metadata"].get("process") or "未知"`
     - `host = conn["metadata"].get("host") or conn["metadata"].get("destinationIP")`
     - `network = conn["metadata"].get("network", "tcp")`
     - `direction = self.classify_direction(conn.get("chains", []))`
     - `chain = conn["chains"][0] if conn.get("chains") else "DIRECT"`（Mihomo 的 chains 数组顺序需在实现时用真实响应确认展示哪一层最合适，取最終使用的节点名）
     - `rule = conn.get("rule", "")`
     - 计算增量：若 `cid` 不在 `self.conn_states`（首次见到）→ `delta_up = delta_down = 0`，只记录基线，避免把连接建立前的历史累计值一次性算进本分钟；否则 `delta_up = max(0, cur_up - prev.last_upload)`，`delta_down` 同理（负数说明计数器被重置，钳为 0）
     - 更新 `self.conn_states[cid] = ConnState(cur_up, cur_down, first_seen=False)`
     - 累加进分钟聚合：`minute_key = (int(now // 60 * 60), process_name, direction)`，`self.minute_agg.setdefault(minute_key, [0,0])` 后 `+= (delta_up, delta_down)`
     - 计算速率：`elapsed = now - getattr(self.live_map.get(cid), '_last_ts', now)`（或用固定假设间隔，实现时取实际时间差更准确），`speed_up = delta_up / max(elapsed, 0.1)`
     - 更新/新建 `self.live_map[cid] = LiveConn(...)`
  4. 处理已关闭的连接：`closed_ids = set(self.live_map) - seen_ids`，从 `self.live_map` 中移除（`conn_states` 可保留一小段时间或直接一并清理，实现时选简单方案：一并删除）

- `@staticmethod def classify_direction(chains: list[str]) -> str`：`return "direct" if chains and chains[-1] == "DIRECT" else "proxy"`（需要用真实 Mihomo 响应确认 DIRECT 出现在数组的哪个位置，实现时用一次真实抓包核对再定最终判断表达式）。

- `async def _flush_minute_loop(self)`：`while True: await asyncio.sleep(cfg.minute_flush_interval_sec); await repository.upsert_minute_stats(db, self.minute_agg); self.minute_agg.clear()`

- `async def _flush_connlog_loop(self)`：`while True: await asyncio.sleep(cfg.connlog_flush_interval_sec); await repository.upsert_connection_log(db, self.live_map, self.conn_states)`（把当前 live_map 中每条连接的最新累计值、host、direction 等写入/更新 `connection_log` 表）

- `async def _cleanup_loop(self)`：`while True: await asyncio.sleep(cfg.cleanup_interval_hours * 3600); await repository.delete_older_than(db, cfg.retention_days)`

- `def get_live_snapshot(self) -> list[dict]`：把 `self.live_map.values()` 转成给前端的 JSON 友好 list（供 WS 推送和 `/api/status` 兜底展示）。

- `def get_status(self) -> dict`：`{"connected": self.connected, "last_update_ts": self.last_update_ts, "live_count": len(self.live_map)}`

### 5.3 边界情况（实现时需处理）

- Clash 未启动/连不上：`connected=False`，前端顶部提示，历史统计接口仍正常可用。
- 计数器重置/负数增量：钳为 0，不写入负值。
- `process` 字段为空：归入 `"未知"`，不报错。
- 长连接（几小时不断开）：靠分钟级增量累加已能正确按时间分布，不会在断开时产生假峰值。

## 6. 数据读写（`repository.py`）

- `async def upsert_minute_stats(db, agg: dict) -> None`：对 `agg` 中每个 `(minute_ts, process, direction) -> [up, down]`，执行：
  ```sql
  INSERT INTO traffic_minute_app (minute_ts, process_name, direction, upload_bytes, download_bytes)
  VALUES (?, ?, ?, ?, ?)
  ON CONFLICT(minute_ts, process_name, direction)
  DO UPDATE SET upload_bytes = upload_bytes + excluded.upload_bytes,
                download_bytes = download_bytes + excluded.download_bytes;
  ```
  用 `executemany` 批量执行后 `commit()`。

- `async def upsert_connection_log(db, live_map, conn_states) -> None`：对每条活跃连接 `INSERT ... ON CONFLICT(id) DO UPDATE SET last_seen_ts=excluded.last_seen_ts, upload_bytes=excluded.upload_bytes, download_bytes=excluded.download_bytes, direction=excluded.direction, chain=excluded.chain, rule=excluded.rule`（`start_ts` 只在首次插入时写入，用 `INSERT OR IGNORE` 先插入基础行，或在 `ON CONFLICT` 中不覆盖 `start_ts`）。

- `async def query_timeseries(db, granularity: str, start_ts: int, end_ts: int, direction: str|None, app: str|None) -> list[dict]`：
  - `hour`：`GROUP BY (minute_ts / 3600) * 3600`
  - `day`：`GROUP BY date(minute_ts, 'unixepoch', 'localtime')`
  - `week`：`GROUP BY strftime('%Y-%W', minute_ts, 'unixepoch', 'localtime')`
  - 返回每个桶的 `{ts, direct_upload, direct_download, proxy_upload, proxy_download}`（用 `SUM(CASE WHEN direction='direct' THEN upload_bytes ELSE 0 END)` 之类的条件聚合，一次查询出两个方向）
  - `app` 非空时加 `WHERE process_name = ?`

- `async def query_top_apps(db, start_ts, end_ts, direction: str|None, sort: str, limit: int) -> list[dict]`：按 `process_name[, direction]` 分组求和 `traffic_minute_app`，按 `sort`（upload/download/total）降序取前 `limit`。

- `async def query_top_connections(db, start_ts, end_ts, direction: str|None, sort: str, limit: int) -> list[dict]`：从 `connection_log` 按 `last_seen_ts BETWEEN` 过滤，按总字节数排序取前 `limit`，返回含 `process_name, host, direction, chain, upload_bytes, download_bytes, start_ts, last_seen_ts`。

- `async def query_distinct_apps(db) -> list[str]`：`SELECT DISTINCT process_name FROM traffic_minute_app ORDER BY process_name`。

- `async def delete_older_than(db, retention_days: int) -> None`：删除两张表中早于 `now - retention_days*86400` 的记录，`VACUUM` 视情况可选（数据量不大可不做，避免锁表耗时）。

## 7. API 层

### 7.1 `api/live.py`
- `@router.websocket("/ws/live")`：accept 后 `while True: await ws.send_json(collector.get_live_snapshot()); await asyncio.sleep(1)`，捕获 `WebSocketDisconnect` 正常退出循环。

### 7.2 `api/stats.py`
- `GET /api/timeseries?granularity=hour|day|week&start=&end=&direction=&app=`
  → 调 `repository.query_timeseries`，响应 `{"buckets": [...]}`。`start`/`end` 为 epoch 秒，缺省按 `granularity` 给合理默认范围（hour→近24小时，day→近7天，week→近8周）。
- `GET /api/top?dimension=app|connection&range=1h|today|7d|30d&direction=&sort=total&limit=20`
  → 把 `range` 转成 `start_ts/end_ts`，按 `dimension` 分派到 `query_top_apps` 或 `query_top_connections`。
- `GET /api/apps` → `query_distinct_apps`。
- `GET /api/export?...`（CSV 导出，复用 timeseries/top 的参数与查询函数）→ `StreamingResponse`，`media_type="text/csv"`，用 `csv.writer` 写入内存 `io.StringIO`。

### 7.3 `api/status.py`
- `GET /api/status` → `collector.get_status()`。

## 8. 前端（`static/`）

`index.html` 三段式布局 + 顶部状态条，`app.js` 提供：

- `connectLiveWS()`：建立 `/ws/live` 连接，`onmessage` 调 `renderLiveTable(JSON.parse(evt.data))`；`onclose` 时定时重连。
- `renderLiveTable(connections)`：渲染实时连接表，表头可点击排序，顶部有方向筛选（全部/仅代理/仅直连）下拉。
- `fetchTimeseries(granularity, range, direction, app)` + `renderChart(data)`：调用 `/api/timeseries`，用 Chart.js 画直连/代理堆叠柱状图/面积图，粒度切换 Tab（小时/天/周）。
- `fetchTop(dimension, range, direction, sort)` + `renderTopTable(data)`：Top 排行表，行内“应用/节点名”可点击 → 触发下钻，过滤实时表/连接明细。
- `exportCSV(endpoint, params)`：拼 URL 触发浏览器下载。
- `pollStatus()`：轮询 `/api/status`（如 5s 一次），更新顶部连接状态指示灯。

`vendor/chart.min.js`：从 Chart.js 官方发行版下载后直接放入项目，前端 `<script src="/static/vendor/chart.min.js">` 本地引用，不依赖 CDN。

## 9. `main.py`

- 创建 `FastAPI()` 实例，`app.mount("/static", StaticFiles(...))`，根路径 `/` 返回 `index.html`。
- `include_router` 挂载 `live.py` / `stats.py` / `status.py`。
- `@app.on_event("startup")`：`load_config()` → `init_db()` → 构造全局 `Collector` 实例（挂到 `app.state.collector`）→ `asyncio.create_task(collector.run())`。
- `@app.on_event("shutdown")`：取消后台任务、关闭数据库连接。
- 入口：`if __name__ == "__main__": uvicorn.run(app, host="127.0.0.1", port=cfg.server.listen_port)`。

## 10. 部署文件

- `requirements.txt`：`fastapi`, `uvicorn[standard]`, `websockets`, `aiosqlite`, `pyyaml`。
- `run.bat`：检测 `venv` 是否存在 → 不存在则 `python -m venv venv` 并 `pip install -r requirements.txt`；存在则直接激活运行 `python -m app.main`。
- `README.md` 需包含前置条件说明：
  1. Clash Verge/Mihomo 设置里确认 `external-controller` 已开启（默认 `127.0.0.1:9090`）。
  2. 若客户端设置了 `secret`，需填入 `config.yaml` 的 `clash_api.secret`。
  3. 务必将核心配置的 `find-process-mode` 设为 `always`，否则拿不到应用名，所有连接会归入“未知”。
  4. 双击 `run.bat` 启动后浏览器打开 `http://127.0.0.1:8899`。

## 11. 测试要点（`tests/test_collector.py`）

- `classify_direction`：给不同 `chains` 数组样例，断言 direct/proxy 判定正确。
- 增量计算：构造两次连续快照（同一个 `cid`，累计值递增），断言 `minute_agg` 中的增量等于两次快照差值；构造计数器回退（模拟重置）场景，断言增量被钳为 0 而不是负数。
- 分钟分桶边界：构造跨分钟边界的两次快照时间戳，断言落入不同的 `minute_ts` key。
- 连接消失处理：构造快照 A 含连接 X，快照 B 不含 X，断言 X 从 `live_map` 中被移除。
- 手动联调（无法自动化，需人工执行一次）：真实连上本机 Clash Verge，分别产生走代理和走直连的流量（如 `curl` 指定/不指定代理），核对实时表格分类、趋势图数值与 Clash Verge 自带面板的总量大致吻合。

## 12. 明确不做（Out of scope）

- 主动阈值告警/通知。
- 系统托盘常驻图标、开机自启动注册。
- 多用户鉴权/登录（仅监听 `127.0.0.1`，本机访问）。
- 非 Clash/Mihomo 内核（V2rayN 等）的适配。
