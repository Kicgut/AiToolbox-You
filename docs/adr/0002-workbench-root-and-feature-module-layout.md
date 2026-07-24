# ADR 0002：仓库以 AI Coding Workbench 为主产品，辅助功能收纳进 `features/`

日期：2026-07-24

状态：已确认（架构决策已批准；物理迁移作为独立任务执行，见下方"迁移排期"，执行前不代表本 ADR 未生效）

取代：`docs/adr/0001-ai-workbench-placement.md` 中关于 Phase 0 代码放置的决定（"Phase 0 code lives under `proxy-traffic-monitor/app/ai_workbench/`"）。ADR 0001 其余内容（数据目录规则等）仍然有效，作为历史记录保留，不做回溯修改。

## 背景

仓库当前的物理结构和产品的实际主从关系是反的：AI Coding Workbench（Phase 0-5 完整路线图——会话中心、统计中心、交互式运行、自动任务、跨 profile 迁移）是用户长期投入的主产品，但代码却嵌在 `proxy-traffic-monitor/app/ai_workbench/` 里——`proxy-traffic-monitor` 本来是一个代码量有限、职责单一、已经稳定上线的辅助工具。用户明确指出这个命名/结构已经不能准确反映实际情况，并说明未来还会持续新增其他辅助功能，这些新功能同样是"小、专一、简单"性质，不是与 Workbench 同等规模的独立大产品。

产品/UI 层面其实已经确立了主从关系：2026-07-23/24 的 P1-12 设计（`plans/ai-coding-workbench/01-read-only-session-center.md`）把 workbench SPA 定为前端主壳（根路径 `/` 的总览页），代理流量监控降级为从总览跳转出去的子页面（`/traffic`）。这份 ADR 让代码目录结构镜像这个已经确立的产品关系，而不是继续维持"大壳套小 workbench"的历史遗留结构。

## 决策

1. **仓库根即 Workbench 工程根。** 不再引入 `products/` 或 `ai-coding-workbench/` 这类包装目录。`app/`、`frontend/`、`tests/` 从 `proxy-traffic-monitor/` 提升到仓库根。

2. **辅助功能统一收纳进 `features/<slug>/`。** `proxy-traffic-monitor` 降级为 `features/proxy-traffic-monitor/`，以"挂载在主产品上、边界清晰的辅助功能"形式存在：暴露 router 和生命周期接口，由主 app 显式注册，不并入 `app/ai_workbench`。

3. **未来新增辅助功能的标准模式（技术栈无关）**，三选一：
   - **A. Python 进程内模块**：暴露 router + 生命周期接口，主 app 显式注册（当前 `features/proxy-traffic-monitor/` 采用此模式）。
   - **B. 静态子应用**：功能自带前端构建工具链，只把构建产物交给主 FastAPI 分发。
   - **C. 本地独立进程**：适用于非 Python 技术栈或依赖冲突场景，主壳只负责启动链接和状态展示，不做进程内集成。

4. **依赖策略。** 主产品保留自己的 uv 管理虚拟环境；简单辅助功能可复用主环境；复杂或容易依赖冲突的功能自建独立 uv 环境。不预先搭建共享 SDK/组件库；只有当至少两个已稳定的功能出现真实重复需求、且能形成版本化契约时才考虑抽取共享层。

5. **文档治理体系不对称。** 根 `AGENTS.md`/`CONTEXT.md` 同时承担仓库级治理和主产品治理（因为仓库事实身份就是主产品，不是两者平级）。辅助功能默认不配对等的 `AGENTS.md`/`CONTEXT.md`，只有涉及独立安全边界或独立技术栈时才按需增加轻量说明（README 为主）。`docs/adr/` 保持单一目录，靠文件名区分作用域，不按功能拆子目录。`plans/<slug>/` 只用于受 Phase 审批门禁约束的主产品（`plans/ai-coding-workbench/`）；已上线的辅助功能（`plans/proxy-traffic-monitor/` 现有的 3 份历史计划）保留原状，标记为历史记录，不受当前 Phase 门禁约束，也不要求持续维护。

## 迁移排期

本 ADR 只确认结构决策，不代表迁移已执行。物理迁移作为一次独立任务，按以下顺序执行，且必须在继续 Phase 1 的 P1-12/P1-14/P1-13 之前完成（2026-07-24 确认，避免先在旧结构上实现路由契约、之后又要因迁移返工）：

1. 把 `proxy-traffic-monitor/app/ai_workbench/`、`frontend/`、`tests/ai_workbench/` 提升到仓库根对应位置。
2. 把 `proxy-traffic-monitor/` 里流量监控自身的代码（`collector.py`、`clash_client.py`、`db.py`、`repository.py`、路由、静态资源）迁入 `features/proxy-traffic-monitor/`。
3. 反转 FastAPI 组合与 lifespan 归属权：Workbench 成为真正的主 app，流量监控通过显式接口注册进主 app，不再是反过来的关系。这是唯一改变运行时结构的步骤，风险最高，需要完整回归测试。
4. 更新所有引用旧路径 `proxy-traffic-monitor/...` 的文件：`AGENTS.md`、`docs/ai-coding-workbench-architecture.md`、`plans/ai-coding-workbench/*.md`、`CONTEXT.md`、`docs/verification-and-boundaries.md`、`.agents/skills/ai-coding-workbench/SKILL.md`、`run.bat`、`config.yaml`、`tests/conftest.py`。
5. 完成迁移和回归验证后，再恢复 Phase 1 实施：P1-12 → P1-14 → P1-13。

## 后果

- 流量监控的 API/WS 路径会变化（如 `/api/status` → `/api/features/proxy-traffic-monitor/status`）；本项目是本地单用户工具，没有外部 API 消费者依赖旧路径，倾向于直接切换而不做兼容别名，具体是否保留兼容别名在执行迁移任务时另行确认。
- 迁移期间 `docs/adr/0001-ai-workbench-placement.md` 中的路径描述已成为历史事实（描述的是 Phase 0 当时的决定），不追溯修改，但本 ADR 的"取代"关系需要在该文件顶部补充一行"Status: Superseded by ADR 0002"提示。
- 迁移涉及的文件数量和路径引用较多（详见"迁移排期"第 4 步清单），需要作为一次完整、可回归验证的变更单元执行，不与其他功能改动混在一起提交。
