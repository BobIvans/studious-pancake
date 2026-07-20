"""Durable JSONL lifecycle journal for the paper/shadow runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PaperShadowEvent:
    """One durable lifecycle event.

    Events are append-only and intentionally contain no private key material,
    signed transaction bytes or raw API secrets.  The runner records message
    hashes and stage outputs only after upstream stages provide them.
    """

    run_id: str
    sequence: int
    event_type: str
    status: str
    reason_code: str
    stage: str | None = None
    opportunity_id: str | None = None
    message_hash: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: str = "pr038.paper-shadow-event.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))
        if self.sequence <= 0:
            raise ValueError("event sequence must be positive")
        if self.details.get("executed") is True:
            raise ValueError("paper/shadow journal cannot record executed trades")
        if self.details.get("signature") or self.details.get("signed_transaction"):
            raise ValueError("paper/shadow journal cannot contain submission material")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "created_at": self.created_at,
            "event_type": self.event_type,
            "stage": self.stage,
            "status": self.status,
            "reason_code": self.reason_code,
            "opportunity_id": self.opportunity_id,
            "message_hash": self.message_hash,
            "details": dict(self.details),
        }


class JsonlPaperShadowJournal:
    """Append-only JSONL journal with restart-safe sequence discovery."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def next_sequence(self) -> int:
        max_seen = 0
        if not self.path.exists():
            return 1
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            sequence = payload.get("sequence")
            if isinstance(sequence, int):
                max_seen = max(max_seen, sequence)
        return max_seen + 1

    def append(self, event: PaperShadowEvent) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True))
            handle.write("\n")
            handle.flush()

    def read_events(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        events: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    events.append(payload)
        return tuple(events)
