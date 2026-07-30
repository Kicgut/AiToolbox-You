# AI Coding Workbench 验证与边界手册

> 文档性质：规则的验证层，不是规则正文。  
> 核对基线：2026-07-24；当前 Phase 1 为 `修订中`，Phase 2–5 为 `待审查`。  
> 适用对象：在本仓库执行任务的 Claude Code、Codex 及人工审查者。

## 1. 使用方法与真源

### 1.1 唯一规则真源

本手册不复制规则原文。执行任务时必须先读：

1. `AGENTS.md`：仓库门禁、GitHub 同步、外部数据安全、实现约束；
2. `docs/ai-coding-workbench-architecture.md`：架构边界与决策表，尤其 §5.2、§5.3、§5.4、§12.2、§12.3、§15、§19；
3. `.agents/skills/ai-coding-workbench/SKILL.md`：可重复执行流程；
4. `CONTEXT.md`：术语；
5. `plans/ai-coding-workbench/README.md` 与唯一相关的当前 Phase 文件：授权状态、任务和退出证据。

若本手册与上述真源冲突，以真源为准，并先修订本手册中的验证映射；不得用本手册改变架构决策或 Phase 状态。

### 1.2 每项任务的执行顺序

- [ ] **开始前**：写下任务类型（设计/审查、诊断、实现、验收）和涉及的 Phase。
- [ ] **门禁**：核对 Phase 状态和用户原话。`待审查`、`修订中`不得实施；架构反馈只授权文档/计划修订；不得自动进入下一 Phase。
- [ ] **边界**：列出将读取、写入、执行和联网的目标；真实用户目录、外部数据库、CLI prompt、危险权限分别单列。
- [ ] **测试映射**：从本文规则矩阵选择适用的自动化断言和人工检查。
- [ ] **执行后**：保存测试命令、结果、第三方文件前后状态和已知空白；实现任务将证据写入当前 Phase。
- [ ] **同步前**：确认实际 Git 根、remote、仓库级身份、待提交文件、敏感信息扫描和远端状态。
- [ ] **停止点**：到 Phase 退出门禁即停止，等待验收；不得顺带实施后续 Phase。

判定词统一如下：

- **已覆盖**：现有测试直接断言该规则的关键结果；
- **部分覆盖**：只断言一个子条件，或实现存在但没有完整测试；
- **当前空白**：实际代码或测试中找不到对应行为；
- **未到 Phase**：规则已确定，但按门禁尚不应有产品实现；仍须保留未来验证设计。

## 2. 完整性核对结论

### 2.1 已知清单中的表述需要校正

| ID | 已知规则主题 | 当前代码/测试核对结论 | 证据 |
|---|---|---|---|
| C-01 | adapter 隔离 | **部分实现，不是已完整落地。** 能力探测位于 adapter 包，但解析走一个通用 normalizer；当前没有架构所述 `CodexAdapter`/`ClaudeAdapter` 合同。 | `app/ai_workbench/adapters/capabilities.py::probe_codex`、`probe_claude`；`events/normalizer.py::normalize_jsonl` |
| C-02 | 先归一化再存储/UI | **部分实现。** 扫描器先调用 normalizer 再写 `events`；详情 DTO 同时返回 `raw_json`，这是诊断 raw view，并不能证明所有未来 UI 不依赖 raw schema。 | `indexing/scanner.py::_index_transcript`（275–381）；`get_session_detail`（202–239） |
| C-03 | 来源和质量标签 | **模型与存储列已存在，语义覆盖不足。** `exact/estimated/unavailable` 枚举存在，但 normalizer 未针对不同来源赋值，当前事件默认全部 `exact`；尚无统计指标实现。 | `models.py::DataQuality`、`NormalizedEvent.quality`；`storage.py` 的 `data_quality`；无直接测试 |
| C-04 | schema fixture 与未知降级 | **未知降级已覆盖；“每个外部 schema 版本/分支”未满足。** 现有 golden fixture 是最小事件集合，没有 CLI 版本分支矩阵。 | `phase0/test_events.py::test_fixture_event_types_match_golden_file`、`test_normalize_jsonl_degrades_bad_lines_to_unknown_events`、`test_unknown_record_preserves_raw_payload` |
| C-05 | 完整尾行与 byte offset | **部分实现且实现方式与 §5.3 不同。** `_complete_text` 忽略未换行尾部并记录重编码后的长度，但扫描器每次 `read_text` 全量重读、删除并重写事件；没有从 checkpoint offset 增量读取。 | `scanner.py::_complete_text`（407–416）、`_index_transcript`（275–381）；`phase1/test_session_indexing.py::test_scan_indexes_codex_jsonl_and_ignores_incomplete_tail` |
| C-06 | 读取前后 length/mtime 复核 | **当前空白。** 只在读取前 `stat()`，读取后不复核；checkpoint 保存的是读取前 stat。 | `scanner.py::_index_transcript`（275–381） |
| C-07 | 暂时占用指数退避且不判损坏 | **当前空白。** 扫描器捕获 `OSError` 后记录错误并继续；watcher 仅固定间隔轮询，没有文件级指数退避状态。 | `scanner.py::scan_sessions`（54–61）；`watcher.py::run_forever`（24–34） |
| C-08 | CC Switch 只读、短事务、白名单列、回退 | **只有 `mode=ro`、1 秒连接 timeout、关闭连接和损坏状态已实现。** 当前 probe 枚举全部非 SQLite 表及其全部列，不是白名单列；未显式设置 `busy_timeout`，无短事务边界、统计导入、回退/去重。 | `compatibility/cc_switch.py::probe_cc_switch_schema`（21–46）；`phase0/test_cc_switch.py::test_cc_switch_probe_reads_schema_without_writing`、`test_cc_switch_probe_reports_corrupt_database` |
| C-09 | CC Switch“不读取/迁移数据库” | 已知清单中的“**不读取 CC Switch 数据库**”字样应校正为“**不写入、不迁移；只按批准的只读白名单读取**”。架构 §12.2/§12.3 明确允许只读连接器。 | `cc_switch.py` 确实只读打开；规则真源为架构 §12.2/§12.3 |
| C-10 | argv + stdin，不拼 shell prompt | **当前 supervisor 已实现并部分覆盖。** 测试证明 stdin 和 stdout/stderr 分离，但没有恶意 shell 元字符不被解释的断言，也未覆盖未来 Codex/Claude 运行 adapter。 | `execution/supervisor.py::run_process`（18–50）；`phase0/test_supervisor.py::test_supervisor_sends_stdin_and_separates_streams` |
| C-11 | 超时/取消/进程树清理/审批/沙箱 | **超时部分覆盖，其余当前空白。** 超时时只 `process.kill()`，不保证 Windows 子孙进程树清理；没有取消、审批或沙箱策略对象。 | `supervisor.py`（35–41）；`phase0/test_supervisor.py::test_supervisor_times_out_process` |
| C-12 | FTS 默认、提示、拒绝、清空 | **清空与最小脱敏已覆盖；2026-07-23 决策尚未实现。** 当前 `fts_status.enabled` 由索引行数推导，没有持久化“建议开启/已确认/拒绝”状态。P1-14 未勾选。 | `scanner.py::rebuild_fts`、`clear_fts`、`fts_status`；`phase1/test_session_indexing.py::test_manual_profile_and_fts_lifecycle`；Phase 1 P1-14 |
| C-13 | Windows only | **决策有效，不能误写成跨平台承诺。** 路径代码保留一定可迁移性，但现有测试没有 Windows watcher、锁、替换或进程树专项矩阵。 | 架构 §19；Phase 1 测试均基于 `tmp_path`，无 Windows 专项断言 |
| C-14 | Phase 5 安全闸门 | **未到 Phase，当前空白是正确状态。** 不得因缺少实现而在 Phase 1 补代码。 | `app/ai_workbench/` 无 migration/copy 模块；Phase 5 状态 `待审查` |

