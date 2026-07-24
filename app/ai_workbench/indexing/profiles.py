from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path

from app.ai_workbench.models import ToolKind


@dataclass(frozen=True)
class DiscoveredProfile:
    id: str
    tool: ToolKind
    display_name: str
    config_root: Path
    session_root: Path
    discovery_source: str
    valid: bool
    reason: str | None = None


def discover_profiles(
    manual_roots: list[tuple[ToolKind, Path, str | None]] | None = None,
    cockpit_whitelist: Path | None = None,
) -> list[DiscoveredProfile]:
    candidates: list[DiscoveredProfile] = []
    home = Path.home()

    codex_roots = _path_values("CODEX_HOME") or [home / ".codex"]
    claude_roots = _path_values("CLAUDE_CONFIG_DIR") or [home / ".claude"]
    manual_roots = manual_roots or []
    whitelist_roots = load_cockpit_whitelist(cockpit_whitelist) if cockpit_whitelist else []

    for root in _dedupe_paths(codex_roots):
        candidates.append(build_profile(ToolKind.CODEX, root, "env" if os.environ.get("CODEX_HOME") else "default"))

    for root in _dedupe_paths(claude_roots):
        candidates.append(build_profile(ToolKind.CLAUDE, root, "env" if os.environ.get("CLAUDE_CONFIG_DIR") else "default"))

    for tool, root, display_name in manual_roots:
        candidates.append(build_profile(tool, root, "manual", display_name=display_name))

    for tool, root, display_name in whitelist_roots:
        candidates.append(build_profile(tool, root, "cockpit_whitelist", display_name=display_name))

    return _dedupe_profiles(candidates)


def build_profile(tool: ToolKind, root: Path, discovery_source: str, display_name: str | None = None) -> DiscoveredProfile:
    session_root = root / ("sessions" if tool is ToolKind.CODEX else "projects")
    return DiscoveredProfile(
        id=_profile_id(tool, root),
        tool=tool,
        display_name=display_name or f"{tool.value.title()} - {root.name}",
        config_root=root,
        session_root=session_root,
        discovery_source=discovery_source,
        valid=session_root.exists(),
        reason=None if session_root.exists() else f"{session_root.name} directory not found",
    )


def load_cockpit_whitelist(path: Path) -> list[tuple[ToolKind, Path, str | None]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = payload.get("profiles", []) if isinstance(payload, dict) else []
    result: list[tuple[ToolKind, Path, str | None]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tool = entry.get("tool")
        root = entry.get("config_root")
        if tool not in {ToolKind.CODEX.value, ToolKind.CLAUDE.value} or not isinstance(root, str):
            continue
        result.append((ToolKind(tool), Path(root).expanduser(), entry.get("display_name")))
    return result


def _path_values(name: str) -> list[Path]:
    raw = os.environ.get(name)
    if not raw:
        return []
    return [Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip()]


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        resolved = str(path.expanduser())
        key = resolved.lower() if os.name == "nt" else resolved
        if key in seen:
            continue
        seen.add(key)
        result.append(Path(resolved))
    return result


def _dedupe_profiles(profiles: list[DiscoveredProfile]) -> list[DiscoveredProfile]:
    seen: set[str] = set()
    result: list[DiscoveredProfile] = []
    for profile in profiles:
        if profile.id in seen:
            continue
        seen.add(profile.id)
        result.append(profile)
    return result


def _profile_id(tool: ToolKind, root: Path) -> str:
    normalized = str(root.expanduser()).replace("\\", "/").lower()
    import hashlib

    return f"{tool.value}:{hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:16]}"
