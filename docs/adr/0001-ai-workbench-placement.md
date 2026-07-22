# ADR 0001: AI Workbench Placement and Phase 0 Boundary

Date: 2026-07-22

Status: Accepted for Phase 0 implementation

## Context

The existing application is a FastAPI service under `proxy-traffic-monitor/` with static frontend assets served by Python. The AI coding workbench is planned as a larger module, but Phase 0 is a technical spike with no production UI and no real model turns.

## Decision

Phase 0 code lives under:

```text
proxy-traffic-monitor/app/ai_workbench/
```

Phase 0 tests live under:

```text
proxy-traffic-monitor/tests/ai_workbench/phase0/
```

The module is isolated from the current proxy traffic monitor APIs. It may define adapter contracts, read-only probes, fixtures, normalized events, and process-supervision prototypes. It must not be wired into user-facing routes until a later approved phase.

The first supported implementation target is Windows, matching the current development host and the main use case for local Codex CLI and Claude Code automation. Phase 0 code avoids Windows-only APIs where practical so Linux server support remains feasible in later phases.

Workbench-owned runtime data will use a dedicated application data directory derived from `platformdirs` or an equivalent standard rule in Phase 1. It must not be placed under `~/.codex`, `~/.claude`, `~/.cc-switch`, or `~/.antigravity_cockpit`.

The Git repository root is `E:\statistics-toolbox-You`, with the existing FastAPI service in `proxy-traffic-monitor/`.

## Consequences

- Existing proxy monitoring behavior remains untouched.
- Phase 0 can be removed without migrating user data.
- Future extraction into a separate backend package remains possible because tool-specific code is isolated behind `app.ai_workbench`.
- Later frontend work can move to Vue 3 + TypeScript + Vite while still shipping built assets through FastAPI.

