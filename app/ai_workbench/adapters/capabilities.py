from __future__ import annotations

import shutil
import subprocess
import re

from app.ai_workbench.models import CapabilityStatus, ProbeCommand, ToolCapabilities, ToolKind


def _run_text(command: ProbeCommand) -> tuple[CapabilityStatus, str]:
    try:
        completed = subprocess.run(
            list(command.argv),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=command.timeout_seconds,
        )
    except FileNotFoundError:
        return CapabilityStatus.MISSING, ""
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return CapabilityStatus.TIMEOUT, output
    except OSError as exc:
        return CapabilityStatus.ERROR, str(exc)

    output = f"{completed.stdout}\n{completed.stderr}".strip()
    if completed.returncode != 0 and not output:
        return CapabilityStatus.ERROR, f"exit code {completed.returncode}"
    return CapabilityStatus.AVAILABLE, output


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _has_option(help_text: str, option: str) -> bool:
    """Match a CLI option as a token, never by an unrelated substring."""
    return bool(re.search(rf"(?<![A-Za-z0-9_-]){re.escape(option)}(?![A-Za-z0-9_-])", help_text))


def parse_claude_help_capabilities(help_text: str) -> dict[str, bool]:
    """Derive the supported Claude flags from this exact help snapshot.

    Unknown/new flags remain false until a later read-only probe observes them;
    no machine's result is treated as a permanent product guarantee.
    """
    return {
        "stream_json": _has_option(help_text, "stream-json"),
        "resume": _has_option(help_text, "--resume"),
        "fork": _has_option(help_text, "--fork-session"),
        "input_stream": _has_option(help_text, "--input-format") and _has_option(help_text, "stream-json"),
        "max_budget_usd": _has_option(help_text, "--max-budget-usd"),
        "permission_mode": _has_option(help_text, "--permission-mode"),
        "allowed_tools": _has_option(help_text, "--allowedTools"),
        "disallowed_tools": _has_option(help_text, "--disallowedTools"),
    }


def probe_codex(executable: str = "codex") -> ToolCapabilities:
    resolved = shutil.which(executable)
    if resolved is None:
        return ToolCapabilities(ToolKind.CODEX, CapabilityStatus.MISSING, message="codex executable not found")

    version_status, version_text = _run_text(ProbeCommand((resolved, "--version")))
    help_status, help_text = _run_text(ProbeCommand((resolved, "--help")))
    app_status, app_text = _run_text(ProbeCommand((resolved, "app-server", "--help")))

    status = version_status
    if status is CapabilityStatus.AVAILABLE and help_status is not CapabilityStatus.AVAILABLE:
        status = help_status

    combined = "\n".join([help_text, app_text]).lower()
    features = {
        "resume": "resume" in combined,
        "exec_json": "exec" in combined and "--json" in combined,
        "app_server": app_status is CapabilityStatus.AVAILABLE and "app-server" in combined,
    }
    return ToolCapabilities(
        tool=ToolKind.CODEX,
        status=status,
        executable=resolved,
        version=_first_line(version_text),
        features=features,
        message=None if status is CapabilityStatus.AVAILABLE else version_text,
    )


def probe_claude(executable: str = "claude") -> ToolCapabilities:
    resolved = shutil.which(executable)
    if resolved is None:
        return ToolCapabilities(ToolKind.CLAUDE, CapabilityStatus.MISSING, message="claude executable not found")

    version_status, version_text = _run_text(ProbeCommand((resolved, "--version")))
    help_status, help_text = _run_text(ProbeCommand((resolved, "--help")))

    status = version_status
    if status is CapabilityStatus.AVAILABLE and help_status is not CapabilityStatus.AVAILABLE:
        status = help_status

    features = parse_claude_help_capabilities(help_text)
    return ToolCapabilities(
        tool=ToolKind.CLAUDE,
        status=status,
        executable=resolved,
        version=_first_line(version_text),
        features=features,
        message=None if status is CapabilityStatus.AVAILABLE else version_text,
    )
