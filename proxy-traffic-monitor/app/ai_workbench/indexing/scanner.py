from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ai_workbench.events.normalizer import normalize_jsonl
from app.ai_workbench.indexing.profiles import DiscoveredProfile, discover_profiles
from app.ai_workbench.models import NormalizedEvent, NormalizedEventType, ToolKind

PARSER_VERSION = 1


@dataclass(frozen=True)
class ScanSummary:
    profiles_seen: int
    profiles_indexed: int
    files_seen: int
    sessions_indexed: int
    events_indexed: int
    errors: list[str]


def scan_sessions(conn: sqlite3.Connection, *, max_files_per_profile: int = 5000) -> ScanSummary:
    profiles = discover_profiles()
    files_seen = 0
    sessions_indexed = 0
    events_indexed = 0
    errors: list[str] = []
    profiles_indexed = 0

    for profile in profiles:
        _upsert_profile(conn, profile)
        if not profile.valid:
            continue
        profiles_indexed += 1
        for transcript in _iter_transcripts(profile, max_files_per_profile):
            files_seen += 1
            try:
                event_count = _index_transcript(conn, profile, transcript)
                events_indexed += event_count
                sessions_indexed += 1
            except OSError as exc:
                errors.append(f"{transcript}: {exc}")
            except sqlite3.Error as exc:
                errors.append(f"{transcript}: {exc}")
    conn.commit()
    return ScanSummary(
        profiles_seen=len(profiles),
        profiles_indexed=profiles_indexed,
        files_seen=files_seen,
        sessions_indexed=sessions_indexed,
        events_indexed=events_indexed,
        errors=errors[:20],
    )


