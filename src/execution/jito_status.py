from __future__ import annotations
from dataclasses import dataclass
from .models import ExecutionErrorCode

MAX_BUNDLE_STATUS_IDS = 5
INFLIGHT_BUNDLE_STATUS_WINDOW_SECONDS = 300

@dataclass(frozen=True, slots=True)
class JitoBundleStatus:
    status: str
    landed_slot: int | None = None
    error_code: ExecutionErrorCode | None = None
    landed: bool = False
    ambiguous: bool = False

def parse_inflight_bundle_status(value: dict | None) -> JitoBundleStatus:
    if value is None: return JitoBundleStatus("Null", ambiguous=True)
    status = value.get("status")
    if status == "Landed": return JitoBundleStatus(status, value.get("landed_slot"), landed=True)
    if status == "Pending": return JitoBundleStatus(status, value.get("landed_slot"), ExecutionErrorCode.BUNDLE_PENDING, ambiguous=True)
    if status == "Failed": return JitoBundleStatus(status, value.get("landed_slot"), ExecutionErrorCode.BUNDLE_FAILED, ambiguous=True)
    if status == "Invalid": return JitoBundleStatus(status, value.get("landed_slot"), ExecutionErrorCode.BUNDLE_INVALID, ambiguous=True)
    raise ValueError(f"unknown Jito inflight bundle status: {status}")

def bundle_status_batches(bundle_ids: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(bundle_ids[i:i+MAX_BUNDLE_STATUS_IDS]) for i in range(0, len(bundle_ids), MAX_BUNDLE_STATUS_IDS))
