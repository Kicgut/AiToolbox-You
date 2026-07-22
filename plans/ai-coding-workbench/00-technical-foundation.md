# Phase 0：技术基础与兼容性 Spike

> 状态：已完成  
> 依赖：`docs/ai-coding-workbench-architecture.md`  
> 允许真实模型请求：否  
> 允许修改第三方数据：否

## 目标

用无费用、可重复的实验确定实现边界，建立工具能力探测、原生会话 fixture、统一事件契约和进程监管原型。Phase 0 不交付用户功能页面。

## 非目标

- 不创建或续接真实模型 Turn。
- 不升级、降级、重装或修复 CC Switch、Cockpit Tools、Codex CLI、Claude Code 等外部软件。
- 不修改 Codex、Claude、Cockpit Tools 或 CC Switch 数据。
- 不实现正式数据库和完整前端。
- 不决定跨 profile 写入算法。

## 预期代码位置

本阶段先通过 ADR 确认。建议后端落在：

```text
proxy-traffic-monitor/app/ai_workbench/
├── adapters/
├── events/
├── indexing/
├── execution/
└── compatibility/
```

如果确认该模块未来应脱离 `proxy-traffic-monitor`，本 Phase 只调整 ADR 和计划，不同时搬迁现有流量监控代码。

## 任务

### P0-01：记录环境与目录 ADR

- [x] 确认后端模块、测试、fixture 和未来前端目录。
- [x] 明确 Windows 首发还是 Windows/Linux 同步支持。
- [x] 明确自有数据目录的 `platformdirs` 规则。
- [x] 记录现有 workspace 非 Git 根目录这一事实。

交付：`docs/adr/0001-ai-workbench-placement.md`。

### P0-02：工具能力探测

- [x] 定义 `ToolCapabilities` 数据结构。
- [x] 探测 Codex/Claude 可执行文件、版本和 help 能力，不依赖本地语言输出。
- [x] Codex 探测 App Server、`exec --json`、resume。
- [x] Claude 探测 `stream-json`、resume、fork、input stream。
- [x] 缺失工具时返回可解释状态，不使服务启动失败。

测试矩阵：两者存在、只存在一个、都不存在、命令超时、help 输出变化。

### P0-03：脱敏 fixture 集

- [x] 从 Codex 和 Claude 本机会话中选择覆盖主要事件形态的最小样本。
- [x] 复制到测试 fixture 前移除 prompt 私密内容、绝对用户名、token、URL 凭据和仓库私密信息。
- [x] 加入截断尾行、未知事件、工具结果、文件变化和 usage 样本。
- [x] 记录 fixture 来源 CLI 版本和脱敏方法。

禁止把真实完整 transcript 提交为 fixture。

### P0-04：统一事件契约 v1

- [x] 定义 event envelope、sequence、source provenance 和 data quality。
- [x] 定义 user/assistant/tool/command/file/usage/error/unknown 事件。
- [x] 规定 raw event 的保留和脱敏边界。
- [x] 生成 golden normalized events。

验收重点：前端和统计层不需要认识 Codex/Claude 原始 schema。

### P0-05：App Server 无费用验证

- [x] `initialize → initialized → thread/list(limit=1)` 已验证。
- [x] 验证 `thread/read(includeTurns=false)`，只读取一个已存在会话。
- [x] 验证客户端正常关闭、异常退出和超时。
- [x] 保存当前版本生成的 JSON Schema 到测试临时目录，确认版本绑定方式。
- [x] 记录稳定 API 与 experimental API 的使用清单。

不得调用 `thread/start` 或 `turn/start`。

### P0-06：Claude stream-json 模拟验证

- [x] 用 fake process 输出 assistant、tool、result 和 error JSONL。
- [x] 验证 stdout 增量解析与 stderr 分离。
- [x] 验证半行、无效 JSON、超长行和进程提前退出。
- [x] 研究但不执行真实 prompt 的 argv/stdin 组合。

### P0-07：CC Switch schema 兼容探测

- [x] 保存 v10 schema 元数据 fixture，不复制用户统计明细。
- [x] 从当前源码生成 schema 能力清单。
- [x] 实现只读 `sqlite_master/table_info/user_version` 探测原型。
- [x] 验证数据库不存在、损坏和旧列缺失。
- [x] 确认连接器从不打开写事务或改变 PRAGMA。

### P0-08：进程监管原型

- [x] 用 fake CLI 验证 spawn argv、stdin、stdout、stderr 和超时。
- [x] Windows process group 与 Job Object 方案保留为 Phase 3 正式运行中心硬化项。
- [x] 定义退出状态、interrupted 和 orphan cleanup 的原型边界。
- [x] 验证有限内存缓冲。

### P0-09：Spike 决策归档

- [x] 将验证事实更新到架构和 project context。
- [x] 更新 Phase 1–4 的接口假设。
- [x] 记录未解决问题和放弃的方案。

## 自动化验证

```powershell
python -m pytest tests/ai_workbench/phase0 -q
python C:\Users\YOU2\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents\skills\ai-coding-workbench
```

实际路径已由 P0-01 确认为 `proxy-traffic-monitor/tests/ai_workbench/phase0`。

## 退出标准

- 两个工具的能力探测在缺失和版本差异下均可解释。
- App Server read-only 握手和读取通过，无模型调用。
- 统一事件契约和 golden fixtures 通过测试。
- CC Switch v10/v16 能力探测不会写数据库。
- fake CLI 的取消、超时、stderr 和异常 JSON 均有确定结果。
- Phase 1 可以基于已验证接口实施，不依赖 Cockpit Tools/CC Switch。

## 风险与回滚

- 风险：fixture 泄露隐私。措施：人工复核、模式扫描、只保留最小结构。
- 风险：把实验 App Server API 固化。措施：只列白名单稳定方法并保留 exec fallback。
- 回滚：Phase 0 只新增隔离原型、fixture 和文档，不迁移用户数据；删除原型不会影响现有功能。

## 审查记录

- 暂无。

## 执行证据

- 已完成的前置验证：本机 Codex App Server initialize/thread list 成功，未调用模型。
- 2026-07-22：新增隔离模块 `proxy-traffic-monitor/app/ai_workbench/`，包含能力探测、统一事件契约、JSONL parser、只读 CC Switch schema probe、fake CLI process supervisor。
- 2026-07-22：新增最小脱敏 fixture 和 golden event types，覆盖 user、assistant、tool started/completed、file.changed、usage、error、unknown 和 invalid JSON tail。
- 2026-07-22：`codex app-server generate-json-schema --out <temp>` 成功；schema 包含 `thread/list` 和 `thread/read`。
- 2026-07-22：通过 `codex.cmd app-server --stdio` 完成 `initialize → initialized → thread/list(limit=1) → thread/read(includeTurns=false)`；返回 `turns_count=0`，未调用 `thread/start` 或 `turn/start`，未产生模型请求。
- 2026-07-22：只读检查 CC Switch 当前源码 `schema.rs` 的统计相关表，并保存 schema capability fixture；未升级或写入本机 CC Switch。
- 2026-07-22：验证命令 `python -m pytest tests\ai_workbench\phase0 -q`，结果 `13 passed`。
- 2026-07-22：验证命令 `python -m pytest -q`，结果 `17 passed`。
- 已知限制：Phase 0 的 process supervisor 只是原型，未实现 Windows Job Object 内核级进程树管理；正式运行、取消、审批和 orphan cleanup 进入 Phase 3。