### 2.2 已知清单相对真源的遗漏

以下项目应加入未来助手的边界核对；它们不是新规则，而是现有真源中已存在、已知清单未完整列出的要求：

1. **外部软件更新禁令**：不得升级、降级、重装、修复或调用 Cockpit Tools、CC Switch、Codex CLI、Claude Code 的 updater；只允许只读版本探测。来源：`AGENTS.md`“外部数据安全”、skill“Preserve safety and coexistence”。
2. **仓库同步完整约束**：不得改全局 Git identity、全局 credential helper 或活动 GitHub CLI 账号；同步前先 fetch；不提交 runtime DB、凭据、本地设置、venv、cache、生成物；一致验证单元才推送。来源：`AGENTS.md`“GitHub synchronization”。
3. **保留无关改动、避免推测性重构**。来源：`AGENTS.md`“Implementation constraints”。
4. **上游代码归属**：复制或实质改写上游时记录仓库、URL、commit、license、修改摘要，并在首次复制时维护 `THIRD_PARTY_NOTICES.md`。来源：`AGENTS.md` 与 skill“Attribute upstream code”。
5. **完成证据落盘**：当前 Phase 的完成项和验证结果必须回写 active phase；架构决策变化同步决策表和受影响计划。来源：`AGENTS.md`、skill“Verify and hand off”。
6. **Cockpit/CC Switch 不得成为核心依赖**：不仅是“可选”，还必须验证未安装、关闭、运行中行为一致，自有原生解析始终可用。来源：架构 §5、§12 与 Phase 1/2 退出标准。
7. **Cockpit 明细隔离**：除已知清单列出的文件、端口、header/provider 外，还应检查不复用其临时文件名、垃圾箱、备份目录以及不依赖其内部运行状态。来源：架构 §5.2。
8. **原生文件永久只读边界**：Phase 0–4 不删除、归档、覆盖或写入原生会话；Phase 5 只允许被明确批准的精确目标和回滚流程。来源：`AGENTS.md`、架构 §15、Phase README。
9. **真实回合审批字段完整性**：Phase 3 每次真实测试必须逐字段填写并批准 P3-10，固定账号、精确模型、回合/输入/输出/turn/时长/工具和总预算、重试、回退、中止条件；一次批准不延续。来源：架构 §19。
10. **SSH 边界**：只监听 `127.0.0.1`；不实现应用内认证/TLS/远程服务；SSH 隧道不会降低高风险操作的确认、预算、回滚要求。来源：架构 §15、§19。
11. **敏感数据全链路**：API Key、OAuth token、Cookie、完整环境变量不得进入日志或数据库；导出 prompt/命令输出前做密钥模式扫描。已知清单提到扫描，但未强调“完整环境变量”和全链路存储/日志。来源：架构 §15。
12. **定时任务表达形式**：保存权限模板，不保存 shell 拼接字符串；危险权限显式开启且在运行中心持续可见。来源：架构 §15。
13. **Phase 5 发布边界**：默认关闭并标实验性，只开放逐项完整验证的 copy/fork 组合；实验性标签不能降低备份、precondition、原子写、回滚和隐私标准。来源：架构 §19。
14. **`model_pricing` 限定**：仅只读探测且默认不启用；用户显式信任后也只生成 API-equivalent estimate，不改写 token/会话/实际成本事实，自建 snapshot 优先。来源：架构 §19。
15. **部署产物一致性**：除“不要求 Node.js”外，还需验证 frontend 源码与提交的 hash 静态产物一致。当前为 P1-13 未完成门禁。来源：架构 §13.7、Phase 1 P1-13。

