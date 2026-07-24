from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class DataQuality(str, Enum):
    EXACT = "exact"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class ToolKind(str, Enum):
    CODEX = "codex"
    CLAUDE = "claude"


class CapabilityStatus(str, Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    ERROR = "error"
    TIMEOUT = "timeout"


class NormalizedEventType(str, Enum):
    USER_MESSAGE = "user.message"
    ASSISTANT_MESSAGE = "assistant.message"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    COMMAND_OUTPUT = "command.output"
    FILE_CHANGED = "file.changed"
    USAGE_SNAPSHOT = "usage.snapshot"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceProvenance:
    tool: ToolKind
    source: str
    raw_event_type: str | None = None
    cli_version: str | None = None
    offset: int | None = None


@dataclass(frozen=True)
class ToolCapabilities:
    tool: ToolKind
    status: CapabilityStatus
    executable: str | None = None
    version: str | None = None
    features: dict[str, bool] = field(default_factory=dict)
    message: str | None = None

    def supports(self, feature: str) -> bool:
        return bool(self.features.get(feature))


@dataclass(frozen=True)
class NormalizedEvent:
    event_type: NormalizedEventType
    sequence_no: int
    provenance: SourceProvenance
    role: Literal["user", "assistant", "tool", "system"] | None = None
    text: str | None = None
    structured: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | None = None
    quality: DataQuality = DataQuality.EXACT


@dataclass(frozen=True)
class ProbeCommand:
    argv: tuple[str, ...]
    timeout_seconds: float = 3.0
