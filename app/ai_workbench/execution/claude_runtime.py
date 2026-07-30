from __future__ import annotations

import json
import queue
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Iterable

from .codex_runtime import ExecutionCapabilities, ExecutionResult, _event, _read_stream


@dataclass
class ClaudeStepProcess:
    """Own exactly one Claude CLI process for one Workbench Step."""

    process: Any
    argv: tuple[str, ...]
    uncertain_session: bool = False


class ClaudeAdapter:
    """Run one short-lived Claude CLI process per Step and normalize stream-json."""

    capabilities = ExecutionCapabilities(fork=True, native_approval=False, structured_events=True)

    def __init__(self, executable: str | tuple[str, ...] = "claude", *, cwd: str | None = None,
                 env: dict[str, str] | None = None, on_process: Any | None = None, on_event: Any | None = None):
        self.executable = (executable,) if isinstance(executable, str) else tuple(executable)
        self.cwd = cwd
        self.env = env
        self.on_process = on_process
        self.on_event = on_event

    def _spawn(self, prompt: str, *, session_id: str | None = None, fork: bool = False,
               max_budget: str | float | None = None, model: str | None = None, permission_mode: str | None = None,
               allowed_tools: Iterable[str] = (), disallowed_tools: Iterable[str] = (),
               use_continue: bool = False) -> ClaudeStepProcess:
        """Build argv and spawn one isolated Claude Step process."""
        # Claude 2.1.x requires --verbose when --print is paired with the
        # stream-json output contract; without it the process rejects the
        # request before creating or resuming a native session.
        argv = list(self.executable) + ["-p", prompt, "--verbose", "--output-format", "stream-json", "--include-partial-messages"]
        uncertain = False
        if session_id:
            argv += ["--resume", session_id]
        elif use_continue:
            argv += ["--continue"]
            uncertain = True
        if fork:
            argv.append("--fork-session")
        if max_budget is not None:
            argv += ["--max-budget-usd", str(max_budget)]
        if model:
            argv += ["--model", model]
        if permission_mode:
            argv += ["--permission-mode", permission_mode]
        for tool in allowed_tools:
            argv += ["--allowedTools", tool]
        for tool in disallowed_tools:
            argv += ["--disallowedTools", tool]
        process = subprocess.Popen(tuple(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace", cwd=self.cwd, env=self.env)
        if self.on_process:
            self.on_process(process)
        return ClaudeStepProcess(process, tuple(argv), uncertain)

    def start_session(self, prompt: str, **options: Any) -> ClaudeStepProcess:
        """Start one new Step process; Claude's native session id is read from init."""
        return self._spawn(prompt, session_id=None, use_continue=False, **options)

    def resume_session(self, session_id: str, prompt: str, **options: Any) -> ClaudeStepProcess:
        """Resume a known native session explicitly in a new Step process."""
        if not session_id:
            raise ValueError("session_id is required for resume_session")
        return self._spawn(prompt, session_id=session_id, use_continue=True if session_id is None else False, **options)

    def fork_session(self, session_id: str, prompt: str, **options: Any) -> ClaudeStepProcess:
        """Fork a known native session in a new Step process."""
        if not session_id:
            raise ValueError("session_id is required for fork_session")
        return self._spawn(prompt, session_id=session_id, fork=True, **options)

    def start_turn(self, prompt: str, *, session_id: str | None = None, **options: Any) -> ClaudeStepProcess:
        """Start the process for one turn, using explicit resume when available."""
        return self._spawn(prompt, session_id=session_id, use_continue=session_id is None, **options)

    def stream_events(self, step: ClaudeStepProcess) -> ExecutionResult:
        """Drain one Step's real stdout/stderr and map every record to unified events."""
        process = step.process
        events: list[dict[str, Any]] = []
        stderr_lines: list[str] = []
        session_id = None
        lines: queue.Queue[tuple[str, str]] = queue.Queue()
        threading.Thread(target=_read_stream, args=(process.stdout, "stdout", lines), daemon=True).start()
        threading.Thread(target=_read_stream, args=(process.stderr, "stderr", lines), daemon=True).start()
        closed: set[str] = set()
        while len(closed) < 2:
            try:
                label, line = lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if not line:
                closed.add(label)
                continue
            if label == "stderr":
                stderr_lines.append(line)
                self._emit(events, self._claude_event("diagnostic.stderr", {"raw": line.rstrip("\r\n")}, "stderr"))
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                self._emit(events, self._claude_event("unknown", {"raw": line.rstrip("\r\n")}, "non_json"))
                continue
            if not isinstance(record, dict):
                self._emit(events, self._claude_event("unknown", {"raw": record}, "non_object"))
                continue
            mapped = self._map_record(record)
            if mapped["event_type"] == "run.started":
                session_id = record.get("session_id") or record.get("sessionId") or record.get("id")
            self._emit(events, mapped)
        process.wait()
        if process.returncode:
            self._emit(events, self._claude_event("run.failed", {"exit_code": process.returncode}, "exit"))
        elif not any(e["event_type"] == "run.completed" for e in events):
            self._emit(events, self._claude_event("run.completed", {}, "exit"))
        if step.uncertain_session:
            for event in events:
                event["session_confidence"] = "low"
                event["session_id"] = session_id
        return ExecutionResult(events, "claude_step_process", self.capabilities,
                               "failed" if process.returncode else "completed", "".join(stderr_lines))

    def _emit(self, events: list[dict[str, Any]], event: dict[str, Any]) -> None:
        events.append(event)
        if self.on_event:
            self.on_event(dict(event))

    @staticmethod
    def _claude_event(kind: str, payload: dict[str, Any], source_type: str) -> dict[str, Any]:
        """Build a Claude event while retaining the shared Codex envelope."""
        event = _event(kind, payload, source_type, "claude_cli")
        event["source_tool"] = "claude"
        return event

    @staticmethod
    def _map_record(record: dict[str, Any]) -> dict[str, Any]:
        """Map Claude stream-json record types onto the Codex unified event shape."""
        typ = str(record.get("type") or record.get("event") or "unknown")
        low = typ.lower()
        if low in {"init", "session_started", "system"}:
            kind = "run.started"
        elif low in {"partial", "stream_event", "content_block_delta"}:
            kind = "message.delta"
        elif low in {"assistant", "assistant_message"}:
            kind = "message.completed"
        elif low in {"tool_use", "tool_started"}:
            kind = "tool.started"
        elif low in {"tool_result", "tool_output"}:
            kind = "tool.output"
        elif low in {"result", "completed", "turn_completed"}:
            kind = "run.completed"
        elif low == "hook":
            kind = "hook.event"
        elif low in {"error", "failed"}:
            kind = "error"
        elif "usage" in record or low in {"usage", "token_usage"}:
            kind = "usage.updated"
        else:
            kind = "unknown"
        return ClaudeAdapter._claude_event(kind, record, typ)