上述遗漏中，1、2、3、4、5 属于执行流程；6–15 属于产品/数据边界。未来不得因某条尚未进入 Phase 而删除其验证设计。

## 3. 规则验证矩阵

建议测试路径是设计目标；本轮不创建测试。每项先复用已覆盖测试，再补最小缺口。

### 3.1 流程、Phase 与同步

#### GATE-01 Phase 门禁与停止点

- 真源：`AGENTS.md`“Phase gate”；Phase README。
- 自动化建议：新建 `tests/ai_workbench/governance/test_phase_gate.py`，解析 README 表和 Phase 文件首部状态，断言同一 Phase 状态一致；静态检查仅能发现状态矛盾，**不能证明用户意图**。

```python
phase = parse_phase("01-read-only-session-center.md")
assert phase.status in ALLOWED_STATUS
assert roadmap[1].status == phase.status
assert implementation_authorized is (phase.status in {"已批准", "实施中"})
```

- 人工/AI 必查：
  - [ ] 引用用户授权原句和时间，不把“继续审查/设计”解释成“批准实施”。
  - [ ] 当前状态为 `待审查`/`修订中` 时，变更清单只含获准文档/计划。
  - [ ] 完成当前 Phase 后停止；下一 Phase 仍需单独批准。
  - [ ] 架构反馈先更新架构决策及受影响计划，不修改产品代码。

#### GATE-02 任务范围、无关改动与证据

- 自动化建议：CI 可比较允许路径清单，并校验实施状态的 Phase 有本次命令/结果记录；建议新建 `tests/ai_workbench/governance/test_change_scope.py`。
- 人工/AI 必查：
  - [ ] 开始前声明允许修改的精确路径。
  - [ ] 结束时比较工作区，逐个解释变更；无关用户改动保持原样。
  - [ ] 没有顺带重构、格式化或修复未授权内容。
  - [ ] 若是实现，active phase 的任务勾选、命令、结果、限制和回滚证据已同步。

#### GIT-01 仓库身份与安全同步

- 自动化建议：仓库脚本/CI（不接触凭据）断言 `remote.origin.url`、local `user.name/email`、分支与 forbidden paths；secret scanner 只扫 staged blob。此检查应位于仓库级 CI，不放业务 pytest。
- 人工/AI 必查：
  - [ ] 先发现真实 Git 根；不假定 workspace root 是 Git 仓库。
  - [ ] `origin` 精确为 `https://github.com/Kicgut/AiToolbox-You.git`。
  - [ ] 身份来自 repo-local config，未改 global identity、credential helper 或 gh 账号。
  - [ ] fetch 后再协调远端；不 force-push、不改写已发布历史、不丢弃远端工作。
  - [ ] staged diff 已检查 secret、真实 transcript、runtime DB、本地设置、cache、venv 和生成物。
  - [ ] 只推送完整且测试通过的一致变更单元。

#### EXT-01 不更新外部软件

- 自动化建议：新建 `tests/ai_workbench/governance/test_external_command_allowlist.py`，对 command builder 做静态/单元检查，拒绝 `update/upgrade/install/repair` 子命令；能力探测只允许版本/帮助命令。
- 现有部分证据：`phase0/test_capabilities.py::test_codex_probe_detects_expected_features` 证明当前探测调用可被替身隔离，但不覆盖更新禁令。
- 人工/AI 必查：
  - [ ] 执行记录只有只读 `--version`/`--help`/协议探测。
  - [ ] 未调用任何 updater、包管理安装、repair、迁移工具。
  - [ ] 若版本不兼容，只报告影响并让用户通过产品自身 UI 完整更新。

#### ATTR-01 上游代码归属

- 自动化建议：首次出现来源标记或复制清单时，CI 校验 `THIRD_PARTY_NOTICES.md` 存在，且每项含 repository、source URL、commit SHA、license、changes。
- 人工/AI 必查：
  - [ ] 区分“借鉴思路”与“复制/实质改写”。
  - [ ] 逐文件记录来源；核对 Cockpit Tools 的 CC BY-NC-SA 4.0 和目标项目许可兼容性。
  - [ ] 首次复制即维护 notices；信息不全则停止合入。

### 3.2 原生会话、Cockpit 与索引并发

#### IO-01 第三方和原生目录只读

- 自动化建议：新建 `phase1/test_read_only_boundaries.py`。完全使用 `tmp_path` 模拟四类根；扫描前后递归快照 `(relative_path, size, mtime_ns, sha256)`，只允许 Workbench 自有 DB 变化。

```python
before = tree_snapshot(fake_codex, fake_claude, fake_ccswitch, fake_cockpit)
scan_sessions(workbench_conn)
after = tree_snapshot(...)
assert after == before
assert writes_spy.targets <= {workbench_db, workbench_local_whitelist}
```

- 人工/AI 必查：
  - [ ] 测试输入全部是 fixture/temp，未指向真实 `~/.codex`、`~/.claude`、`~/.cc-switch`、`~/.antigravity_cockpit`。
  - [ ] Phase 0–4 无原生写 API；Phase 5 变更另走 MIG 规则。
  - [ ] 不删除、归档、覆盖第三方原始文件。
