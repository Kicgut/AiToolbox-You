---
name: delegating-to-codex
description: Use when dispatching analysis, review, or implementation work to the Codex CLI rescue subagent (codex:codex-rescue) in this repository, or when a Codex task unexpectedly can't write files despite requesting it.
---

# Delegating to Codex

## Overview

`codex:codex-rescue` forwards to `node codex-companion.mjs task ...`, a thin wrapper around the Codex App Server. Two things about it are easy to get wrong: which thread you resume, and what "write access" actually means. Both come from one fact — **sandbox mode (`read-only` vs `workspace-write`) is set once per Codex thread, at the turn that creates it, from a `--write` flag. Resuming a thread does not change its sandbox mode**, no matter what you ask for on the resumed turn.

## When to Use

- Before dispatching any Codex task (analysis, review, or "write this code").
- When a Codex task reports it *wanted* to write files but the sandbox rejected the write (`apply_patch`/`writing is blocked by read-only sandbox`) even though you thought you asked for write access.
- When deciding whether to `--resume` a prior thread or start `--fresh`.

## Core Pattern

**Pick sandbox mode by matching the flag to the thread's origin turn, not to the current request:**

| You want | Flag | Why |
|---|---|---|
| An unbiased second opinion / review that must not touch files | `--fresh` (no `--write`) | Creates a new read-only thread. This is also what you get by default if you don't ask for writes. |
| Codex to actually edit code | `--fresh --write` | Start a *new* thread with write access baked in from turn one. |
| To continue a thread that already writes | `--resume --write` | `--write` here is a no-op if the thread was already write-capable, but keep passing it — omitting it doesn't downgrade an existing write thread, it just avoids confusion about why it's there. |
| To continue a thread that was created read-only, but now you want it to write | **Don't.** Start `--fresh --write` instead. | The sandbox can't be upgraded on a resumed turn. Resuming a review-only thread and asking it to fix the bug it just found will fail with a read-only sandbox error, even with `--write` on that turn. |

This is why a review pass and the fix for what it finds are naturally two separate dispatches: `--fresh` (no write) for the review, then `--fresh --write` for the fix — never `--resume` from review straight into writing.

## Other conventions worth keeping

- **Append `/goal` to the end of write-task prompts.** Improves Codex's adherence to the full task in one pass.
- **Never trust a Codex task's self-reported test/build results as-is.** Its sandbox may have its own permission quirks (temp-dir access, blocked subprocess spawning for `npm`/`vite`) that produce misleading pass/fail signals. After any Codex write task, independently re-run the real test suite and the real build tool (not a substitute like esbuild-for-Vite) in your own environment before treating the task as done.
- **Give Codex the plan/spec file path, not a re-paraphrased spec.** If a plan file already has the authoritative contract (route tables, state machines, acceptance assertions), point Codex at it and tell it to treat that file as authoritative — don't retype the spec into the prompt where it can drift from the written plan.
- **For an independent second opinion, use a genuinely fresh thread**, not a resume of the thread that wrote the code under review. A resumed thread has seen its own reasoning and will tend to confirm it.

## When you hit a real permission dead end

If `--fresh --write` still can't write (not a stale read-only thread — an actual environment restriction even on a freshly-created write thread), don't reach for `-c danger-full-access` or `--dangerously-bypass-approvals-and-sandbox` on your own judgment. This repo's own `AGENTS.md` and `docs/codex-project-guide.md` are explicit that these are not to be used as defaults to solve ordinary development problems, and a stuck sandbox on a `--write` thread is usually a configuration problem (check whether `.codex/config.toml`'s `sandbox_mode = "workspace-write"` is actually being picked up), not a reason to disable sandboxing entirely.

If you've confirmed it's a genuine dead end and the task can't proceed otherwise:

1. Do the fix yourself directly (you almost always have write access even when Codex's sandbox doesn't) — this is usually faster than escalating anyway.
2. Only if you truly need Codex specifically to perform the write (e.g. the task requires its long-running/background execution), stop and use `AskUserQuestion` to ask the user for explicit, one-time authorization before adding `-c danger-full-access` or `--dangerously-bypass-approvals-and-sandbox` to that specific dispatch. State plainly what command will run and why weaker options were insufficient. Never apply it silently, never make it the default for future dispatches, and don't carry the authorization forward to unrelated tasks.

## Common Mistakes

- Resuming a review thread to also get the fix written — fails silently confusing ("it says read-only but I asked for write this time"). Start fresh instead.
- Treating a Codex-reported `npm run build` success as ground truth when its sandbox blocks subprocess spawning — it may have silently substituted a different bundler. Rebuild yourself.
- Reaching for the dangerous bypass flags as a first response to any sandbox error, instead of first checking whether the request simply needed `--fresh --write` or a config fix.
