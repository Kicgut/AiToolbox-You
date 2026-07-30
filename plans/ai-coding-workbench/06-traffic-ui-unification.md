# UI-06：代理流量前端统一

> 状态：已完成
> 用户授权：2026-07-31，“能统一就统一，现在只是产品开发阶段还没上线，有必要的化完全修改代理流量的前端代码也可以”
> 依赖：现有 Workbench SPA、代理流量 API 与 WebSocket 均已可用
> 范围：仅统一 `/traffic` 的前端入口、路由、布局与视觉组件；不变更采集器、SQLite 模型、Clash/Mihomo 连接方式或接口数据合同

## 目标

让 `/traffic` 成为 Workbench SPA 的一个正式路由，复用同一 `AppShell`、左侧导航、主题令牌、状态语义和响应式行为；代理流量后端仍作为 `features/proxy-traffic-monitor` 的独立挂载模块运行。

## 任务

- [x] UI6-01：将架构、功能文档与 SPA 路由边界更新为“视觉和代码统一、后端功能边界独立”。
- [x] UI6-02：移除代理流量模块对 `/traffic` 静态 HTML 的占用，使 FastAPI history fallback 可交给 Workbench SPA；保留 `/api/*`、`/ws/live`、collector 与 lifespan。
- [x] UI6-03：建立全局左侧导航和统一令牌；主 SPA 与 `/traffic` 使用相同的页面外壳。
- [x] UI6-04：实现 `TrafficView`，覆盖连接状态、KPI、小时/天/周趋势、应用/主机/链路/连接排行、实时连接、方向筛选与导出。
- [x] UI6-05：以稳定 DTO 和现有 API 实现请求、加载、空数据、断线/重连、已断开连接与错误状态；不得读取或展示 Clash API 密钥。
- [x] UI6-06：为 `/traffic` history fallback、已存在流量 API、WebSocket 降级行为和前端构建补充或运行验证。

## 非目标

- 不迁移、重写或升级 Clash/Mihomo、Collector、数据库、第三方配置或凭据。
- 不把流量数据放入 Workbench 会话/运行统计模型。
- 不实现云同步、账户体系、远程多用户或自动化任务。
- 不更改任何 Codex/Claude 真实执行门禁。

## 验收

- `/traffic` 在浏览器 history 访问与直接刷新时均由 Workbench SPA 渲染，侧栏中“代理流量”可见且激活。
- 现有 `/api/status`、`/api/timeseries`、`/api/top`、`/api/export` 与 `/ws/live` 保持合同兼容。
- 已连接、重连、数据为空、数据请求失败、未知进程及已断开连接均有独立且可访问的视觉状态。
- 前端构建、Python 全量测试和代理流量定向测试通过；不产生第三方文件写入。

## 执行证据

- `npm run build`：通过，产物已写入 `app/static/workbench/`。
- `.venv\\Scripts\\python.exe -m pytest features/proxy-traffic-monitor/tests tests/test_routing.py -q`：16 通过。
- 全量 pytest：受限环境外运行后 168 通过、1 失败；失败为既有 `test_submitted_turn_failure_does_not_silently_fallback` 的 50ms App Server 握手时序，不涉及流量路由、API 或页面。
- 浏览器检查：直接访问 `/traffic` 成功渲染 Workbench 壳；侧栏激活、排行维度切换、代理方向筛选、导出 URL 上下文和无数据解释状态均已验证。
- 边界检查：未读取或写入 Clash/Mihomo 凭据、CC Switch、Codex 或 Claude 配置；仅新建项目根 `.venv` 与 `.artifacts/tmp/` 测试临时文件。
- 回滚：恢复本计划关联提交即可将 `/traffic` 返回到原独立静态入口；后端采集器、SQLite 和 API 数据不受本次变更影响。