- 当前覆盖：**无直接快照断言，是真空白。**

#### IO-02 Cockpit 目录、锁、端口与注入隔离

- 自动化建议：新建 `phase1/test_cockpit_coexistence.py`，fixture 建立同名临时/垃圾箱/备份/lock/`codex_instances.json`/account 文件；运行 discovery/scan 后快照不变；socket spy 断言未 bind/connect Cockpit 内部端口；请求/进程参数不含 Cockpit 专用 header/provider/auth projection。
- 现状：`profiles.py::load_cockpit_whitelist` 只读 Workbench 自有 `data/ai_workbench/cockpit_profile_whitelist.json`，不是读取 Cockpit `codex_instances.json`；这是合规的不同实现，但没有隔离测试。
- 人工/AI 必查：
  - [ ] 写目标不在 Cockpit 根目录。
  - [ ] 没有导入 Cockpit 内部 lock、port、header、provider、认证文件约定。
  - [ ] Cockpit 未安装/关闭/运行中的核心结果一致。

#### IO-03 完整换行与 checkpoint

- 现有部分覆盖：`phase1/test_session_indexing.py::test_scan_indexes_codex_jsonl_and_ignores_incomplete_tail` 只证明未完成尾行不入库。
- 自动化补充：加入 `phase1/test_incremental_io.py`：

```python
scan(file=b'complete\npartial')
cp1 = checkpoint()
assert cp1.parsed_offset == len(b'complete\n')
append(file, b'-rest\n')
reconcile()
assert events == [complete_event, completed_tail_event]
assert checkpoint.parsed_offset == file.stat().st_size
assert no_duplicate_event_ids()
```

- 必须增加 UTF-8 多字节、CRLF、空文件、仅半行、文件缩短/替换用例。当前用 `read_text` 后重编码计算 offset，只能算部分实现。

#### IO-04 读前/读后复核与竞态

- 自动化建议：加入 `phase1/test_incremental_io.py`，monkeypatch 文件 reader，在读取中间追加/替换文件；断言本轮不提交未经复核的尾部，重新 stat 后重试或安全推迟，checkpoint 不越过最后完整换行。

```python
stat_before = os.stat(path)
reader_hook.append_during_read(...)
scan()
stat_after = os.stat(path)
assert checkpoint.offset <= last_complete_newline_verified
assert committed_hash == sha256(bytes[:checkpoint.offset])
assert retry_or_deferred is True
```

- 当前空白：`_index_transcript` 只有读前 stat。

#### IO-05 文件暂时占用退避

- 自动化建议：加入 `phase1/test_incremental_io.py`，前两次 open 抛 `PermissionError`/sharing violation，第三次成功；替换 clock/sleep，断言 delay 指数递增且有上限，session/checkpoint 未被标为 corrupt。

```python
assert sleep_delays == [base, base * 2]
assert source.status in {"active", "deferred"}
assert "corrupt" not in persisted_statuses
```

- 当前空白：scanner 只记录 error，watcher 使用固定 15 秒周期。

#### IO-06 replacement、缩短、移动和 missing

- 自动化建议：加入 `phase1/test_incremental_io.py`，覆盖相同路径 inode/file identity 变化、size 缩短、mtime 不变但 hash 变化、移动后旧 checkpoint missing；不得把新旧内容静默拼接。
- 现有 `test_reconcile_only_indexes_changed_files` 只覆盖 size/mtime 变化后的重索引，没有 replacement/缩短/移动/file identity 断言。

#### OPT-01 可选集成不影响核心

- 自动化建议：新建 `phase1/test_optional_integrations.py` 和未来 `phase2/test_statistics_fallback.py`。参数化 `missing/disabled/available/busy/corrupt/incompatible`；原生 session/token 基线保持一致，增强指标按质量标签降级。

```python
baseline = collect(cc_switch=None, cockpit=None)
for state in optional_states:
    result = collect(cc_switch=state)
    assert result.native_session_count == baseline.native_session_count
    assert result.native_token_total == baseline.native_token_total
    assert result.enrichment.quality in {"exact", "estimated", "unavailable"}
```

- 当前真空白：只有 capability/schema probe，尚无集成回退统计测试。

### 3.3 CC Switch 只读连接器与统计边界

#### CC-01 只读连接、短事务、busy timeout 与关闭

- 现有部分覆盖：
  - `phase0/test_cc_switch.py::test_cc_switch_probe_reads_schema_without_writing`：只断言主 DB `size` 不变；
  - `test_cc_switch_probe_reports_corrupt_database`：断言损坏返回 error；
  - `test_cc_switch_probe_reports_missing_database`：断言缺失。
- 现有测试不足：只比较 size，不能发现同尺寸写入、mtime 变化或 `-wal/-shm/-journal` 副文件。
- 自动化补充：扩展 `phase0/test_cc_switch.py`：

```python
before = db_snapshot(db, include_sidecars=True)
probe_cc_switch_schema(db)
after = db_snapshot(db, include_sidecars=True)
assert after == before
connect_spy.assert_uri_contains("mode=ro")
assert observed_busy_timeout == EXPECTED_MS
assert transaction_duration < bounded_window
assert connection_closed
```

并用外部连接持有写锁，断言在上限内返回 `busy/unavailable`，不等待或尝试修复。

#### CC-02 禁止 DDL、journal 修改、migration、VACUUM、写入

