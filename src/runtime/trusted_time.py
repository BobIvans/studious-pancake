"""Single injectable clock boundary for runtime policy decisions.

Monotonic values are process-local and intentionally absent from durable
serialization.  UTC, slot, and block height are evidence for restart-spanning
decisions; provider timestamps are never treated as trusted current time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
import time
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TrustedTimeSnapshot:
    monotonic_ns: int
    utc: datetime
    slot: int | None = None
    block_height: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.monotonic_ns, bool) or not isinstance(self.monotonic_ns, int) or self.monotonic_ns < 0:
            raise ValueError("monotonic_ns must be a non-negative integer")
        if self.utc.tzinfo is None or self.utc.utcoffset() is None:
            raise ValueError("utc must be timezone-aware")
        for name in ("slot", "block_height"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer")

    def durable_evidence(self) -> dict[str, object]:
        """Return restart-portable evidence, deliberately excluding monotonic time."""
        return {"utc": self.utc.astimezone(UTC).isoformat(), "slot": self.slot, "block_height": self.block_height}


class TrustedTime(Protocol):
    def snapshot(self) -> TrustedTimeSnapshot: ...


class SystemTrustedTime:
    def snapshot(self) -> TrustedTimeSnapshot:
        return TrustedTimeSnapshot(time.monotonic_ns(), datetime.now(UTC))


def duration_ns(value: int, *, name: str, minimum: int = 1, maximum: int = 86_400_000_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite integer nanosecond duration")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum} nanoseconds")
    return value
