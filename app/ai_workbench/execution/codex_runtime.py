from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable


METHODS = frozenset({"initialize", "initialized", "thread/list", "thread/read", "thread/start", "thread/resume", "thread/fork", "turn/start", "turn/interrupt", "experimentalApi"})
APPROVAL_METHODS = frozenset({
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
})


def resolve_codex_executable() -> str:
    """Return a directly executable Codex binary, including npm installs on Windows."""
    override = os.environ.get("AI_WORKBENCH_CODEX_EXECUTABLE")
    if override:
        return override
    if os.name == "nt":
        direct = shutil.which("codex.exe")
        if direct:
            return direct
        appdata = os.environ.get("APPDATA")
        if appdata:
            bundled = os.path.join(
                appdata, "npm", "node_modules", "@openai", "codex", "node_modules",
                "@openai", "codex-win32-x64", "vendor", "x86_64-pc-windows-msvc", "bin", "codex.exe",
            )
            if os.path.isfile(bundled):
                return bundled
        cmd = shutil.which("codex.cmd")
        if cmd:
            return cmd
    return shutil.which("codex") or "codex"


class AppServerFallback(Exception):
    """Raised only when the App Server transport or negotiated protocol is unusable."""


class BusinessError(Exception):
    """Raised for a valid App Server business response; it must not trigger fallback."""


@dataclass(frozen=True)
class ExecutionCapabilities:
    fork: bool = True
    native_approval: bool = True
    structured_events: bool = True


@dataclass
class ExecutionResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    execution_path: str = "codex_app_server"
    capabilities: ExecutionCapabilities = field(default_factory=ExecutionCapabilities)
    state: str = "completed"
    stderr: str = ""


def _event(kind: str, payload: dict[str, Any], source_type: str, path: str) -> dict[str, Any]:
    """Build the stable event envelope consumed by the persistence writer."""
    return {"event_type": kind, "payload": payload, "source_tool": "codex", "source_event_type": source_type, "execution_path": path}


def _map_record(record: dict[str, Any], path: str) -> dict[str, Any]:
    """Map one Codex JSON object to the unified event contract."""
    typ = str(record.get("type") or record.get("event") or record.get("method") or "unknown")
    low = typ.lower()
    if low in {"session_started", "thread_started", "thread.start", "session", "thread"}:
        kind = "run.started"
    elif low in {"user", "user_message", "prompt"}:
        kind = "user.message"
    elif low in {"assistant_delta", "message_delta", "assistant.delta", "delta"}:
        kind = "message.delta"
    elif low in {"assistant", "assistant_message", "message_completed", "assistant.completed"}:
        kind = "message.completed"
    elif low in {"tool_call", "tool_started", "tool_use"}:
        kind = "tool.started"
    elif low in {"tool_result", "tool_output"}:
        kind = "tool.output"
    elif low in {"tool_completed", "tool_done"}:
        kind = "tool.completed"
    elif low in {"command_output", "exec_output", "command.stdout"}:
        kind = "command.output"
    elif low in {"file_changed", "file_change", "diff"}:
        kind = "file.changed"
    elif low in {"usage", "usage_snapshot", "token_usage"} or "usage" in record:
        kind = "usage.updated"
    elif low in {"error", "failed", "rejected"}:
        kind = "error"
    elif low in {"turn_completed", "turn.completed", "completed"}:
        kind = "run.completed"
    else:
        kind = "unknown"
    return _event(kind, record, typ, path)


def _read_stream(stream: Any, label: str, out: queue.Queue[tuple[str, str]]) -> None:
    """Read one child stream independently so stderr can never contaminate stdout JSONL."""
    for line in iter(stream.readline, ""):
        out.put((label, line))
    out.put((label, ""))