def list_sessions(conn: sqlite3.Connection, *, tool: str | None = None, search: str | None = None, limit: int = 100, cursor: int = 0) -> dict[str, Any]:
    where = ["1=1"]
    params: list[Any] = []
    if tool:
        where.append("tool = ?")
        params.append(tool)
    if search:
        where.append("(title LIKE ? OR transcript_path LIKE ? OR native_session_id LIKE ?)")
        needle = f"%{search}%"
        params.extend([needle, needle, needle])
    query = f"""
        SELECT id, family_id, tool, native_session_id, profile_id, project_id, transcript_path,
               title, model, kind, created_at, updated_at, divergence_status, event_count, index_status
        FROM session_copies
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(updated_at, created_at, 0) DESC, id ASC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(query, (*params, limit + 1, cursor)).fetchall()
    has_more = len(rows) > limit
    data = [dict(row) for row in rows[:limit]]
    return {"data": data, "nextCursor": cursor + limit if has_more else None}


def get_session_detail(conn: sqlite3.Connection, copy_id: str, *, event_limit: int = 300, event_cursor: int = 0) -> dict[str, Any] | None:
    copy = conn.execute("SELECT * FROM session_copies WHERE id = ?", (copy_id,)).fetchone()
    if copy is None:
        return None
    events = conn.execute(
        """
        SELECT id, sequence_no, event_type, role, text_content, structured_json, raw_json,
               source_offset, data_quality
        FROM events
        WHERE session_copy_id = ?
        ORDER BY sequence_no ASC
        LIMIT ? OFFSET ?
        """,
        (copy_id, event_limit + 1, event_cursor),
    ).fetchall()
    profile = conn.execute("SELECT * FROM tool_profiles WHERE id = ?", (copy["profile_id"],)).fetchone()
    family_copies = conn.execute(
        """
        SELECT id, tool, profile_id, transcript_path, updated_at, divergence_status, event_count
        FROM session_copies
        WHERE family_id = ?
        ORDER BY updated_at DESC
        """,
        (copy["family_id"],),
    ).fetchall()
    page = [dict(row) for row in events[:event_limit]]
    for event in page:
        event["structured_json"] = _loads(event["structured_json"])
        event["raw_json"] = _loads(event["raw_json"])
    return {
        "session": dict(copy),
        "profile": dict(profile) if profile else None,
        "copies": [dict(row) for row in family_copies],
        "events": page,
        "nextEventCursor": event_cursor + event_limit if len(events) > event_limit else None,
    }


def profile_diagnostics(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    profiles = discover_profiles()
    stored = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM tool_profiles").fetchall()}
    result = []
    for profile in profiles:
        result.append(
            {
                "id": profile.id,
                "tool": profile.tool.value,
                "display_name": profile.display_name,
                "config_root": str(profile.config_root),
                "session_root": str(profile.session_root),
                "discovery_source": profile.discovery_source,
                "valid": profile.valid,
                "reason": profile.reason,
                "indexed": profile.id in stored,
            }
        )
    return result


def _iter_transcripts(profile: DiscoveredProfile, max_files: int) -> list[Path]:
    if profile.tool is ToolKind.CODEX:
        roots = [profile.session_root, profile.config_root / "archived_sessions"]
    else:
        roots = [profile.session_root]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime_ns if p.exists() else 0, reverse=True))
    return files[:max_files]


def _index_transcript(conn: sqlite3.Connection, profile: DiscoveredProfile, transcript: Path) -> int:
    stat = transcript.stat()
    text = transcript.read_text(encoding="utf-8", errors="replace")
    complete_text, offset = _complete_text(text)
    lines = complete_text.splitlines(True)
    content_hash = hashlib.sha256(complete_text.encode("utf-8", errors="replace")).hexdigest()
    events = normalize_jsonl(lines, tool=profile.tool, source=str(transcript), cli_version=None)
    native_session_id = _native_session_id(profile.tool, transcript, events)
    copy_id = _copy_id(profile, native_session_id, transcript)
    family_id = _family_id(profile.tool, native_session_id, events)
    now = int(time.time())
    created_at = _guess_created_at(stat)
    updated_at = int(stat.st_mtime)
    title = _title_from_events(events) or transcript.stem
    project_id = _project_id_from_transcript(profile, transcript)
    project_path = _project_path(profile, transcript)

    conn.execute(
        "INSERT OR IGNORE INTO repositories(id, root_path, exists_on_disk) VALUES(?, ?, ?)",
        (project_id, project_path, 1 if project_path and Path(project_path).exists() else 0),
    )
    conn.execute(
        """
        INSERT INTO projects(id, cwd_raw, cwd_canonical, repository_id, exists_on_disk)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET cwd_raw=excluded.cwd_raw, cwd_canonical=excluded.cwd_canonical,
            repository_id=excluded.repository_id, exists_on_disk=excluded.exists_on_disk
        """,
        (project_id, project_path, project_path, project_id, 1 if project_path and Path(project_path).exists() else 0),
    )
    conn.execute(
        """
        INSERT INTO conversation_families(id, tool, native_session_id, initial_fingerprint, created_at, updated_at)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at
        """,
        (family_id, profile.tool.value, native_session_id, _initial_fingerprint(events), created_at, updated_at),
    )
    conn.execute(
        """
        INSERT INTO session_copies(
            id, family_id, tool, native_session_id, profile_id, project_id, transcript_path,
            transcript_kind, title, model, kind, created_at, updated_at, content_hash,
            head_event_hash, parse_version, index_status, divergence_status, event_count
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tool, profile_id, native_session_id, transcript_path) DO UPDATE SET
            title=excluded.title, updated_at=excluded.updated_at, content_hash=excluded.content_hash,
            head_event_hash=excluded.head_event_hash, parse_version=excluded.parse_version,
            index_status=excluded.index_status, event_count=excluded.event_count
        """,
        (
            copy_id,
            family_id,
            profile.tool.value,
            native_session_id,
            profile.id,
            project_id,
            str(transcript),
            "jsonl",
            title,
            _model_from_events(events),
            _kind_from_path(profile, transcript),
            created_at,
            updated_at,
            content_hash,
            _head_hash(events),
            PARSER_VERSION,
            "indexed",
            "unknown",
            len(events),
        ),
    )
    conn.execute("DELETE FROM events WHERE session_copy_id = ?", (copy_id,))
    for event in events:
        conn.execute(
            """
            INSERT INTO events(
                id, session_copy_id, sequence_no, event_type, role, text_content,
                structured_json, raw_json, source_offset, data_quality
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{copy_id}:{event.sequence_no}",
                copy_id,
                event.sequence_no,
                event.event_type.value,
                event.role,
                event.text,
                json.dumps(event.structured, ensure_ascii=False) if event.structured else None,
                json.dumps(event.raw, ensure_ascii=False) if event.raw else None,
                event.provenance.offset,
                event.quality.value,
            ),
        )
    conn.execute(
        """
        INSERT INTO source_checkpoints(path, profile_id, file_size, mtime_ns, parsed_offset,
            last_complete_line_offset, content_hash, parser_version, last_indexed_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET file_size=excluded.file_size, mtime_ns=excluded.mtime_ns,
            parsed_offset=excluded.parsed_offset, last_complete_line_offset=excluded.last_complete_line_offset,
            content_hash=excluded.content_hash, parser_version=excluded.parser_version,
            last_indexed_at=excluded.last_indexed_at
        """,
        (str(transcript), profile.id, stat.st_size, stat.st_mtime_ns, offset, offset, content_hash, PARSER_VERSION, now),
    )
    _update_divergence(conn, family_id)
    return len(events)


