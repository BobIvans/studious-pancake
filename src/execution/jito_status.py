from __future__ import annotations
from dataclasses import dataclass
from .models import ExecutionErrorCode

@dataclass(frozen=True, slots=True)
class JitoBundleStatus:
    status: str
    landed_slot: int | None = None
    error_code: ExecutionErrorCode | None = None
    landed: bool = False

def parse_inflight_bundle_status(value: dict) -> JitoBundleStatus:
    status = value.get("status")
    if status == "Landed": return JitoBundleStatus(status, value.get("landed_slot"), landed=True)
    if status == "Pending": return JitoBundleStatus(status, value.get("landed_slot"), ExecutionErrorCode.BUNDLE_PENDING)
    if status == "Failed": return JitoBundleStatus(status, value.get("landed_slot"), ExecutionErrorCode.BUNDLE_FAILED)
    if status == "Invalid": return JitoBundleStatus(status, value.get("landed_slot"), ExecutionErrorCode.BUNDLE_INVALID)
    raise ValueError(f"unknown Jito inflight bundle status: {status}")