class AppServerClient:
    """Run the supported Codex App Server stdio protocol and normalize its output."""

    def __init__(self, argv: Iterable[str] | None = None, *, handshake_timeout: float = 3.0,
                 cwd: str | None = None, env: dict[str, str] | None = None, on_process: Any | None = None,
                 approval_handler: Any | None = None, approval_delivery_handler: Any | None = None, on_event: Any | None = None):
        self.argv = tuple(argv) if argv is not None else (resolve_codex_executable(), "app-server")
        self.handshake_timeout = handshake_timeout
        self.cwd = cwd
        self.env = env
        self.on_process = on_process
        self.approval_handler = approval_handler
        self.approval_delivery_handler = approval_delivery_handler
        self.on_event = on_event
        self._next_id = 1
        self.turn_submitted = False

    def run(self, prompt: str, *, mode: str = "new", session_id: str | None = None, fork_from: str | None = None,
            model: str | None = None, approval_policy: str = "on-request") -> ExecutionResult:
        """Spawn App Server, negotiate, start the requested thread/turn, and collect events."""
        try:
            process = subprocess.Popen(self.argv, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1)
        except (FileNotFoundError, OSError) as exc:
            raise AppServerFallback("app-server spawn failed") from exc
        if self.on_process:
            self.on_process(process)
        q: queue.Queue[tuple[str, str]] = queue.Queue()
        threading.Thread(target=_read_stream, args=(process.stdout, "stdout", q), daemon=True).start()
        threading.Thread(target=_read_stream, args=(process.stderr, "stderr", q), daemon=True).start()
        events: list[dict[str, Any]] = []
        self._stderr_lines: list[str] = []
        try:
            response = self._request(process, {
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "ai-coding-workbench",
                        "title": "AI Coding Workbench",
                        "version": "0.1.0",
                    },
                    "capabilities": {
                        "experimentalApi": False,
                        "requestAttestation": False,
                        "optOutNotificationMethods": [],
                    },
                },
            }, q, self.handshake_timeout)
            if response.get("error"):
                code = str(response["error"].get("code", ""))
                if "unsupported" in code.lower() or response["error"].get("data") == "unsupported_capability":
                    raise AppServerFallback("unsupported capability")
                raise BusinessError(str(response["error"]))
            version = response.get("result", {}).get("protocolVersion")
            if version not in (None, "1", 1):
                raise AppServerFallback("protocol version mismatch")
            self._notify(process, "initialized")
            method = {"new": "thread/start", "resume": "thread/resume", "fork": "thread/fork"}.get(mode, "thread/start")
            params: dict[str, Any] = {
                "cwd": self.cwd,
                "approvalPolicy": approval_policy,
                "sandbox": "read-only",
            }
            if method == "thread/resume":
                if not session_id:
                    raise BusinessError("resume requires a native thread id")
                params["threadId"] = session_id
            if method == "thread/fork":
                source_id = fork_from or session_id
                if not source_id:
                    raise BusinessError("fork requires a native thread id")
                params["threadId"] = source_id
            thread_response = self._request(process, {"method": method, "params": params}, q, self.handshake_timeout)
            if thread_response.get("error"):
                raise BusinessError(str(thread_response["error"]))
            result_payload = thread_response.get("result", {})
            thread_id = result_payload.get("threadId") or result_payload.get("thread", {}).get("id")
            if not thread_id:
                raise BusinessError("thread response did not include a thread id")
            self._emit(events, _event("run.started", {"thread_id": thread_id, "session_id": thread_id}, "thread", "codex_app_server"))
            self.turn_submitted = True
            turn_params: dict[str, Any] = {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt, "text_elements": []}],
                "cwd": self.cwd,
                "approvalPolicy": approval_policy,
            }
            if model:
                turn_params["model"] = model
            self._request(process, {
                "method": "turn/start",
                "params": turn_params,
            }, q, self.handshake_timeout)
            for notification in getattr(self, "_pending_notifications", []):
                self._emit(events, _map_record(notification, "codex_app_server"))
            self._pending_notifications = []
            self._collect(process, q, events)
            return ExecutionResult(events, stderr="".join(x[1] for x in self._stderr_lines))
        except AppServerFallback:
            process.kill(); process.wait(); raise
        except BusinessError:
            process.kill(); process.wait(); raise
        except TimeoutError as exc:
            process.kill(); process.wait()
            if self.turn_submitted: raise BusinessError("turn submitted; execution interrupted") from exc
            raise AppServerFallback("handshake timeout") from exc

    def _send(self, process: Any, message: dict[str, Any]) -> int | None:
        """Write one JSONL protocol message, assigning ids only to requests."""
        if "id" not in message and message["method"] != "initialized":
            message["id"] = self._next_id; self._next_id += 1
        process.stdin.write(json.dumps(message) + "\n"); process.stdin.flush()
        return message.get("id")

    def _notify(self, process: Any, method: str, params: dict[str, Any] | None = None) -> None:
        if method not in METHODS: raise ValueError(method)
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        self._send(process, message)

    def _request(self, process: Any, message: dict[str, Any], q: queue.Queue, timeout: float) -> dict[str, Any]:
        """Send a whitelisted request and await its matching response while dispatching notifications."""
        if message["method"] not in METHODS: raise ValueError(message["method"])
        wanted = self._send(process, message); deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try: label, line = q.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty: break
            if label == "stderr": self._stderr_lines = getattr(self, "_stderr_lines", []) + ([line] if line else []); continue
            if not line: continue
            try: item = json.loads(line)
            except json.JSONDecodeError: continue
            if item.get("id") == wanted: return item
            if "method" in item: self._pending_notifications.append(item) if hasattr(self, "_pending_notifications") else setattr(self, "_pending_notifications", [item])
        raise TimeoutError("protocol response timeout")

    def _collect(self, process: Any, q: queue.Queue, events: list[dict[str, Any]]) -> None:
        """Drain child output and retain malformed or unknown records as raw events."""
        while process.poll() is None or not q.empty():
            try: label, line = q.get(timeout=0.1)
            except queue.Empty: continue
            if not line: continue
            if label == "stderr": self._emit(events, _event("diagnostic.stderr", {"raw": line.rstrip("\r\n")}, "stderr", "codex_app_server")); continue
            try: item = json.loads(line)
            except json.JSONDecodeError: self._emit(events, _event("unknown", {"raw": line.rstrip("\r\n")}, "non_json", "codex_app_server")); continue
            if item.get("id") is not None and item.get("method") in APPROVAL_METHODS:
                self._respond_to_approval(process, item, events)
                continue
            self._emit(events, _map_record(item, "codex_app_server"))

    def _respond_to_approval(self, process: Any, request: dict[str, Any], events: list[dict[str, Any]]) -> None:
        """Bridge only schema-confirmed one-shot command/file approvals.

        The callback blocks the collection loop while the local browser decides;
        stdin stays open so its JSON-RPC response reaches the same app-server
        session.  Unsupported server requests are explicitly declined rather
        than represented as a fake actionable approval in the UI.
        """
        if self.approval_handler is None:
            result: dict[str, Any] = {"decision": "decline"}
        else:
            result = self.approval_handler(request)
        try:
            process.stdin.write(json.dumps({"id": request["id"], "result": result}) + "\n")
            process.stdin.flush()
            if self.approval_delivery_handler:
                self.approval_delivery_handler(str(request["id"]), str(result.get("decision") or "decline"), True)
            self._emit(events, _event("approval.resolved", {"native_request_id": str(request["id"]), "decision": result.get("decision")}, request["method"], "codex_app_server"))
        except (BrokenPipeError, OSError, ValueError):
            if self.approval_delivery_handler:
                self.approval_delivery_handler(str(request["id"]), str(result.get("decision") or "decline"), False)
            self._emit(events, _event("error", {"code": "approval_delivery_failed", "native_request_id": str(request["id"])}, request["method"], "codex_app_server"))

    def _emit(self, events: list[dict[str, Any]], event: dict[str, Any]) -> None:
        events.append(event)
        if self.on_event:
            self.on_event(dict(event))


