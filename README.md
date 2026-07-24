# AiToolbox-You

AI Coding Workbench：统一索引、查看、统计本地 Codex CLI / Claude Code 会话的工具，按 Phase 0-5 逐阶段审查和实施。仓库根即本产品的工程根，见 [`docs/adr/0002-workbench-root-and-feature-module-layout.md`](docs/adr/0002-workbench-root-and-feature-module-layout.md)。

## 当前内容

- `app/`、`frontend/`、`tests/`：AI Coding Workbench 主产品代码（Phase 1 只读会话中心已实现，`修订中`，其余 Phase 2-5 待审查）。
- [`docs/ai-coding-workbench-architecture.md`](docs/ai-coding-workbench-architecture.md)：主产品总体架构和决策记录。
- [`plans/ai-coding-workbench/`](plans/ai-coding-workbench/)：逐阶段任务、审批状态和执行证据。
- [`CONTEXT.md`](CONTEXT.md)：领域术语表（Native/Workbench 两层）。
- [`docs/verification-and-boundaries.md`](docs/verification-and-boundaries.md)：边界规则与验证方法。
- [`AGENTS.md`](AGENTS.md)：仓库协作约束和安全边界。
- [`features/proxy-traffic-monitor/`](features/proxy-traffic-monitor/)：辅助功能——Clash/Mihomo 代理与直连流量监控，已上线，挂载进主应用运行。未来新增的其他小型辅助功能同样收纳在 `features/<slug>/` 下。

尚未获得明确批准的 Phase 任务不会开始对应产品代码实现；详见 `plans/ai-coding-workbench/README.md` 的审查流程。

## 开发

```bash
uv venv .venv --python 3.12
uv pip install -r requirements.txt -r requirements-dev.txt --python .venv
.venv\Scripts\python.exe -m pytest -q
```

启动：双击根目录 `run.bat`，或 `python -m app.main`，访问 `http://127.0.0.1:8899`。

`features/proxy-traffic-monitor/` 的功能说明见其自己的 [`README.md`](features/proxy-traffic-monitor/README.md) 和 [`docs/architecture.md`](features/proxy-traffic-monitor/docs/architecture.md)。