- 自动化建议：新建 `phase2/test_cc_switch_readonly_connector.py`，SQLite authorizer 拒绝并记录 `INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/PRAGMA journal_mode/VACUUM`；执行所有 probe/import 路径后断言记录为空。
- 当前 `mode=ro` 提供一层保护，但没有意图级测试；Phase 2 连接器尚未实现。

#### CC-03 表列白名单与凭据隔离

- 自动化建议：在 fixture 增加 `providers(credentials_json, api_key)`、`secrets` 及 trap view/authorizer；只允许批准的表列，访问凭据列即失败。

```python
assert observed_reads <= APPROVED_TABLE_COLUMN_WHITELIST
assert ("providers", "credentials_json") not in observed_reads
assert secret_marker not in repr(result)
```

- **当前实现不符合目标方式**：`probe_cc_switch_schema` 枚举所有表并对每表执行 `PRAGMA table_info`。虽未读数据行，仍不是“只读白名单列”连接器；应在 Phase 2 设计中收窄，而不是在当前修订中越门禁实现。
- 人工/AI 必查：
  - [ ] 评审 SQL 常量和动态 SQL来源；没有 `SELECT *`。
  - [ ] `providers` 凭据 JSON 不参与 account attribution。
  - [ ] 错误信息、日志和 DTO 不带 schema 中的敏感值。

#### CC-04 回退、去重和来源质量

- 自动化建议：新建 `phase2/test_statistics_fallback.py`，构造 native、`session_log`、`codex_session`、proxy 重叠 fixture：

```python
assert total_tokens == native_total + proxy_only_total
assert session_log_tokens_counted == 0
assert codex_session_tokens_counted == 0
assert cross_checks_recorded
assert every_metric_has(source, quality)
assert missing_value is None and display_value == "—"
```

- 当前真空白：Phase 2 尚未批准，无统计导入/去重代码。

#### CC-05 `model_pricing` 默认禁用

- 自动化建议：加入 `phase2/test_pricing_sources.py`，断言可探测但默认 inactive；未经显式 trust 不产生估价；启用后只生成 `estimated` API-equivalent cost，不覆盖实际成本，用户 snapshot 优先。
- 人工/AI 必查：
  - [ ] 启用记录包含用户显式信任动作。
  - [ ] 来源、生效时间、更新时间、币种齐全，否则 unavailable。
  - [ ] 不把估价写成实际账单事实。
- 当前真空白，且未到 Phase。

### 3.4 Adapter、事件、DTO 与数据质量

#### EVT-01 工具行为在 adapter 后

- 自动化建议：新建 `phase1/test_adapter_boundaries.py`，用 import/lint 架构测试禁止 API、storage、frontend-facing DTO 直接 import Codex/Claude raw parser；合同测试对两种 adapter 返回同一 normalized event interface。
- 人工/AI 必查：
  - [ ] 新增工具分支落在 adapter/parser 层，不散落于 API/storage/UI。
  - [ ] 共用代码只消费稳定合同，不基于 raw `type` 分支。
- 当前只有 capability adapter，解析隔离仍是部分实现。

#### EVT-02 unknown/raw/provenance

- 现有已覆盖：
  - `phase0/test_events.py::test_normalize_jsonl_degrades_bad_lines_to_unknown_events`；
  - `test_unknown_record_preserves_raw_payload`；
  - `test_fixture_event_types_match_golden_file`。
- 自动化缺口：扩展版本化 fixtures，逐个支持的 Codex/Claude schema/CLI 分支断言 normalized type、source、raw type、CLI version、byte offset、quality；一条 unknown 不影响后续有效行。

#### EVT-03 UI/API 不依赖 raw schema

- 自动化建议：新建 `phase1/test_stable_dto.py`，同一语义用两个 raw schema 版本输入，断言稳定 DTO 相同；raw 只出现在明确诊断字段/端点，列表 DTO 不泄露 raw。
- 当前 `get_session_detail` 返回 `raw_json` 以支持 raw view，合理但需要合同测试限定用途；`test_api_routes_are_registered` 只证明空列表接口存在，不覆盖 DTO 稳定性。

#### EVT-04 来源与数据质量

- 自动化建议：加入 `phase1/test_event_quality.py`，以及 Phase 2 指标测试。断言所有持久化事件/指标的 `source` 和 `quality` 非空且枚举合法；估算与缺失不能伪装成 exact/0。
- 当前模型存在但无直接测试，且事件默认 exact；统计质量是真空白。

#### EVT-05 版本化 fixture 矩阵

- 自动化建议：fixtures 路径显式携带 `tool/schema-or-cli-version/case.jsonl`；参数化测试读取 manifest，断言 manifest 声明的每个支持分支至少一个 fixture，unknown 和 invalid tail 均覆盖。
- 现有 `cc_switch_schema_capabilities.json` 只“文档化所需表”，`test_cc_switch_schema_capability_fixture_documents_statistics_tables` 不会驱动真实连接器版本分支，不能算 v10/v16 完整覆盖。

### 3.5 进程执行、真实额度与危险权限

#### RUN-01 argv 与 stdin/协议字段

- 现有部分覆盖：`phase0/test_supervisor.py::test_supervisor_sends_stdin_and_separates_streams`。
- 自动化补充：在同文件加入 shell 元字符测试，mock `Popen` 断言 `args` 是 list、`shell` 未启用，prompt 只出现在 `communicate(input=...)`：

```python
prompt = 'x & echo PWNED | $(whoami) " ;'
run_process(("fake-cli", "--json"), stdin_text=prompt)
assert popen.args == ["fake-cli", "--json"]
assert popen.kwargs.get("shell", False) is False
assert communicate.input == prompt
```

