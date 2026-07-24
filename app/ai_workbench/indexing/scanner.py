from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ai_workbench.events.normalizer import normalize_jsonl
from app.ai_workbench.indexing.profiles import DiscoveredProfile, discover_profiles
from app.ai_workbench.models import NormalizedEvent, NormalizedEventType, ToolKind
from app.ai_workbench.storage import FTS_NOTICE_VERSION

PARSER_VERSION = 1


@dataclass(frozen=True)
class ScanSummary:
    profiles_seen: int
    profiles_indexed: int
    files_seen: int
    sessions_indexed: int
    events_indexed: int
    errors: list[str]
    run_id: str | None = None


class FtsConsentRequiredError(RuntimeError):
    """Raised when an FTS write is requested without current explicit consent."""


class FtsIndexingDisabledError(RuntimeError):
    """Raised when a consented user has disabled future FTS writes."""


def scan_sessions(conn: sqlite3.Connection, *, max_files_per_profile: int = 5000, changed_only: bool = False) -> ScanSummary:
    run_id = uuid.uuid4().hex
    started_at = int(time.time())
    conn.execute(
        "INSERT INTO scan_runs(id, started_at, status) VALUES(?, ?, 'running')",
        (run_id, started_at),
    )
    profiles = discover_profiles(manual_roots=_manual_roots(conn), cockpit_whitelist=_cockpit_whitelist_path())
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
            if changed_only and not _needs_reindex(conn, transcript):
                continue
            try:
                event_count = _index_transcript(conn, profile, transcript)
                events_indexed += event_count
                sessions_indexed += 1
            except OSError as exc:
                errors.append(f"{transcript}: {exc}")
            except sqlite3.Error as exc:
                errors.append(f"{transcript}: {exc}")
    _mark_missing_sources(conn)
    summary = ScanSummary(
        profiles_seen=len(profiles),
        profiles_indexed=profiles_indexed,
        files_seen=files_seen,
        sessions_indexed=sessions_indexed,
        events_indexed=events_indexed,
        errors=errors[:20],
        run_id=run_id,
    )
    conn.execute(
        """
        UPDATE scan_runs SET completed_at = ?, status = ?, profiles_seen = ?, profiles_indexed = ?,
            files_seen = ?, sessions_indexed = ?, events_indexed = ?, errors_json = ?
        WHERE id = ?
        """,
        (
            int(time.time()),
            "completed" if not errors else "completed_with_errors",
            summary.profiles_seen,
            summary.profiles_indexed,
            summary.files_seen,
            summary.sessions_indexed,
            summary.events_indexed,
            json.dumps(summary.errors, ensure_ascii=False),
            run_id,
        ),
    )
    conn.commit()
    return summary


def reconcile_sessions(conn: sqlite3.Connection, *, max_files_per_profile: int = 5000) -> ScanSummary:
    return scan_sessions(conn, max_files_per_profile=max_files_per_profile, changed_only=True)


def add_manual_profile(conn: sqlite3.Connection, *, tool: str, config_root: Path, display_name: str | None = None) -> dict[str, Any]:
    if tool not in {ToolKind.CODEX.value, ToolKind.CLAUDE.value}:
        raise ValueError("unsupported tool")
    normalized = str(config_root.expanduser())
    profile_id = f"manual:{tool}:{hashlib.sha1(normalized.lower().encode('utf-8')).hexdigest()[:16]}"
    conn.execute(
        """
        INSERT INTO manual_profile_roots(id, tool, config_root, display_name, enabled, created_at)
        VALUES(?, ?, ?, ?, 1, ?)
        ON CONFLICT(tool, config_root) DO UPDATE SET display_name=excluded.display_name, enabled=1
        """,
        (profile_id, tool, normalized, display_name, int(time.time())),
    )
    conn.commit()
    return {"id": profile_id, "tool": tool, "config_root": normalized, "display_name": display_name}


def list_manual_profiles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute("SELECT * FROM manual_profile_roots ORDER BY created_at DESC").fetchall()]


