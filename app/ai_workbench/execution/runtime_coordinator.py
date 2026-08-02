"""Single-process owner for queued interactive runs.

The coordinator deliberately owns worker threads and live process handles instead
of letting HTTP request threads spawn CLIs.  SQLite remains the durable fact
source; the in-memory registry only enables cancellation while this process is
alive.
"""

from __future__ import annotations

import json
import os
import queue
import shlex
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from dataclasses import dataclass, field

from app.ai_workbench.approval import create_approval, record_approval_delivery
from app.ai_workbench.event_persistence import cleanup_expired_artifacts, persist_event, persist_status_change
from app.ai_workbench.execution.claude_runtime import ClaudeAdapter, resolve_claude_executable
from app.ai_workbench.execution.codex_runtime import AppServerClient, BusinessError, CodexExecClient, execute_with_fallback, resolve_codex_executable
from app.ai_workbench.execution.supervisor import reconcile_stale_runs
from app.ai_workbench.execution.supervisor import attach_process_to_job, terminate_process_job, terminate_process_tree
from app.ai_workbench.execution.runtime_baseline import record_runtime_baseline
from app.ai_workbench.runtime_stream import runtime_broadcaster
from app.ai_workbench.storage import SessionBusyError, acquire_writer_lease, connect_workbench_db, heartbeat_writer_lease, release_writer_lease


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _physical_session_key(tool: str, profile_id: str, native_session_id: str) -> str:
    """Stable lease identity for one physical native conversation."""
    return f"{tool}:{profile_id}:{native_session_id}"


@dataclass
class RuntimeRegistration:
    """One coordinator-owned live record for a run's native resources."""

    adapter: Any | None = None
    session_id: str | None = None
    process: Any | None = None
    job: Any | None = None
    lease_key: str | None = None
    lease_generation: int | None = None
    interrupt: Callable[[], bool] | None = None
    cancel_requested: bool = False
    approval_waiters: set[str] = field(default_factory=set)