#### RUN-02 超时、取消和进程树清理

- 已覆盖：`tests/ai_workbench/phase3/test_p3_06_supervisor.py` 使用真实父子 fixture 验证 timeout 和已登记取消都会结束 Windows 子进程树；`test_p3_06_runtime_coordinator.py` 覆盖 timeout 事实先持久化、运行结束后终态与 session writer lease。
- 运行时边界：Coordinator 是唯一进程 handle 所有者；取消 API 只持久化请求，Coordinator 再终止树。无法确认清理时应为 `interrupted`，不得伪报 `cancelled`。

#### RUN-03 审批、沙箱和危险权限可见性

- 已覆盖的审批桥：`tests/ai_workbench/phase3/test_p3_07_approval.py` 与 `test_p3_06_runtime_coordinator.py` 验证 `pending → responding → delivered terminal`、并发决定只允许一个胜出，以及 native delivery failed 不显示为 accepted。Codex command/file request 由同一 App Server stdin 回送；Claude stream-json 明确不提供该桥。
- 仍需 P3-10 人工验证的项目：真实 CLI 的沙箱实际执行、模型侧权限语义和额度上限。

- 人工/AI 必查：
  - [ ] 默认 sandbox/approval 不被绕过。
  - [ ] 危险权限由用户显式开启，并在运行中心持续显示。
  - [ ] SSH 隧道访问不降低审批、预算、回滚。
- 当前剩余边界是 P3-10 的真实模型回合验收；自动化 fake 运行不得替代该授权。

#### RUN-04 真实模型请求与 P3-10

- 不能仅靠自动化证明“用户批准”。可增加 hard gate：integration test 默认 skip，只有结构化 approval artifact 的所有字段齐全、一次性 nonce 未消费且预算上限合法才可解锁。
- 人工/AI 必查：
  - [ ] 用户明确批准 account、精确 model、prompt。
  - [ ] P3-10 的回合数、单回合输入/输出/turn/时长、单工具和总预算、重试、model fallback、中止条件逐字段填写。
  - [ ] 批准只覆盖本次固定回合，不授权后续测试/自动重试。
  - [ ] 默认测试全部 fake CLI；无批准时网络/真实 CLI 调用为零。
- 当前测试均使用 Python fake process 或 monkeypatch，没有发送真实 prompt；这是良好基线，但没有“防误发”硬门禁测试。

### 3.6 安全、隐私、网络与全文索引

#### SEC-01 loopback 与 SSH 产品边界

- 自动化建议：新建 `phase1/test_network_boundary.py`，检查启动配置默认 host 精确为 `127.0.0.1`；拒绝/警告 `0.0.0.0`、`::`；路由表无应用内 login/OAuth/TLS/session-management 产品端点。
- 人工/AI 必查：
  - [ ] 未实现应用内远程服务、认证或多人租户。
  - [ ] SSH 仅是用户外部建立的隧道；应用仍视连接者为实例所有者。
  - [ ] 需要真正远程只读/多用户时，单独立项和批准。
- 当前 `ai_workbench` 测试没有监听地址断言，真空白。

#### SEC-02 凭据不进入日志、DB、DTO

- 自动化建议：新建 `phase1/test_sensitive_data_boundaries.py`，把 unique markers 放入 API key、OAuth、Cookie、完整 env fixture；运行 discovery/scan/error path 后递归检查 Workbench DB、captured logs、API JSON 不含 marker。
- 注意：raw transcript 本身可能合法含敏感文本；规则要求 Workbench 不读取第三方凭据做归属，也不把 API key/token/Cookie/完整环境变量写入日志/DB。对 transcript raw 的保留与索引脱敏必须按架构明确区分，不能用测试误删诊断 raw。
- 当前只有 FTS 的 `password=hidden` 脱敏断言；全链路真空白。

#### SEC-03 FTS 知情选择、关闭、清空和脱敏

- 现有部分覆盖：`test_manual_profile_and_fts_lifecycle` 证明一种 password 模式被 redacted，且 clear 后行数为 0。
- 自动化建议：新建 `phase1/test_fts_consent.py`：

```python
fresh = new_instance()
assert fresh.fts_recommendation == "on"
assert fresh.fts_effective is False  # 尚未确认
assert build_before_consent() is blocked
assert reject_consent().indexed_events == 0
assert existing_install_upgrade().setting == old_setting
assert disable_future_indexing_keeps_existing_rows()
assert clear_existing_index_removes_all_rows()
```

并参数化全部密钥模式与误报边界。P1-14 完成前不得把当前行为称为已符合新决策。

#### SEC-04 导出前密钥扫描

- 自动化建议：未来新建 `phase3/test_export_redaction.py`，在 prompt/command output 中放入各类 canary；导出动作必须 block、redact 或要求明确确认，并返回扫描报告。
- 人工/AI 必查：
  - [ ] 导出目标和包含内容可见。
  - [ ] 扫描发生在写文件/复制/发送之前。
  - [ ] 扫描器限制与用户 override 被记录。
- 当前无 export 模块，真空白。

#### SEC-05 自动任务和权限模板

- 自动化建议：未来新建 `phase4/test_automation_policy.py`；持久化对象只含 argv/protocol fields 与 permission template，不含 shell command string；危险位默认 false 且 UI 状态持续可见。
- 当前未到 Phase，真空白。

### 3.7 部署、平台与发布

#### DEP-01 FastAPI 携带静态产物且生产无 Node.js

