# Repository guidance

## Scope and source of truth

- Treat `docs/ai-coding-workbench-architecture.md` as the architecture source of truth for the AI coding workbench.
- Read `docs/project-context.md` before changing architecture, plans, adapters, session storage, statistics, execution, scheduling, or third-party integration.
- Read `plans/ai-coding-workbench/README.md` and only the active phase file before implementing workbench code.
- Use the repo skill `$ai-coding-workbench` for architecture revisions, phase reviews, and phase implementation.
- The workspace root is not currently a Git repository. Do not assume Git operations are available; discover the actual code root before using Git.

## Phase gate

- Do not implement a phase marked `待审查` or `修订中`. Implementation starts only after the user explicitly approves that phase.
- Do not begin a later phase automatically after completing the current one.
- Architecture feedback updates documents and plans first; it does not authorize product-code changes.
- Record completed task evidence and verification results in the active phase plan.

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
- Do not use dangerous approval or sandbox bypasses as defaults.

## Implementation constraints

- Preserve unrelated user changes and avoid speculative refactors.
- Keep Codex- and Claude-specific behavior behind adapters and normalize their events before storage or UI use.
- Treat unknown CLI records as compatible raw events; one unknown line must not invalidate an entire session.
- Use argument arrays and stdin/protocol fields for prompts; do not build shell command strings from user content.
- Keep deployment independent of Node.js by shipping built frontend assets with FastAPI.
- Add fixture-based tests for every supported external schema and version branch.
- Attribute copied upstream code with repository, source URL, commit, license, and changes; add `THIRD_PARTY_NOTICES.md` when copying begins.

## Current verification commands

Run from `proxy-traffic-monitor/` when changing the existing Python service:

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
- Put only verified facts and confirmed decisions in `docs/project-context.md`; keep hypotheses and temporary research in `notes/`.
- When a decision changes, update the architecture decision record, project context, and affected plans in the same change.
