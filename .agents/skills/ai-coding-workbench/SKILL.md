---
name: ai-coding-workbench
description: Plan, review, implement, and verify the AI coding workbench in this repository. Use when updating its architecture or project context, reviewing or executing a phase plan, working on Codex/Claude session indexing, usage statistics, structured live execution, scheduling, or cross-profile migration, and when changes must respect Cockpit Tools and CC Switch coexistence boundaries.
---

# AI Coding Workbench

Follow the repository's approved architecture and phase gates. Keep design decisions, implementation state, and verification evidence synchronized without expanding into an unapproved phase.

## Load context

1. Read the nearest `AGENTS.md`.
2. Read `docs/project-context.md` for confirmed decisions and current status.
3. Read `docs/ai-coding-workbench-architecture.md` when the task affects architecture, data contracts, security, interoperability, or UI structure.
4. Read `plans/ai-coding-workbench/README.md`, then the one phase file relevant to the request. Do not load every phase unless comparing dependencies or changing the roadmap.
5. Inspect the existing implementation and tests before proposing file-level changes.

## Classify the request

- For architecture feedback, update the architecture document, project context, affected phase plans, and decision records. Do not implement product code.
- For a phase review, inspect its dependencies, tasks, risks, tests, and exit criteria. Record requested revisions without marking the phase approved unless the user explicitly approves it.
- For implementation, require the phase status to be `已批准`. Work only on that phase and update task checkboxes and evidence as work completes.
- For diagnosis or research, perform read-only checks first and record verified facts separately from assumptions.

## Preserve safety and coexistence

- Keep native Codex and Claude session sources read-only until the approved phase explicitly authorizes a mutation.
- Treat Cockpit Tools and CC Switch as optional external systems. Never make core behavior depend on either being installed.
- Never write to `~/.cc-switch`, `~/.antigravity_cockpit`, third-party databases, account files, or credential stores unless a separately approved migration task names the exact target and rollback.
- Do not upgrade, downgrade, reinstall, repair, or run an updater for external software such as Cockpit Tools, CC Switch, Codex CLI, or Claude Code. Report version compatibility read-only; if an upgrade is useful, stop and recommend that the user perform it through the software's own update UI.
- Do not send real model prompts or consume quota during tests unless the user approves the account, model, prompt, and budget cap.
- Do not enable dangerous permission bypasses by default. Exercise approval, sandbox, timeout, cancellation, and process-tree cleanup paths.
- Avoid shell command-string concatenation for prompts. Spawn executables with argument arrays and use stdin or protocol fields for user content.

## Implement through stable boundaries

- Keep tool-specific behavior behind `CodexAdapter` and `ClaudeAdapter` contracts.
- Normalize external events before exposing them to API, storage, statistics, or the frontend.
- Keep raw source events for compatibility diagnostics, but do not make UI components depend on raw tool schemas.
- Preserve source provenance and data-quality labels: `exact`, `estimated`, or `unavailable`.
- Use fixture and golden-event tests for CLI schema versions. A parser must degrade an unknown record to a raw/unknown event instead of failing the entire session.
- Keep the frontend build deployable as static FastAPI assets; Node.js is a development/build dependency, not a production runtime requirement.

## Verify and hand off

1. Run the checks required by the active phase file.
2. Confirm no unapproved external database, session, account, or configuration file changed.
3. Record verification commands and results in the phase evidence section.
4. Update `docs/project-context.md` only with durable, verified information or explicitly confirmed decisions.
5. Update the architecture decision table when a design choice changes.
6. Review staged content for credentials and machine-local data, then commit and push the coherent verified change to `origin/main` using only repository-local Kicgut configuration. Do not change global Git/GitHub account settings and never force-push.
7. Stop at the phase exit gate and request review instead of beginning the next phase automatically.

## Attribute upstream code

When copying or substantially adapting upstream code, add the upstream repository, source file URL, commit SHA, license, and a concise change summary. Maintain `THIRD_PARTY_NOTICES.md` when the first copied implementation is introduced. Cockpit Tools code is CC BY-NC-SA 4.0; CC Switch and Claude Waitlist are MIT at the references currently reviewed by this project.