- 自动化建议：新建 `phase1/test_packaged_frontend.py`，在移除 PATH 中 node/npm 的隔离环境启动 Python 包，访问 SPA/静态资源均 200；检查 runtime dependencies 不含 Node。
- 现有测试 `test_api_routes_are_registered` 只覆盖 API，不覆盖静态分发或无 Node 运行。

#### DEP-02 源码与构建产物一致

- 自动化建议：P1-13 新增构建一致性命令：复制源码树、执行锁定依赖的 build、比较生成 manifest/hash 与提交的 `app/static/workbench/`；diff 必须为空。
- 人工/AI 必查：
  - [ ] lockfile 未漂移。
  - [ ] 产物来自当前源码，不是手工旧文件。
  - [ ] 不把 node_modules/cache 纳入提交。
- 当前真空白，P1-13 明确未完成。

#### PLAT-01 Windows 正式支持范围

- 自动化建议：Windows CI 覆盖路径大小写、CRLF/UTF-8、sharing violation、watcher、SQLite lock、process tree、atomic replace；Linux job 可作非阻塞烟测，但不得成为兼容承诺。
- 人工/AI 必查：
  - [ ] 发布说明只声明 Windows 正式支持。
  - [ ] 不以 Linux 未通过阻塞首版，也不声称已验收 Linux。
- 当前无 Windows 专项矩阵，真空白。

### 3.8 Phase 5 复制安全闸门

本节是未来验收设计。当前 Phase 5 为 `待审查`，不得据此实施。

#### MIG-01 显式源/目标、隐私与实验开关

- 自动化建议：未来 `phase5/test_migration_gate.py` 断言 feature flag 默认 false、UI/API 标 experimental；源和目标缺一、相同或未确认隐私提示均拒绝。
- 人工/AI 必查：
  - [ ] 用户逐次选择精确 source/target profile 和 transcript。
  - [ ] 显示目标账号/provider/设备及数据外发提醒。
  - [ ] 只开放已完整验证的 copy/fork 组合；replace、handoff、Claude target、cross-provider 分别验收。

#### MIG-02 活跃 writer 检测与前置条件

- 自动化建议：模拟 Codex/Claude/Cockpit 写入、文件 handle 和 mtime/hash 变化；任一 writer 活跃或 precondition 变化立即中止，无目标写入。

```python
pre = snapshot_hash_mtime(source, target)
assert migrate_when(writer_active).status == "blocked"
mutate(source_after_precheck)
assert migrate().status == "precondition_failed"
assert target_snapshot == target_before
```

#### MIG-03 备份、操作日志、fsync 与原子替换

- 自动化建议：fault injection 覆盖临时写中断、fsync 失败、二次 hash 变化、replace 失败；断言 backup 可恢复、操作日志完整、temp 清理可控、目标不是半文件。

```python
write(temp); fsync(temp)
assert recheck_hashes() == preconditions
atomic_replace(temp, target)
assert operation_log.has(pre, post, backup, outcome)
```

Windows 上必须验证同卷 atomic replace 语义和被占用目标的失败路径。

#### MIG-04 完成后重索引、CLI 可读与回滚

- 自动化建议：使用 fake CLI/fixture validator，断言成功后重新索引、目标 CLI read probe 成功；验证失败自动回滚并复核 backup hash。不得用真实模型回合作为默认可读性检查。
- 当前整个 MIG-01–04 均为真空白且未到 Phase，这是符合门禁的状态。

## 4. 现有测试覆盖清单

### 4.1 已直接覆盖或可复用

| 规则片段 | 测试证据 | 覆盖边界 |
|---|---|---|
| argv 进程可通过 stdin 收 prompt；stdout/stderr 分离 | `phase0/test_supervisor.py::test_supervisor_sends_stdin_and_separates_streams` | 未断言 shell 元字符、未来 adapter、危险权限 |
| supervisor timeout | `phase0/test_supervisor.py::test_supervisor_times_out_process` | 未断言 child tree、取消、有限缓冲 |
| 最小 Codex/Claude normalized event golden | `phase0/test_events.py::test_fixture_event_types_match_golden_file` | 非版本矩阵 |
| invalid JSON 降级 unknown | `phase0/test_events.py::test_normalize_jsonl_degrades_bad_lines_to_unknown_events` | parser 层会接收半行；scanner 层另行丢弃半行 |
| unknown 保留 raw | `phase0/test_events.py::test_unknown_record_preserves_raw_payload` | 未限制 raw DTO/UI 使用 |
| CC Switch 缺失/损坏降级为 probe 状态 | `phase0/test_cc_switch.py::test_cc_switch_probe_reports_missing_database`、`test_cc_switch_probe_reports_corrupt_database` | 尚未证明统计回退 |
| CC Switch schema probe 主文件 size 不变 | `phase0/test_cc_switch.py::test_cc_switch_probe_reads_schema_without_writing` | 未检查 hash/mtime/sidecar/authorizer；且 probe 非列白名单 |
| CC Switch fixture 包含目标表字段描述 | `phase0/test_cc_switch.py::test_cc_switch_schema_capability_fixture_documents_statistics_tables` | 只检查 JSON 内容，不验证连接器 v10/v16 分支 |
| capability missing/feature/timeout | `phase0/test_capabilities.py` 四个测试 | 未覆盖外部 updater 禁令 |
| env profile discovery | `phase1/test_session_indexing.py::test_discover_profiles_from_env` | 未覆盖 Cockpit 三态和白名单边界 |
| scanner 忽略未换行尾部 | `phase1/test_session_indexing.py::test_scan_indexes_codex_jsonl_and_ignores_incomplete_tail` | 未证明真正增量 byte-offset、并发复核 |
| changed_only 根据 size/mtime 重索引 | `phase1/test_session_indexing.py::test_reconcile_only_indexes_changed_files` | 未覆盖 hash-only、replacement、缩短、移动 |
| Claude project 基本扫描 | `phase1/test_session_indexing.py::test_scan_indexes_claude_project_path` | 未覆盖版本/子代理/附件等矩阵 |
| FTS 单一脱敏模式和清空 | `phase1/test_session_indexing.py::test_manual_profile_and_fts_lifecycle` | 未覆盖 consent/default/升级保留/全模式 |
| divergent copies 和 common prefix | `phase1/test_session_indexing.py::test_divergent_copies_return_diff_summary` | 未覆盖 in_sync/ahead/假碰撞/不自动合并 |
| API 空列表路由 | `phase1/test_session_indexing.py::test_api_routes_are_registered` | 未覆盖 stable DTO、raw 边界、分页上限 |

