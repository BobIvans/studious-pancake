"""PR-017 compatible Pump event names and sanitizer."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Any

PUMP_EVENT_TYPES = (
    "pump_state_loaded", "pump_contract_version_detected", "pump_quote_created",
    "pump_quote_rejected", "pump_migration_state_changed", "pump_mint_excluded",
    "pump_snapshot_stale", "pump_heuristic_disabled", "pump_shadow_simulation_completed",
)


@dataclass(frozen=True)
class PumpEvent:
    event_type: str
    mint: str
    slot: int
    manifest_checksum: str
    account_hash: str
    lifecycle: str
    reason_code: str | None = None
    amounts: Mapping[str, int] | None = None

    def as_record(self) -> dict[str, Any]:
        if self.event_type not in PUMP_EVENT_TYPES:
            raise ValueError("unknown Pump event type")
        return {"event_type": self.event_type, "mint": self.mint, "slot": self.slot, "manifest_checksum": self.manifest_checksum, "account_hash": self.account_hash, "lifecycle": self.lifecycle, "reason_code": self.reason_code, "amounts": dict(self.amounts or {})}
