# Repository guidance

## Scope and source of truth

- Treat `docs/ai-coding-workbench-architecture.md` as the architecture source of truth for the AI coding workbench.
- Read `CONTEXT.md` for domain terminology, `docs/ai-coding-workbench-architecture.md` (including its decision table) for confirmed decisions, and the active phase file in `plans/ai-coding-workbench/` for current status before changing architecture, plans, adapters, session storage, statistics, execution, scheduling, or third-party integration.
- Read `plans/ai-coding-workbench/README.md` and only the active phase file before implementing workbench code.
- Use the repo skill `$ai-coding-workbench` for architecture revisions, phase reviews, and phase implementation.
- The workspace root is not currently a Git repository. Do not assume Git operations are available; discover the actual code root before using Git.

## Codex collaboration context

- Apply repository rules in this order: root `AGENTS.md`, then the nearest nested `AGENTS.md`, then the task-relevant skill; `CONTEXT.md`, architecture, ADRs and Phase plans retain the content ownership described in this file.
- Project-local `.codex/config.toml` applies only when Codex trusts the project. Do not assume a project configuration changes host-wide policy or creates a repository-owned memory store.
- Codex memories are personal host state under `CODEX_HOME`; they are not versioned project facts. Never create, commit or rely on a repository `.codex/memories/` directory for mandatory instructions.
- Use `$ai-coding-workbench` for architecture, plans, session indexing, statistics, execution, scheduling, migration and optional external-tool boundaries. Keep the skill as workflow guidance; keep decisions and evidence in the repository documents it routes to.

## Phase gate

- Do not implement a phase marked `待审查` or `修订中`. Implementation starts only after the user explicitly approves that phase.
- Do not begin a later phase automatically after completing the current one.
- Architecture feedback updates documents and plans first; it does not authorize product-code changes.
- Record completed task evidence and verification results in the active phase plan.
- When a Phase reaches user-confirmed completion, update `docs/phase-execution-lessons.md` in the same closeout: record reusable lessons, or explicitly record that no new reusable lesson arose. Important end-to-end lessons discovered before closure may be recorded there as `进行中`, then finalized at completion.

## GitHub synchronization

- The canonical remote is `https://github.com/Kicgut/AiToolbox-You.git` and this repository must use the repo-local `Kicgut` identity.
- Never change global Git identity, global credential helpers, or the active GitHub CLI account to synchronize this repository.
- After each coherent requested change is complete and proportionately verified, review the staged diff for secrets and local data, create a focused commit, and push it to `origin/main` unless the user explicitly requests local-only work.
- “Real-time synchronization” means pushing verified change units, not partially edited or failing intermediate states.
- Fetch before reconciling remote changes. Never force-push, rewrite published history, or discard remote work without explicit user approval.
- Keep runtime databases, credentials, local settings, virtual environments, caches, and generated artifacts out of Git.

## External data safety

- Cockpit Tools and CC Switch are optional integrations, never runtime dependencies.
- Keep `~/.codex`, `~/.claude`, `~/.cc-switch`, and `~/.antigravity_cockpit` read-only unless an approved task explicitly authorizes exact mutations and rollback.
- Never read or persist third-party credentials merely to improve account attribution.
- Never write or migrate the CC Switch database from this project. Its connector is read-only and must fall back to native session parsing.
- Never upgrade, downgrade, reinstall, repair, or invoke an updater for Cockpit Tools, CC Switch, Codex CLI, Claude Code, or other external software as part of a project phase. Read-only version detection is allowed. If an upgrade may help, explain the impact, ask the user first, and recommend that the user perform the complete software update through that product's own update UI. A phase approval does not authorize an external-software upgrade.
- Do not send real Codex or Claude prompts during tests without explicit approval of account, model, prompt, and budget.
- If a task genuinely needs an approval/sandbox bypass (`danger-full-access`, `--dangerously-bypass-approvals-and-sandbox`), ask the user first and get explicit confirmation before using it on that dispatch. A Codex process already running with such a bypass that you did not start yourself is very likely something the user launched intentionally (e.g. a project-local launcher script) — leave it running and don't interrupt or kill it; if it genuinely needs to be interrupted, confirm with the user first.

## Implementation constraints

- Preserve unrelated user changes and avoid speculative refactors.
- Keep Codex- and Claude-specific behavior behind adapters and normalize their events before storage or UI use.
- Treat unknown CLI records as compatible raw events; one unknown line must not invalidate an entire session.
- Use argument arrays and stdin/protocol fields for prompts; do not build shell command strings from user content.
- Keep deployment independent of Node.js by shipping built frontend assets with FastAPI.
- Add fixture-based tests for every supported external schema and version branch.
- Attribute copied upstream code with repository, source URL, commit, license, and changes; add `THIRD_PARTY_NOTICES.md` when copying begins.

## Generated artifact hygiene

- Do not create test databases, screenshots, generated schemas, temporary scripts, logs, basetemp directories, or verification reports in the repository root.
- Put disposable test/runtime scratch output under `.artifacts/tmp/`; put retained local verification evidence under `.artifacts/verification/`.
- Use a task- or run-specific subdirectory below those roots. Never invent new top-level `*-temp`, `pytest-*`, `verification-*`, `codex-test-*`, or smoke database paths.
- Pytest tests should prefer the built-in `tmp_path`/`tmp_path_factory`. Manual `--basetemp` paths must be below `.artifacts/tmp/pytest/`.
- Generated frontend assets intentionally shipped by FastAPI remain under `app/static/workbench/`; source-controlled fixtures remain under `tests/fixtures/`. Runtime application data remains under ignored `data/`. These are not verification scratch directories.
- Before finishing a task, remove disposable artifacts and check `git status --short` for root-level leakage. See `docs/artifact-hygiene.md` for the full policy.

## Repository layout

- This repository's root is the AI Coding Workbench's own engineering root (`app/`, `frontend/`, `tests/`); the repo itself is the primary product, not a container for peer products. See `docs/adr/0002-workbench-root-and-feature-module-layout.md`.
- Auxiliary features (small, focused, secondary tools such as `features/proxy-traffic-monitor/`) live under `features/<slug>/` and are mounted into the primary app via an explicit `mount()`/`lifespan()` interface — never merged into `app/ai_workbench`.

## Current verification commands

Run from the repository root when changing the existing Python service:

```powershell
python -m pytest
python -m app.main
```

For the project skill:

```powershell
python C:\Users\YOU2\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents\skills\ai-coding-workbench
```

Add phase-specific commands to the active plan when new frontend or workbench modules are introduced.

## Documentation maintenance

- Keep `AGENTS.md` short and durable. Put detailed architecture in `docs/` and executable task breakdowns in `plans/`.
- Put domain terminology in `CONTEXT.md` only (definitions, no implementation detail or rationale). Put confirmed architecture decisions in the `docs/ai-coding-workbench-architecture.md` decision table, or in `docs/adr/` when a decision is hard to reverse, surprising, and the result of a real trade-off. Keep hypotheses and temporary research in `notes/`.
- When a decision changes, update the architecture decision record and affected plans in the same change.