`test_schema_version_is_recorded` 验证 Workbench 自有 DB schema version，不直接覆盖本文外部边界。

### 4.2 真正的测试空白

以下没有现有测试直接断言，不能以计划勾选或代码表面存在代替：

- Phase 授权意图、停止点、active phase 证据同步；
- repo-local Git identity、remote/fetch/no-force-push、staged secret/local-data 审查；
- 外部软件不升级/修复、上游 attribution；
- 四类真实来源的递归只读快照；
- Cockpit 临时名/垃圾箱/备份/lock/端口/header/provider/auth 隔离及三态一致性；
- 真正从 byte offset 增量读取、读前后 stat 复核、竞态、sharing violation 指数退避；
- replacement/缩短/移动/file identity 的完整行为；
- CC Switch authorizer 禁写、明确 busy timeout/短事务、表列白名单、凭据 trap；
- CC Switch 统计回退、proxy-only 导入、session_log/codex_session 去重；
- `model_pricing` 默认禁用与 estimated 语义；
- CodexAdapter/ClaudeAdapter 合同、稳定 DTO 不依赖 raw；
- 全部 schema/CLI 版本 fixture 分支；
- estimated/unavailable 的来源与质量传播；
- shell 元字符不执行、取消、Windows 进程树清理、审批/沙箱/危险权限持续可见；
- 真实请求防误发硬门禁与 P3-10 一次性字段化审批；
- 默认 `127.0.0.1`、无应用内远程认证产品；
- 凭据/完整环境变量不进入日志、DB、DTO；
- FTS 首次提示/拒绝/已有安装不变；导出前密钥扫描；
- 定时任务只存权限模板和结构化参数；
- FastAPI 静态产物无 Node 运行、源码/产物一致性；
- Windows 专项 watcher/lock/atomic replace/process tree 矩阵；
- Phase 5 全部复制安全闸门。

## 5. 优先补测顺序

按“越界后果 × 当前实现接近可测程度”排序：

1. **P0：只读不变式**：IO-01、CC-01/02/03、SEC-02。先建立递归 hash/mtime/size/sidecar 与 SQLite authorizer，成本低，能直接阻止第三方数据和凭据越界。
2. **P0：并发索引正确性**：IO-03/04/05/06。当前实现与 §5.3 差距最大，存在错误 checkpoint、竞态和占用处理风险。
3. **P0：进程边界**：RUN-01/02、RUN-04 防误发门禁。先补 shell 元字符和 Windows child tree；真实额度硬门禁在 Phase 3 实现前先设计成默认关闭。
4. **P1：稳定数据合同**：EVT-01–05。补 adapter 合同、DTO/raw 边界、版本 fixture 和质量标签，避免后续 Phase 2/3 把当前临时 schema 固化。
5. **P1：可选集成回退与去重**：OPT-01、CC-04/05。应作为 Phase 2 获批后的首批测试，而不是现在越门禁实现。
6. **P1：隐私与网络**：SEC-01/03/04/05。P1-14 consent 优先于新增索引行为；导出和自动任务随对应 Phase。
7. **P1：部署与 Windows 发布**：DEP-01/02、PLAT-01。P1-13 的构建一致性是批准 Phase 2 前门禁。
8. **P2：Phase 5 复制矩阵**：MIG-01–04。风险最高，但当前未到 Phase；必须先审查、默认关闭、再用 fault injection 完整覆盖。
9. **流程保障**：GATE/GIT/EXT/ATTR 以 CI 和可勾选审查为主；自动化只能辅助，不能替代用户授权和人工 staged review。

## 6. 每次任务的最终自审模板

复制到任务记录或 active phase 证据中填写：

```text
任务/Phase：
用户授权原句：
Phase 状态与允许动作：
本次读取：
本次写入：
外部程序/网络：
真实用户数据：无 / 精确授权目标
真实模型请求：无 / P3-10 审批引用
危险权限：无 / 显式批准与持续可见证据

适用规则 ID：
现有复用测试：
新增/运行测试：
人工检查结果：
第三方目录前后快照：
Workbench 自有数据变化：
未覆盖空白与风险：
回滚方式：

Git 根与 origin：
repo-local identity：
fetch/远端协调：
staged secret/local-data review：
commit/push 结果：

停止点：等待验收 / 当前 Phase 内继续
```

任何一项无法给出证据时，写“当前空白/未验证”，不得写“应当没问题”或从计划勾选推断已覆盖。