def _upsert_profile(conn: sqlite3.Connection, profile: DiscoveredProfile) -> None:
    conn.execute(
        """
        INSERT INTO tool_profiles(id, tool, display_name, config_root, session_root, discovery_source, capability_status, enabled)
        VALUES(?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, session_root=excluded.session_root,
            discovery_source=excluded.discovery_source, capability_status=excluded.capability_status
        """,
        (
            profile.id,
            profile.tool.value,
            profile.display_name,
            str(profile.config_root),
            str(profile.session_root),
            profile.discovery_source,
            "available" if profile.valid else "missing",
        ),
    )


def _complete_text(text: str) -> tuple[str, int]:
    if not text:
        return "", 0
    if text.endswith("\n"):
        return text, len(text.encode("utf-8", errors="replace"))
    last_newline = text.rfind("\n")
    if last_newline == -1:
        return "", 0
    complete = text[: last_newline + 1]
    return complete, len(complete.encode("utf-8", errors="replace"))


def _native_session_id(tool: ToolKind, transcript: Path, events: list[NormalizedEvent]) -> str:
    for event in events:
        raw = event.raw or {}
        for key in ("session_id", "sessionId", "id"):
            value = raw.get(key)
            if isinstance(value, str) and len(value) >= 8:
                return value
    return transcript.stem


def _copy_id(profile: DiscoveredProfile, native_session_id: str, transcript: Path) -> str:
    raw = f"{profile.tool.value}|{profile.id}|{native_session_id}|{transcript}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()


def _family_id(tool: ToolKind, native_session_id: str, events: list[NormalizedEvent]) -> str:
    raw = f"{tool.value}|{native_session_id}|{_initial_fingerprint(events)}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()


def _initial_fingerprint(events: list[NormalizedEvent]) -> str:
    values = [f"{event.event_type.value}:{event.role}:{event.text or ''}" for event in events[:3]]
    return hashlib.sha1("\n".join(values).encode("utf-8", errors="replace")).hexdigest()


def _head_hash(events: list[NormalizedEvent]) -> str:
    values = [f"{event.sequence_no}:{event.event_type.value}:{event.text or ''}" for event in events[-10:]]
    return hashlib.sha1("\n".join(values).encode("utf-8", errors="replace")).hexdigest()


def _title_from_events(events: list[NormalizedEvent]) -> str | None:
    for event in events:
        if event.event_type is NormalizedEventType.USER_MESSAGE and event.text:
            text = " ".join(event.text.split())
            return text[:80]
    for event in events:
        if event.text:
            return " ".join(event.text.split())[:80]
    return None


def _model_from_events(events: list[NormalizedEvent]) -> str | None:
    for event in events:
        raw = event.raw or {}
        model = raw.get("model") or raw.get("model_name")
        if isinstance(model, str):
            return model
    return None


def _project_id_from_transcript(profile: DiscoveredProfile, transcript: Path) -> str:
    path = _project_path(profile, transcript) or str(profile.config_root)
    return hashlib.sha1(path.lower().encode("utf-8", errors="replace")).hexdigest()


def _project_path(profile: DiscoveredProfile, transcript: Path) -> str | None:
    if profile.tool is ToolKind.CLAUDE:
        try:
            rel = transcript.relative_to(profile.session_root)
            encoded = rel.parts[0]
            if encoded.startswith("-"):
                return encoded.replace("-", os.sep).strip(os.sep)
        except ValueError:
            return None
    return None


def _kind_from_path(profile: DiscoveredProfile, transcript: Path) -> str:
    lower = str(transcript).lower()
    if "archived" in lower:
        return "archived"
    if "subagent" in lower:
        return "subagent"
    return "main"


def _guess_created_at(stat: os.stat_result) -> int:
    return int(min(stat.st_ctime, stat.st_mtime))


def _update_divergence(conn: sqlite3.Connection, family_id: str) -> None:
    rows = conn.execute("SELECT id, content_hash, event_count FROM session_copies WHERE family_id = ?", (family_id,)).fetchall()
    if len(rows) <= 1:
        status = "unknown"
    else:
        hashes = {row["content_hash"] for row in rows}
        status = "in_sync" if len(hashes) == 1 else "diverged"
    conn.execute("UPDATE session_copies SET divergence_status = ? WHERE family_id = ?", (status, family_id))


def _loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None

