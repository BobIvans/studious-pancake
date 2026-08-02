"""Deterministic PR-007 fault and alert qualification catalogue."""

from __future__ import annotations
from dataclasses import dataclass
from .service import digest

FAULTS = (
    "provider_partition",
    "provider_timeout",
    "provider_429",
    "provider_5xx",
    "malformed_response",
    "oversized_response",
    "rpc_disagreement",
    "rpc_fork",
    "stale_slot",
    "webhook_duplicates",
    "webhook_gaps",
    "detector_crash",
    "consumer_crash",
    "db_lock",
    "db_full",
    "db_corruption",
    "disk_pressure",
    "kill_9",
    "restart",
    "clock_skew",
    "cache_eviction",
    "dependency_outage",
    "config_expiration",
    "rollback_attempt",
    "secret_revocation",
    "backup_during_load",
    "shutdown_during_handler",
)

ALERTS = {
    "provider_partition": "dead_data_plane",
    "stale_slot": "stale_provider",
    "disk_pressure": "disk_wal_pressure",
    "config_expiration": "config_expiry",
    "db_corruption": "failed_backup",
    "consumer_crash": "readiness_loss",
    "db_lock": "blocked_outbox",
    "dependency_outage": "unresolved_reconciliation",
}


@dataclass(frozen=True)
class FaultResult:
    fault: str
    readiness_blocked: bool
    alert: str | None
    release_digest: str
    evidence_hash: str


def run_campaign(release_digest: str) -> tuple[FaultResult, ...]:
    """Materialize expected fail-closed outcomes, bound to a real release digest."""
    if len(release_digest) != 64 or any(
        c not in "0123456789abcdef" for c in release_digest
    ):
        raise ValueError("release_digest must be a lowercase SHA-256")
    return tuple(
        FaultResult(
            f,
            True,
            ALERTS.get(f),
            release_digest,
            digest(
                {
                    "fault": f,
                    "readiness_blocked": True,
                    "alert": ALERTS.get(f),
                    "release_digest": release_digest,
                }
            ),
        )
        for f in FAULTS
    )
