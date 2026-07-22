from __future__ import annotations

from dataclasses import dataclass

from .store import ObservabilityError

ARCHIVE_SCHEMA_VERSION = 1
ARCHIVE_SCHEMA_NAME = "pr198.immutable-observability-archive.v1"
PR198_EXPORT_TOOL_VERSION = "observability-export.v3"


class ArchiveError(ObservabilityError):
    """Immutable export ownership or archive truth was violated."""


@dataclass(frozen=True, slots=True)
class ExportClaim:
    claim_id: str
    exporter_id: str
    fencing_token: int
    database_epoch: str
    claimed_at: float
    lease_expires_at: float
    outbox_ids: tuple[int, ...]
    event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RemoteArchiveAck:
    archive_name: str
    object_key: str
    object_version: str
    object_digest: str
    metadata: dict[str, object] | None = None
