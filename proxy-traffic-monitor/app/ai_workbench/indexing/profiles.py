from __future__ import annotations

import os
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


def discover_profiles(extra_roots: list[Path] | None = None) -> list[DiscoveredProfile]:
    candidates: list[DiscoveredProfile] = []
    home = Path.home()

    codex_roots = _path_values("CODEX_HOME") or [home / ".codex"]
    claude_roots = _path_values("CLAUDE_CONFIG_DIR") or [home / ".claude"]
    if extra_roots:
        codex_roots.extend(extra_roots)
        claude_roots.extend(extra_roots)

    for root in _dedupe_paths(codex_roots):
        session_root = root / "sessions"
        candidates.append(
            DiscoveredProfile(
                id=_profile_id(ToolKind.CODEX, root),
                tool=ToolKind.CODEX,
                display_name=f"Codex - {root.name}",
                config_root=root,
                session_root=session_root,
                discovery_source="env" if os.environ.get("CODEX_HOME") else "default",
                valid=session_root.exists(),
                reason=None if session_root.exists() else "sessions directory not found",
            )
        )

    for root in _dedupe_paths(claude_roots):
        session_root = root / "projects"
        candidates.append(
            DiscoveredProfile(
                id=_profile_id(ToolKind.CLAUDE, root),
                tool=ToolKind.CLAUDE,
                display_name=f"Claude - {root.name}",
                config_root=root,
                session_root=session_root,
                discovery_source="env" if os.environ.get("CLAUDE_CONFIG_DIR") else "default",
                valid=session_root.exists(),
                reason=None if session_root.exists() else "projects directory not found",
            )
        )

    return candidates


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


def _profile_id(tool: ToolKind, root: Path) -> str:
    normalized = str(root.expanduser()).replace("\\", "/").lower()
    import hashlib

    return f"{tool.value}:{hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:16]}"