class CodexExecClient:
    """Run codex exec JSONL through stdin and normalize every supported record."""

    capabilities = ExecutionCapabilities(fork=False, native_approval=False, structured_events=True)

    def __init__(self, executable: str | tuple[str, ...] | None = None, *, cwd: str | None = None,
                 env: dict[str, str] | None = None, on_process: Any | None = None, on_event: Any | None = None):
        self.executable = executable or resolve_codex_executable()
        self.cwd = cwd
        self.env = env
        self.on_process = on_process
        self.on_event = on_event

    def run(self, prompt: str, *, session_id: str | None = None) -> ExecutionResult:
        """Spawn exec with argv-only control and send the prompt through stdin."""
        prefix = (self.executable,) if isinstance(self.executable, str) else self.executable
        argv = prefix + (("exec", "resume", session_id, "--json") if session_id else ("exec", "--json"))
        process = subprocess.Popen(argv, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        if self.on_process:
            self.on_process(process)
        process.stdin.write(prompt); process.stdin.close()
        events: list[dict[str, Any]] = []
        stderr_lines: list[str] = []
        lines: queue.Queue[tuple[str, str]] = queue.Queue()
        threading.Thread(target=_read_stream, args=(process.stdout, "stdout", lines), daemon=True).start()
        threading.Thread(target=_read_stream, args=(process.stderr, "stderr", lines), daemon=True).start()
        closed: set[str] = set()
        while len(closed) < 2:
            try: label, line = lines.get(timeout=0.1)
            except queue.Empty: continue
            if not line:
                closed.add(label); continue
            if label == "stderr":
                stderr_lines.append(line)
                self._emit(events, _event("diagnostic.stderr", {"raw": line.rstrip("\r\n")}, "stderr", "codex_exec")); continue
            try: self._emit(events, _map_record(json.loads(line), "codex_exec"))
            except json.JSONDecodeError: self._emit(events, _event("unknown", {"raw": line.rstrip("\r\n")}, "non_json", "codex_exec"))
        process.wait()
        if process.returncode: self._emit(events, _event("run.failed", {"exit_code": process.returncode}, "exit", "codex_exec"))
        elif not any(e["event_type"] == "run.completed" for e in events): self._emit(events, _event("run.completed", {}, "exit", "codex_exec"))
        return ExecutionResult(events, "codex_exec", self.capabilities, "failed" if process.returncode else "completed", "".join(stderr_lines))

    def _emit(self, events: list[dict[str, Any]], event: dict[str, Any]) -> None:
        events.append(event)
        if self.on_event:
            self.on_event(dict(event))


def execute_with_fallback(prompt: str, *, app: AppServerClient, exec_client: CodexExecClient, mode: str = "new", session_id: str | None = None,
                          model: str | None = None, approval_policy: str = "on-request") -> ExecutionResult:
    """Use exec only for transport/capability failures, never for business errors."""
    try:
        return app.run(prompt, mode=mode, session_id=session_id, model=model, approval_policy=approval_policy)
    except AppServerFallback:
        if mode == "fork":
            # codex exec has no explicit fork contract.  Falling back would
            # silently turn a requested fork into a resume/new execution.
            raise BusinessError("fork requires a compatible Codex App Server")
        return exec_client.run(prompt, session_id=session_id)
    except BusinessError:
        raise
