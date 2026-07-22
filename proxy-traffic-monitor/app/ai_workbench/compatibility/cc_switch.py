from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CcSwitchSchemaProbe:
    status: str
    path: Path
    user_version: int | None = None
    tables: dict[str, list[str]] = field(default_factory=dict)
    message: str | None = None

    @property
    def supports_proxy_request_logs(self) -> bool:
        return "proxy_request_logs" in self.tables


def probe_cc_switch_schema(path: Path) -> CcSwitchSchemaProbe:
    if not path.exists():
        return CcSwitchSchemaProbe(status="missing", path=path, message="database not found")

    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    except sqlite3.Error as exc:
        return CcSwitchSchemaProbe(status="error", path=path, message=str(exc))

    try:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        tables: dict[str, list[str]] = {}
        for (table_name,) in table_rows:
            escaped = table_name.replace('"', '""')
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{escaped}")').fetchall()]
            tables[table_name] = columns
    except sqlite3.Error as exc:
        return CcSwitchSchemaProbe(status="error", path=path, message=str(exc))
    finally:
        connection.close()

    return CcSwitchSchemaProbe(status="available", path=path, user_version=user_version, tables=tables)