class RuntimeCoordinator:
    """One local worker for Phase 3 manual runs.

    ``executor`` is intentionally injectable for API integration tests.  Normal
    development runs leave real execution disabled unless the process owner
    explicitly sets ``AI_WORKBENCH_REAL_EXECUTION=1``.
    """

    def __init__(self, db_path: Path, *, executor: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
                 baseline_recorder: Callable[[Any], Any] | None = None) -> None:
        self.db_path = Path(db_path)
        self.instance_id = str(uuid.uuid4())
        self._executor = executor
        self._baseline_recorder = baseline_recorder or record_runtime_baseline
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._stopped = False
        self._active: set[str] = set()
        self._processes: dict[str, Any] = {}
        self._process_jobs: dict[str, Any] = {}
        self._interrupts: dict[str, Callable[[], bool]] = {}
        self._termination_requested: set[str] = set()
        self._timeout_timers: dict[str, threading.Timer] = {}
        self._approval_waiters: dict[str, dict[str, Any]] = {}
        self._approval_native_ids: dict[str, str] = {}
        self._registry: dict[str, RuntimeRegistration] = {}
        # Coordinator-owned process-local fan-out; durable SQLite replay remains
        # authoritative when this in-memory path is unavailable.
        self.broadcaster = runtime_broadcaster
        self._lock = threading.RLock()

    @property
    def real_execution_enabled(self) -> bool:
        return os.environ.get("AI_WORKBENCH_REAL_EXECUTION") == "1"

    @property
    def execution_available(self) -> bool:
        """Whether this process may accept a newly submitted run."""
        with self._lock:
            return not self._stopped and (self._executor is not None or self.real_execution_enabled)

    def start(self) -> None:
        with self._lock:
            if self._stopped:
                raise RuntimeError("runtime coordinator has stopped")
            if self._thread and self._thread.is_alive():
                return
            with connect_workbench_db(self.db_path) as conn:
                reconcile_stale_runs(conn)
                cleanup_expired_artifacts(conn)
                if self._executor is None:
                    self._baseline_recorder(conn)
            self._stop.clear()
            self._thread = threading.Thread(target=self._worker, name="ai-workbench-runtime", daemon=True)
            self._thread.start()

    def stop(self, *, join_timeout: float = 5.0) -> None:
        with self._lock:
            self._stopped = True
            self._stop.set()
            processes = tuple((run_id, process, self._process_jobs.get(run_id)) for run_id, process in self._processes.items())
            waiters = tuple(self._approval_waiters.values())
        for waiter in waiters:
            waiter["decision"] = "cancel"
            waiter["event"].set()
        for _, process, job in processes:
            terminate_process_job(job)
            terminate_process_tree(process)
        self._queue.put(None)
        if self._thread:
            self._thread.join(join_timeout)
        with connect_workbench_db(self.db_path) as conn:
            reconcile_stale_runs(conn)

    def enqueue(self, run_id: str) -> None:
        with self._lock:
            if self._stopped:
                raise RuntimeError("runtime coordinator is stopping")
            self.start()
            self._queue.put(run_id)

    def is_active(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._active

    def request_cancel(self, run_id: str) -> bool:
        """Interrupt the currently registered CLI tree, if it has spawned.

        The API has already persisted ``cancel_requested`` before reaching this
        method.  Returning False means the worker has not spawned yet (or has
        already exited); its durable state remains the source of truth.
        """
        with self._lock:
            registration = self._registry.get(run_id)
            if registration and registration.lease_key and registration.lease_generation:
                if not self._lease_is_current(run_id, registration.lease_key, registration.lease_generation):
                    return False
            process = self._processes.get(run_id)
            job = self._process_jobs.get(run_id)
            interrupt = self._interrupts.get(run_id)
            waiters = [waiter for waiter in self._approval_waiters.values() if waiter["run_id"] == run_id]
            should_terminate = process is not None and run_id not in self._termination_requested
            if should_terminate:
                self._termination_requested.add(run_id)
                registration = self._registry.get(run_id)
                if registration:
                    registration.cancel_requested = True
        for waiter in waiters:
            waiter["decision"] = "cancel"
            waiter["event"].set()
        if not should_terminate:
            return False
        if interrupt is not None:
            try:
                if interrupt():
                    timer = threading.Timer(0.5, self._force_terminate_if_alive, args=(run_id, process, job))
                    timer.daemon = True
                    timer.start()
                    return True
            except Exception:
                pass
        terminate_process_job(job)
        return bool(terminate_process_tree(process))

    def resolve_approval(self, request_id: str, decision: str) -> bool:
        """Wake exactly one live native approval waiter after its DB decision."""
        with self._lock:
            waiter = self._approval_waiters.get(request_id)
        if waiter is None:
            return False
        if not waiter["lease_key"] or not self._lease_is_current(waiter["run_id"], waiter["lease_key"], waiter["lease_generation"]):
            return False
        waiter["decision"] = decision
        waiter["event"].set()
        return True

    def _worker(self) -> None:
        while not self._stop.is_set():
            run_id = self._queue.get()
            if run_id is None:
                return
            try:
                self._execute(run_id)
            except Exception:
                # _execute records known failures. Keep the worker alive even
                # if an unexpected persistence failure reaches this boundary.
                continue

    def _execute(self, run_id: str) -> None:
        lease: tuple[str, int] | None = None
        run_data: dict[str, Any] | None = None
        with self._lock:
            self._active.add(run_id)
        try:
            with connect_workbench_db(self.db_path) as conn:
                run = conn.execute(
                    "SELECT r.*, p.config_root, p.session_root FROM runs r JOIN tool_profiles p ON p.id=r.profile_id WHERE r.id=?",
                    (run_id,),
                ).fetchone()
                step = conn.execute("SELECT * FROM run_steps WHERE run_id=? ORDER BY ordinal", (run_id,)).fetchone()
                if run is None or step is None or run["state"] != "queued":
                    return
                persist_status_change(
                    conn, run_id=run_id, step_id=step["id"], state="starting", source_tool=run["tool"],
                    reason="runtime_claimed", step_state="starting",
                    run_updates={"runtime_instance_id": self.instance_id, "started_at": _now()},
                )
                run = conn.execute(
                    "SELECT r.*, p.config_root, p.session_root FROM runs r JOIN tool_profiles p ON p.id=r.profile_id WHERE r.id=?",
                    (run_id,),
                ).fetchone()
                step = conn.execute("SELECT * FROM run_steps WHERE id=?", (step["id"],)).fetchone()

            run = dict(run)
            step = dict(step)
            run_data = run
            self._register_run(run)
            if run["source_native_session_id"]:
                lease = self._acquire_source_lease(run)
                run["lease_generation"] = lease[1]
                run["_lease_key"] = lease[0]

            if self._executor is not None:
                self._mark_running(run_id, step["id"], run["tool"], reason="fake_process_spawned")
                result = self._executor(dict(run), dict(step))
                events_already_persisted = False
            elif not self.real_execution_enabled:
                self._fail(run_id, step["id"], run["tool"], "real_execution_disabled", "Real model execution is disabled for this process")
                return
            else:
                result = self._execute_real(run, step)
                events_already_persisted = True

            self._persist_result(run_id, step["id"], run, result, events_already_persisted=events_already_persisted)
        except SessionBusyError as exc:
            self._fail(run_id, self._step_id(run_id), self._tool(run_id), "session_busy", str(exc))
        except BusinessError as exc:
            self._fail(run_id, self._step_id(run_id), self._tool(run_id), "execution_error", str(exc))
        except Exception as exc:
            self._fail(run_id, self._step_id(run_id), self._tool(run_id), "runner_error", str(exc))
        finally:
            with self._lock:
                self._active.discard(run_id)
                self._processes.pop(run_id, None)
                job = self._process_jobs.pop(run_id, None)
                self._interrupts.pop(run_id, None)
                self._registry.pop(run_id, None)
                self._termination_requested.discard(run_id)
                timer = self._timeout_timers.pop(run_id, None)
                if timer:
                    timer.cancel()
            terminate_process_job(job)
            active_lease = None
            if run_data and run_data.get("_lease_key") and run_data.get("lease_generation"):
                active_lease = (str(run_data["_lease_key"]), int(run_data["lease_generation"]))
            if active_lease or lease:
                try:
                    self._release_lease(run_id, active_lease or lease)
                except SessionBusyError:
                    # A lost lease is already a durable safety failure; do not
                    # let cleanup hide the original execution result.
                    pass

    def _execute_real(self, run: dict[str, Any], step: dict[str, Any]) -> Any:
        policy = json.loads(run["permission_policy_json"] or "{}")
        budget = json.loads(run["budget_policy_json"] or "{}")
        env = _profile_environment(run)
        if run["tool"] == "claude":
            executable = resolve_claude_executable()
            if not executable:
                raise BusinessError("claude executable unavailable")
            adapter = ClaudeAdapter(executable=executable, cwd=run["cwd"], env=env, on_process=lambda process: self._register_process(run["id"], process, run["tool"], step.get("timeout_ms")), on_event=lambda event: self._persist_live_event(run, step, event))
            self._set_adapter(run["id"], adapter)
            if run["mode"] == "resume":
                process = adapter.resume_session(run["source_native_session_id"], step["prompt_text"], **_claude_options(policy, budget, run["model"]))
            elif run["mode"] == "fork":
                process = adapter.fork_session(run["source_native_session_id"], step["prompt_text"], **_claude_options(policy, budget, run["model"]))
            else:
                process = adapter.start_session(step["prompt_text"], **_claude_options(policy, budget, run["model"]))
            return adapter.stream_events(process)
        codex_executable = resolve_codex_executable()
        app = AppServerClient(argv=(codex_executable, "app-server", "--stdio"), cwd=run["cwd"], env=env, on_process=lambda process: self._register_process(run["id"], process, run["tool"], step.get("timeout_ms")), on_cleanup=lambda process: self._cleanup_registered_process(run["id"], process), on_interrupt=lambda callback: self._register_interrupt(run["id"], callback), on_turn_submitted=lambda thread_id, turn_id: self._mark_turn_submitted(run["id"], step["id"], thread_id, turn_id), approval_handler=lambda request: self._await_native_approval(run, step, request), approval_delivery_handler=lambda native_id, decision, delivered: self._record_native_approval_delivery(run, step, native_id, decision, delivered), on_event=lambda event: self._persist_live_event(run, step, event))
        exec_client = CodexExecClient(codex_executable, cwd=run["cwd"], env=env, on_process=lambda process: self._register_process(run["id"], process, run["tool"], step.get("timeout_ms")), on_event=lambda event: self._persist_live_event(run, step, event))
        self._set_adapter(run["id"], app)
        result = execute_with_fallback(
            step["prompt_text"],
            app=app, exec_client=exec_client,
            mode=run["mode"],
            session_id=run["source_native_session_id"],
            model=run["model"],
            approval_policy=policy.get("approval_policy", "on-request"),
        )
        # The App Server can fall back only before a turn is accepted.  Make
        # that choice durable so the audit view never has to infer execution
        # semantics from stderr or a terminal state.
        self._persist_live_event(run, step, {
            "event_type": "run.execution_path_selected",
            "payload": {"execution_path": result.execution_path},
            "source_tool": "codex",
            "source_event_type": "execution_path_selected",
            "execution_path": result.execution_path,
        })
        return result

    def _register_run(self, run: dict[str, Any]) -> None:
        with self._lock:
            self._registry[run["id"]] = RuntimeRegistration(session_id=run.get("source_native_session_id"))

    def _set_adapter(self, run_id: str, adapter: Any) -> None:
        with self._lock:
            self._registry.setdefault(run_id, RuntimeRegistration()).adapter = adapter

    def _register_process(self, run_id: str, process: Any, tool: str, timeout_ms: int | None = None) -> None:
        job = attach_process_to_job(process)
        with self._lock:
            self._processes[run_id] = process
            self._process_jobs[run_id] = job
            registration = self._registry.setdefault(run_id, RuntimeRegistration())
            registration.process, registration.job = process, job
            if timeout_ms:
                previous = self._timeout_timers.pop(run_id, None)
                if previous:
                    previous.cancel()
                timer = threading.Timer(max(0.001, int(timeout_ms) / 1000), self._timeout_run, args=(run_id, tool))
                timer.daemon = True
                self._timeout_timers[run_id] = timer
                timer.start()
        cancel_already_requested = False
        with connect_workbench_db(self.db_path) as conn:
            step = conn.execute("SELECT id FROM run_steps WHERE run_id=? ORDER BY ordinal LIMIT 1", (run_id,)).fetchone()
            row = conn.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
            if step:
                self._mark_running(run_id, step["id"], tool, reason="process_spawned", conn=conn)
            cancel_already_requested = bool(row and row["state"] == "cancel_requested")
        if cancel_already_requested:
            # A cancellation may land after the worker claim but before spawn.
            # The freshly registered process must not get a chance to continue.
            self.request_cancel(run_id)

    def _cleanup_registered_process(self, run_id: str, process: Any) -> bool:
        """Terminate an App Server process through the coordinator registry."""
        with self._lock:
            if self._processes.get(run_id) is not process:
                return process.poll() is not None
            job = self._process_jobs.get(run_id)
            self._termination_requested.add(run_id)
        terminate_process_job(job)
        return terminate_process_tree(process)

    def _register_interrupt(self, run_id: str, callback: Callable[[], bool]) -> None:
        with self._lock:
            self._interrupts[run_id] = callback
            self._registry.setdefault(run_id, RuntimeRegistration()).interrupt = callback

    def _force_terminate_if_alive(self, run_id: str, process: Any, job: Any) -> None:
        if process.poll() is not None:
            return
        terminate_process_job(job)
        terminate_process_tree(process)

    def _termination_confirmed(self, run_id: str) -> bool:
        """A cancelled/timeout terminal fact needs a confirmed process exit.

        Injected test executors own no OS process and are already complete when
        they return, so their absent registration is a confirmed boundary.
        """
        with self._lock:
            process = self._processes.get(run_id)
        if process is None:
            return True
        try:
            return process.poll() is not None
        except (AttributeError, OSError):
            return False

    def _timeout_run(self, run_id: str, tool: str) -> None:
        """Persist a timeout before killing its registered process tree."""
        with connect_workbench_db(self.db_path) as conn:
            row = conn.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
            step = conn.execute("SELECT id FROM run_steps WHERE run_id=? ORDER BY ordinal LIMIT 1", (run_id,)).fetchone()
            if row and step and row["state"] in {"starting", "running", "waiting_approval"}:
                persist_status_change(
                    conn, run_id=run_id, step_id=step["id"], state="cancel_requested", source_tool=tool,
                    reason="timeout", step_state="cancel_requested",
                    run_updates={"cancel_requested_at": _now(), "failure_code": "timeout", "failure_message": "maximum run duration exceeded"},
                )
        self.request_cancel(run_id)

    def _mark_running(self, run_id: str, step_id: str, tool: str, *, reason: str, conn: Any | None = None) -> None:
        def update(target: Any) -> None:
            row = target.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
            if row and row["state"] == "starting":
                persist_status_change(
                    target, run_id=run_id, step_id=step_id, state="running", source_tool=tool,
                    reason=reason, step_state="running",
                    run_updates={"dispatch_state": "process_spawned"},
                )
        if conn is not None:
            update(conn)
        else:
            with connect_workbench_db(self.db_path) as target:
                update(target)

    def _mark_turn_submitted(self, run_id: str, step_id: str, thread_id: str, turn_id: str) -> None:
        """Record the precise point at which App Server accepted the turn."""
        with connect_workbench_db(self.db_path) as conn:
            persist_event(conn, {
                "event_id": str(uuid.uuid4()), "run_id": run_id, "step_id": step_id,
                "source_tool": "codex", "source_event_type": "turn/start",
                "event_type": "run.dispatch_submitted",
                "payload": {"thread_id": thread_id, "turn_id": turn_id},
            }, broadcast=self.broadcaster.publish, run_updates={"dispatch_state": "submitted", "dispatch_committed_at": _now(), "native_session_id": thread_id, "native_thread_id": thread_id})

    def _await_native_approval(self, run: dict[str, Any], step: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        """Persist a native command/file request and block only its CLI reader.

        This deliberately supports a one-shot decision only; session-wide
        acceptance is never synthesized by the Workbench.
        """
        params = dict(request.get("params") or {})
        method = str(request.get("method"))
        native_id = str(request.get("id"))
        operation = "command" if "commandExecution" in method else "file_change" if "fileChange" in method else "unknown"
        command = params.get("command")
        command_argv = shlex.split(command, posix=False) if isinstance(command, str) and command else None
        affected_paths = params.get("affectedPaths") or params.get("paths") or []
        if not isinstance(affected_paths, list) or not all(isinstance(path, str) for path in affected_paths):
            affected_paths = []
        network_targets = params.get("networkTargets") or params.get("network_targets") or params.get("url") or params.get("host") or []
        if isinstance(network_targets, str):
            network_targets = [network_targets]
        if not isinstance(network_targets, list) or not all(isinstance(target, str) for target in network_targets):
            network_targets = []
        risk_level = "high" if operation in {"command", "file_change"} else "unknown"
        approval_event = threading.Event()
        lease_key = str(run.get("_lease_key") or "")
        lease_generation = int(run.get("lease_generation") or 0)
        if not lease_key or not lease_generation or not self._lease_is_current(run["id"], lease_key, lease_generation):
            raise BusinessError("lease lost before native approval")
        waiter = {"run_id": run["id"], "event": approval_event, "decision": "cancel", "lease_key": lease_key, "lease_generation": lease_generation}
        with connect_workbench_db(self.db_path) as conn:
            item = create_approval(
                conn, run_id=run["id"], step_id=step["id"], native_request_id=native_id,
                operation=operation, target_summary=str(command or params.get("itemId") or "native approval"),
                risk_level=risk_level, command_argv=command_argv,
                cwd=params.get("cwd") or run["cwd"], affected_paths=affected_paths, network_targets=network_targets, reason=params.get("reason"),
            )
            # Install the waiter before broadcasting approval.required; a fast
            # local click must never race the native connection registration.
            with self._lock:
                self._approval_waiters[item["id"]] = waiter
                self._approval_native_ids[native_id] = item["id"]
                self._registry.setdefault(run["id"], RuntimeRegistration()).approval_waiters.add(item["id"])
            persist_status_change(
                conn, run_id=run["id"], step_id=step["id"], state="waiting_approval", source_tool="codex",
                reason=method, step_state="waiting_approval",
            )
            persist_event(conn, {
                "event_id": str(uuid.uuid4()), "run_id": run["id"], "step_id": step["id"],
                "source_tool": "codex", "source_event_type": method, "event_type": "approval.required",
                "payload": {"approval_id": item["id"], "native_request_id": native_id, "operation": operation,
                            "target_summary": item["target_summary"], "risk_level": risk_level, "reason": params.get("reason")},
            }, broadcast=self.broadcaster.publish)
        try:
            while not approval_event.wait(0.25):
                if self._stop.is_set():
                    return {"decision": "cancel"}
            decision = waiter["decision"]
            return {"decision": decision if decision in {"accept", "decline", "cancel"} else "decline"}
        finally:
            with self._lock:
                self._approval_waiters.pop(item["id"], None)
                registration = self._registry.get(run["id"])
                if registration:
                    registration.approval_waiters.discard(item["id"])

    def _record_native_approval_delivery(self, run: dict[str, Any], step: dict[str, Any], native_id: str,
                                         decision: str, delivered: bool) -> None:
        with self._lock:
            request_id = self._approval_native_ids.pop(native_id, None)
        if not request_id:
            return
        with connect_workbench_db(self.db_path) as conn:
            record_approval_delivery(conn, request_id, delivered=delivered)
            row = conn.execute("SELECT state FROM runs WHERE id=?", (run["id"],)).fetchone()
            if not row or row["state"] != "waiting_approval":
                return
            if delivered:
                persist_status_change(
                    conn, run_id=run["id"], step_id=step["id"], state="running", source_tool="codex",
                    reason="approval_delivered", step_state="running",
                )
            else:
                persist_status_change(
                    conn, run_id=run["id"], step_id=step["id"], state="failed", source_tool="codex",
                    reason="approval_delivery_failed", step_state="failed",
                    run_updates={"finished_at": _now(), "failure_code": "approval_delivery_failed", "failure_message": "native approval response could not be delivered"},
                )

    def _persist_live_event(self, run: dict[str, Any], step: dict[str, Any], item: dict[str, Any]) -> None:
        """Make each native record visible before the CLI process exits."""
        event = dict(item)
        event.update(run_id=run["id"], step_id=step["id"], event_id=str(uuid.uuid4()), profile_id=run["profile_id"])
        payload = event.get("payload") or {}
        native_id = payload.get("thread_id") or payload.get("threadId") or payload.get("session_id") or payload.get("sessionId")
        updates: dict[str, Any] = {}
        if native_id:
            self._validate_native_session_identity(run, str(native_id))
            self._convert_to_native_lease(run, str(native_id))
            registration = self._registry.get(run["id"])
            if registration:
                registration.session_id = str(native_id)
            updates["native_session_id"] = native_id
            if run["tool"] == "codex":
                updates["native_thread_id"] = native_id
        if run.get("_lease_key") and run.get("lease_generation"):
            self._heartbeat_lease(run, int(run["lease_generation"]))
        with connect_workbench_db(self.db_path) as conn:
            persist_event(conn, event, broadcast=self.broadcaster.publish, run_updates=updates or None)

    @staticmethod
    def _validate_native_session_identity(run: dict[str, Any], native_session_id: str) -> None:
        """Reject an adapter that violates explicit Resume/Fork semantics."""
        source = run.get("source_native_session_id")
        if run.get("mode") == "resume" and source and native_session_id != source:
            raise BusinessError("resume returned a different native session id")
        if run.get("mode") == "fork" and source and native_session_id == source:
            raise BusinessError("fork did not return a new native session id")

    def _convert_to_native_lease(self, run: dict[str, Any], native_session_id: str) -> None:
        """Acquire the actual session lease before persisting its first event.

        New runs have no source identity, while Fork starts under a source lease
        and must switch to the newly returned thread.  Acquire-before-release
        keeps either identity protected throughout that hand-off.
        """
        target_key = _physical_session_key(run["tool"], run["profile_id"], native_session_id)
        current_key = run.get("_lease_key")
        if current_key == target_key:
            return
        now = _now()
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        with connect_workbench_db(self.db_path) as conn:
            generation = acquire_writer_lease(
                conn, physical_session_key=target_key, run_id=run["id"], owner_id=self.instance_id,
                now=now, expires_at=expiry,
            )
            conn.execute("UPDATE runs SET lease_generation=?, updated_at=? WHERE id=?", (generation, now, run["id"]))
            conn.commit()
            if current_key and run.get("lease_generation"):
                release_writer_lease(
                    conn, physical_session_key=str(current_key), run_id=run["id"],
                    lease_generation=int(run["lease_generation"]),
                )
        run["_lease_key"] = target_key
        run["lease_generation"] = generation
        with self._lock:
            registration = self._registry.setdefault(run["id"], RuntimeRegistration())
            registration.lease_key, registration.lease_generation = target_key, generation

    def _acquire_source_lease(self, run: dict[str, Any]) -> tuple[str, int]:
        key = _physical_session_key(run["tool"], run["profile_id"], run["source_native_session_id"])
        now = _now()
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        with connect_workbench_db(self.db_path) as conn:
            generation = acquire_writer_lease(
                conn, physical_session_key=key, run_id=run["id"], owner_id=self.instance_id,
                now=now, expires_at=expiry,
            )
            conn.execute("UPDATE runs SET lease_generation=?, updated_at=? WHERE id=?", (generation, now, run["id"]))
            conn.commit()
        with self._lock:
            registration = self._registry.setdefault(run["id"], RuntimeRegistration())
            registration.lease_key, registration.lease_generation = key, generation
        return key, generation

    def _heartbeat_lease(self, run: dict[str, Any], generation: int) -> None:
        key = str(run.get("_lease_key") or _physical_session_key(run["tool"], run["profile_id"], run["source_native_session_id"]))
        now = _now()
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        with connect_workbench_db(self.db_path) as conn:
            heartbeat_writer_lease(conn, physical_session_key=key, run_id=run["id"], lease_generation=generation, heartbeat_at=now, expires_at=expiry)

    def _lease_is_current(self, run_id: str, key: str, generation: int) -> bool:
        """Verify the exact lease owner/generation before control-plane actions."""
        with connect_workbench_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT run_id, lease_generation, expires_at FROM session_writer_leases WHERE physical_session_key=?",
                (key,),
            ).fetchone()
        return bool(row and row["run_id"] == run_id and int(row["lease_generation"]) == int(generation) and row["expires_at"] >= _now())

    def _release_lease(self, run_id: str, lease: tuple[str, int]) -> None:
        with connect_workbench_db(self.db_path) as conn:
            released = release_writer_lease(conn, physical_session_key=lease[0], run_id=run_id, lease_generation=lease[1])
            if not released:
                raise SessionBusyError("session_busy")

    def _persist_result(self, run_id: str, step_id: str, run: dict[str, Any], result: Any, *, events_already_persisted: bool = False) -> None:
        with connect_workbench_db(self.db_path) as conn:
            current = conn.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
            if current is None:
                return
            if not events_already_persisted:
                for item in result.events:
                    self._persist_live_event(run, {"id": step_id}, item)
            fresh = conn.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
            if fresh is None or fresh["state"] in {"failed", "cancelled", "interrupted"}:
                return
            if fresh["state"] == "cancel_requested":
                timed_out = conn.execute("SELECT failure_code FROM runs WHERE id=?", (run_id,)).fetchone()
                persist_status_change(
                    conn, run_id=run_id, step_id=step_id, state="cancelling", source_tool=run["tool"],
                    reason="process_finished_after_cancel", step_state="cancelling",
                )
                confirmed = self._termination_confirmed(run_id)
                terminal = "interrupted" if not confirmed else "failed" if timed_out and timed_out["failure_code"] == "timeout" else "cancelled"
                persist_status_change(
                    conn, run_id=run_id, step_id=step_id, state=terminal, source_tool=run["tool"],
                    reason="timeout" if terminal == "failed" else "cancelled" if terminal == "cancelled" else "termination_unconfirmed", step_state=terminal,
                    run_updates={"finished_at": _now(), "failure_code": "termination_unconfirmed" if terminal == "interrupted" else None},
                )
                return
            terminal = "succeeded" if result.state == "completed" else "failed"
            persist_status_change(
                conn, run_id=run_id, step_id=step_id, state=terminal, source_tool=run["tool"],
                reason="process_completed" if terminal == "succeeded" else "process_failed",
                step_state=terminal,
                run_updates={
                    "finished_at": _now(), "execution_path": result.execution_path,
                    "failure_code": "native_process_failed" if terminal == "failed" else None,
                    # stderr is independently persisted as diagnostic events.
                    # It is not a failure message when the native turn succeeds.
                    "failure_message": result.stderr or None if terminal == "failed" else None,
                },
            )

    def _fail(self, run_id: str, step_id: str | None, tool: str | None, code: str, message: str) -> None:
        if not run_id or not step_id or not tool:
            return
        with connect_workbench_db(self.db_path) as conn:
            row = conn.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None or row["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                return
            state = "interrupted" if row["state"] == "cancel_requested" or code in {"session_busy", "lease_lost"} else "failed"
            # cancel_requested can legally advance only through cancelling.
            if state == "interrupted" and row["state"] == "cancel_requested":
                persist_status_change(conn, run_id=run_id, step_id=step_id, state="cancelling", source_tool=tool, reason="worker_exception")
                state = "interrupted"
            persist_status_change(
                conn, run_id=run_id, step_id=step_id, state=state, source_tool=tool,
                reason=code, step_state=state,
                run_updates={"finished_at": _now(), "failure_code": code, "failure_message": message},
            )

    def _step_id(self, run_id: str) -> str | None:
        with connect_workbench_db(self.db_path) as conn:
            row = conn.execute("SELECT id FROM run_steps WHERE run_id=? ORDER BY ordinal LIMIT 1", (run_id,)).fetchone()
            return row["id"] if row else None

    def _tool(self, run_id: str) -> str | None:
        with connect_workbench_db(self.db_path) as conn:
            row = conn.execute("SELECT tool FROM runs WHERE id=?", (run_id,)).fetchone()
            return row["tool"] if row else None


def _claude_options(policy: dict[str, Any], budget: dict[str, Any], model: str | None) -> dict[str, Any]:
    return {
        "max_budget": budget.get("max_budget_usd"),
        "model": model,
        "permission_mode": policy.get("permission_mode"),
        "allowed_tools": tuple(policy.get("allowed_tools") or ()),
        "disallowed_tools": tuple(policy.get("disallowed_tools") or ()),
    }


def _profile_environment(run: dict[str, Any]) -> dict[str, str]:
    """Build a minimal child environment without persisting credential values."""
    inherited = {
        name: value for name, value in os.environ.items()
        if name.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE",
            "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH",
        }
    }
    if run["tool"] == "codex":
        inherited["CODEX_HOME"] = run["config_root"]
    else:
        inherited["CLAUDE_CONFIG_DIR"] = run["config_root"]
    return inherited