def latest_scan_runs(conn: sqlite3.Connection, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def rebuild_fts(conn: sqlite3.Connection) -> dict[str, int]:
    """Rebuild the local FTS index only when persisted consent currently permits writes."""
    settings = _fts_settings_row(conn)
    if not _has_current_fts_consent(settings):
        raise FtsConsentRequiredError("Current FTS notice has not been accepted")
    if not settings["indexing_enabled"]:
        raise FtsIndexingDisabledError("Future FTS indexing is disabled")
    conn.execute("DELETE FROM events_fts")
    rows = conn.execute(
        "SELECT id, session_copy_id, text_content FROM events WHERE text_content IS NOT NULL AND text_content != ''"
    ).fetchall()
    inserted = 0
    for row in rows:
        text = _redact_for_index(row["text_content"])
        if not text:
            continue
        conn.execute(
            "INSERT INTO events_fts(session_copy_id, event_id, text_content) VALUES(?, ?, ?)",
            (row["session_copy_id"], row["id"], text),
        )
        inserted += 1
    conn.commit()
    return {"indexed_events": inserted}


def clear_fts(conn: sqlite3.Connection) -> dict[str, int]:
    """Delete indexed text while leaving consent and future-indexing settings unchanged."""
    before = conn.execute("SELECT count(*) AS count FROM events_fts").fetchone()["count"]
    conn.execute("DELETE FROM events_fts")
    conn.commit()
    return {"cleared_events": before}


def fts_status(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return persisted FTS consent/settings together with the current index row count."""
    settings = _fts_settings_row(conn)
    indexed_events = conn.execute("SELECT count(*) AS count FROM events_fts").fetchone()["count"]
    return {
        "consent_state": settings["consent_state"],
        "indexing_enabled": bool(settings["indexing_enabled"]),
        "recommended": settings["consent_state"] == "recommended_pending"
        or (
            settings["consent_state"] == "user_enabled"
            and settings["notice_version"] != FTS_NOTICE_VERSION
        ),
        "notice_version": settings["notice_version"],
        "indexed_events": indexed_events,
    }


def record_fts_consent(
    conn: sqlite3.Connection,
    *,
    decision: str,
    notice_version: int,
) -> dict[str, Any]:
    """Persist an explicit accept/decline decision for the current FTS notice."""
    if notice_version != FTS_NOTICE_VERSION:
        raise ValueError("notice_version must match the current FTS notice")
    if decision not in {"accept", "decline"}:
        raise ValueError("decision must be accept or decline")
    now = int(time.time())
    conn.execute(
        """
        UPDATE fts_settings
        SET consent_state = ?, indexing_enabled = ?, notice_version = ?,
            decision_at = ?, updated_at = ?
        WHERE id = 1
        """,
        (
            "user_enabled" if decision == "accept" else "user_declined",
            1 if decision == "accept" else 0,
            notice_version,
            now,
            now,
        ),
    )
    conn.commit()
    return fts_status(conn)


def set_fts_indexing_enabled(conn: sqlite3.Connection, *, enabled: bool) -> dict[str, Any]:
    """Enable or disable future FTS writes without changing the recorded consent state."""
    settings = _fts_settings_row(conn)
    if enabled and not _has_current_fts_consent(settings):
        raise FtsConsentRequiredError("Current FTS notice has not been accepted")
    conn.execute(
        "UPDATE fts_settings SET indexing_enabled = ?, updated_at = ? WHERE id = 1",
        (1 if enabled else 0, int(time.time())),
    )
    conn.commit()
    return fts_status(conn)


def list_sessions(
    conn: sqlite3.Connection,
    *,
    tool: str | None = None,
    search: str | None = None,
    profile_id: str | None = None,
    project_id: str | None = None,
    divergence: str | None = None,
    archived: bool | None = None,
    limit: int = 100,
    cursor: int = 0,
) -> dict[str, Any]:
    where = ["1=1"]
    params: list[Any] = []
    if tool:
        where.append("tool = ?")
        params.append(tool)
    if profile_id:
        where.append("profile_id = ?")
        params.append(profile_id)
    if project_id:
        where.append("project_id = ?")
        params.append(project_id)
    if divergence:
        where.append("divergence_status = ?")
        params.append(divergence)
    if archived is not None:
        where.append("kind = ?" if archived else "kind != ?")
        params.append("archived")
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
    diff_summary = _family_diff_summary(conn, copy["family_id"])
    return {
        "session": dict(copy),
        "profile": dict(profile) if profile else None,
        "copies": [dict(row) for row in family_copies],
        "diffSummary": diff_summary,
        "events": page,
        "nextEventCursor": event_cursor + event_limit if len(events) > event_limit else None,
    }


def profile_diagnostics(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    profiles = discover_profiles(manual_roots=_manual_roots(conn), cockpit_whitelist=_cockpit_whitelist_path())
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
    raw = f"{tool.value}|{native_session_id}|{_family_fingerprint(events)}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()


def _initial_fingerprint(events: list[NormalizedEvent]) -> str:
    values = [f"{event.event_type.value}:{event.role}:{event.text or ''}" for event in events[:3]]
    return hashlib.sha1("\n".join(values).encode("utf-8", errors="replace")).hexdigest()


def _family_fingerprint(events: list[NormalizedEvent]) -> str:
    for event in events:
        if event.event_type is NormalizedEventType.USER_MESSAGE:
            return hashlib.sha1(f"{event.role}:{event.text or ''}".encode("utf-8", errors="replace")).hexdigest()
    return _initial_fingerprint(events)


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
        conn.execute("UPDATE session_copies SET divergence_status = ? WHERE family_id = ?", (status, family_id))
        return
    signatures = {row["id"]: _event_signatures(conn, row["id"]) for row in rows}
    unique = {tuple(value) for value in signatures.values()}
    if len(unique) == 1:
        conn.execute("UPDATE session_copies SET divergence_status = 'in_sync' WHERE family_id = ?", (family_id,))
        return
    longest_id = max(signatures, key=lambda copy_id: len(signatures[copy_id]))
    longest = signatures[longest_id]
    all_prefix = all(_is_prefix(value, longest) for value in signatures.values())
    if all_prefix:
        for row in rows:
            conn.execute(
                "UPDATE session_copies SET divergence_status = ? WHERE id = ?",
                ("ahead" if row["id"] == longest_id else "in_sync", row["id"]),
            )
    else:
        conn.execute("UPDATE session_copies SET divergence_status = 'diverged' WHERE family_id = ?", (family_id,))


def _manual_roots(conn: sqlite3.Connection) -> list[tuple[ToolKind, Path, str | None]]:
    rows = conn.execute("SELECT tool, config_root, display_name FROM manual_profile_roots WHERE enabled = 1").fetchall()
    return [(ToolKind(row["tool"]), Path(row["config_root"]), row["display_name"]) for row in rows]


def _cockpit_whitelist_path() -> Path:
    return Path("data") / "ai_workbench" / "cockpit_profile_whitelist.json"


def _needs_reindex(conn: sqlite3.Connection, transcript: Path) -> bool:
    try:
        stat = transcript.stat()
    except OSError:
        return False
    row = conn.execute("SELECT file_size, mtime_ns, parser_version FROM source_checkpoints WHERE path = ?", (str(transcript),)).fetchone()
    if row is None:
        return True
    return row["file_size"] != stat.st_size or row["mtime_ns"] != stat.st_mtime_ns or row["parser_version"] != PARSER_VERSION


def _mark_missing_sources(conn: sqlite3.Connection) -> None:
    now = int(time.time())
    for row in conn.execute("SELECT path FROM source_checkpoints WHERE status = 'active'").fetchall():
        if not Path(row["path"]).exists():
            conn.execute(
                "UPDATE source_checkpoints SET status = 'missing', missing_since = ? WHERE path = ?",
                (now, row["path"]),
            )


def _event_signatures(conn: sqlite3.Connection, copy_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT event_type, role, COALESCE(text_content, structured_json, raw_json, '') AS body FROM events WHERE session_copy_id = ? ORDER BY sequence_no",
        (copy_id,),
    ).fetchall()
    return [hashlib.sha1(f"{row['event_type']}|{row['role']}|{row['body']}".encode("utf-8", errors="replace")).hexdigest() for row in rows]


def _is_prefix(candidate: list[str], full: list[str]) -> bool:
    return len(candidate) <= len(full) and candidate == full[: len(candidate)]


def _family_diff_summary(conn: sqlite3.Connection, family_id: str) -> dict[str, Any]:
    copies = conn.execute("SELECT id, event_count, divergence_status FROM session_copies WHERE family_id = ?", (family_id,)).fetchall()
    if len(copies) <= 1:
        return {"status": "single_copy", "copies": len(copies)}
    signatures = {row["id"]: _event_signatures(conn, row["id"]) for row in copies}
    common = 0
    if signatures:
        shortest = min(len(value) for value in signatures.values())
        for idx in range(shortest):
            values = {sig[idx] for sig in signatures.values()}
            if len(values) != 1:
                break
            common += 1
    return {
        "status": "in_sync" if len({tuple(v) for v in signatures.values()}) == 1 else "diverged",
        "copies": len(copies),
        "common_prefix_events": common,
        "copy_event_counts": {row["id"]: row["event_count"] for row in copies},
    }


def _redact_for_index(text: str) -> str:
    """Replace common secret shapes before text is copied into the local FTS table."""
    import re

    patterns = [
        r"sk-[A-Za-z0-9_\-]{8,}",
        "github" + r"_pat_[A-Za-z0-9_]+",
        r"ghp_[A-Za-z0-9]+",
        r"(?i)(api[_-]?key|password|token|secret)\s*[:=]\s*\S+",
    ]
    redacted = text
    for pattern in patterns:
        redacted = re.sub(pattern, "<redacted>", redacted)
    return redacted


def _fts_settings_row(conn: sqlite3.Connection) -> sqlite3.Row:
    """Return the required singleton FTS settings row from an initialized schema."""
    row = conn.execute("SELECT * FROM fts_settings WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError("fts_settings singleton is missing")
    return row


def _has_current_fts_consent(settings: sqlite3.Row) -> bool:
    """Return whether the stored state permits FTS writes under the current notice."""
    if settings["consent_state"] == "legacy_preserved":
        return bool(settings["indexing_enabled"])
    return (
        settings["consent_state"] == "user_enabled"
        and settings["notice_version"] == FTS_NOTICE_VERSION
    )


def _loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
