"""Process supervision and bounded live-event delivery primitives."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

try:
    import _winapi
except ImportError:  # pragma: no cover - Windows-only implementation detail
    _winapi = None


@dataclass(frozen=True)
class ProcessRunResult:
    argv: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    status: str
    duration_seconds: float


class _WindowsJob:
    """Own one Windows Job Object and terminate every process assigned to it."""

    def __init__(self) -> None:
        self.handle = None
        if os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32
        self.handle = kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        class _BasicLimit(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32), ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]
        class _IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class _ExtendedLimit(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", _IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        limits = _ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")

    def assign(self, process: subprocess.Popen[Any]) -> None:
        """Assign a suspended child process to this job before it can execute."""
        if self.handle is not None and not self._kernel32.AssignProcessToJobObject(self.handle, process._handle):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")

    def terminate(self) -> None:
        """Terminate all processes currently in the job."""
        if self.handle is not None:
            self._kernel32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        """Close the job, applying kill-on-close to its process tree."""
        if self.handle is not None:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


def attach_process_to_job(process: subprocess.Popen[Any]) -> _WindowsJob:
    """Create a kill-on-close Job Object and attach one managed CLI process."""
    job = _WindowsJob()
    try:
        job.assign(process)
    except Exception:
        job.close()
        raise
    return job


def terminate_process_job(job: _WindowsJob | None) -> None:
    """End and release a coordinator-owned Job Object when one is available."""
    if job is None:
        return
    job.terminate()
    job.close()


class RunState:
    """Serialize cancellation and terminal-state decisions for one run."""

    def __init__(self, initial: str = "running") -> None:
        self.state = initial
        self._lock = threading.Lock()
        self.termination_started = False

    def request_cancel(self) -> bool:
        """Move a live run to cancel_requested once, returning whether work is needed."""
        with self._lock:
            if self.state in {"succeeded", "failed", "cancelled", "interrupted"}:
                return False
            if self.state == "cancel_requested":
                return False
            self.state = "cancel_requested"
            return True

    def begin_termination(self) -> bool:
        """Move cancel_requested to cancelling exactly once."""
        with self._lock:
            if self.state != "cancel_requested" or self.termination_started:
                return False
            self.termination_started = True
            self.state = "cancelling"
            return True

    def finish(self, state: str) -> bool:
        """Set a terminal state without overwriting a completed successful run."""
        with self._lock:
            if self.state == "succeeded" or self.state in {"failed", "cancelled", "interrupted"}:
                return False
            self.state = state
            return True


class EventRingBuffer:
    """Bounded per-run buffer that preserves critical events and merges deltas."""

    _CRITICAL = {"tool.started", "tool.completed", "approval.required", "approval.resolved", "usage.updated", "state.changed", "error"}

    def __init__(self, capacity: int = 256) -> None:
        self.capacity = max(1, capacity)
        self._items: deque[dict[str, Any]] = deque()
        self._lock = threading.Lock()
        self.gap_sequence: int | None = None

    def append(self, event: dict[str, Any], *, consumer_blocked: bool = False) -> None:
        """Append without blocking the producer; merge/drop only reconstructable deltas."""
        with self._lock:
            kind = event.get("event_type", event.get("type"))
            if consumer_blocked and kind == "message.delta" and self._items and self._items[-1].get("event_type") == kind and self._items[-1].get("payload", {}).get("message_id") == event.get("payload", {}).get("message_id"):
                self._items[-1]["payload"]["text_delta"] = self._items[-1].get("payload", {}).get("text_delta", "") + event.get("payload", {}).get("text_delta", "")
                self.gap_sequence = event.get("sequence_no", self.gap_sequence)
                return
            if len(self._items) >= self.capacity:
                removable = next((i for i, item in enumerate(self._items) if item.get("event_type", item.get("type")) == "message.delta"), None)
                if removable is None and kind not in self._CRITICAL:
                    self.gap_sequence = event.get("sequence_no", self.gap_sequence)
                    return
                if removable is not None:
                    del self._items[removable]
                    self.gap_sequence = event.get("sequence_no", self.gap_sequence)
            self._items.append(dict(event))

    def drain(self) -> list[dict[str, Any]]:
        """Return buffered events and a stream_gap marker when reconstructable events changed."""
        with self._lock:
            items = list(self._items)
            self._items.clear()
            if self.gap_sequence is not None:
                items.insert(0, {"event_type": "stream_gap", "last_persisted_sequence_no": self.gap_sequence})
                self.gap_sequence = None
            return items


def reconcile_stale_runs(conn: Any) -> int:
    """Mark non-terminal persisted runs interrupted after a supervisor restart."""
    cursor = conn.execute("UPDATE runs SET state='interrupted', failure_code='supervisor_restart' WHERE state IN ('starting','running','waiting_approval','cancel_requested','cancelling')")
    conn.commit()
    return cursor.rowcount


def terminate_process_tree(process: subprocess.Popen[Any], *, grace_seconds: float = 0.25) -> bool:
    """Stop a registered CLI process and its descendants without invoking a shell.

    Coordinator-owned adapters call this only after a durable cancellation request.
    On Windows ``taskkill /T`` is the portable process-tree primitive available
    to independently spawned Codex and Claude CLI children.  Other platforms
    terminate the process group created by the adapter when possible.
    """
    if process.poll() is not None:
        return True
    try:
        if os.name == "nt":
            subprocess.run(
                ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=max(1.0, grace_seconds + 0.5), check=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        try:
            process.wait(timeout=max(0.1, grace_seconds))
        except subprocess.TimeoutExpired:
            return False
        return process.poll() is not None
    except (OSError, subprocess.SubprocessError):
        return process.poll() is not None


def run_process(argv: tuple[str, ...], *, stdin_text: str | None = None, timeout_seconds: float = 10.0, max_output_chars: int = 1_000_000, grace_seconds: float = 0.25) -> ProcessRunResult:
    """Run argv under a tree supervisor and return bounded stdout/stderr results."""
    started = time.monotonic()
    # Popen does not retain the primary thread handle needed to resume a suspended
    # process. Assign immediately after CreateProcess; Job Object owns descendants.
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    job = _WindowsJob()
    process = subprocess.Popen(list(argv), stdin=subprocess.PIPE if stdin_text is not None else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=creationflags)
    stdout = ""
    stderr = ""
    try:
        job.assign(process)
        try:
            stdout, stderr = process.communicate(input=stdin_text, timeout=timeout_seconds)
            status = "completed" if process.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            if process.poll() is None:
                process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
                try:
                    stdout, stderr = process.communicate(timeout=grace_seconds)
                except subprocess.TimeoutExpired:
                    job.terminate()
                    stdout, stderr = process.communicate()
                status = "timeout"
            else:
                # The root exited, but a descendant may still hold the pipe
                # handles open. Tear down the job before collecting output so
                # a natural root exit wins without waiting for the child tree.
                job.terminate()
                stdout, stderr = process.communicate()
                status = "completed" if process.returncode == 0 else "failed"
        return ProcessRunResult(argv, process.returncode, _truncate(stdout, max_output_chars), _truncate(stderr, max_output_chars), status, time.monotonic() - started)
    finally:
        job.close()


def _truncate(value: str, max_chars: int) -> str:
    return value if len(value) <= max_chars else value[:max_chars] + "\n[truncated]"
