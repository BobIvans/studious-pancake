"""PR-182 active trusted-time integration for the durable lifecycle store.

The legacy PR-041 state machine remains the single lifecycle implementation.
This module subclasses it and replaces correctness-sensitive wall-clock lease and
outbox-claim expiry with boot-bound monotonic time plus fencing.  UTC values are
still written for audit/retention compatibility, but they are not used to decide
whether an owner remains live.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from src.time_authority import (
    ClockAnomalyKind,
    ClockUnhealthyError,
    SystemTimeAuthority,
    TimeAuthority,
    TimeSnapshot,
    TimeSourceStatus,
)

from .lifecycle import (
    DurableLifecycleStore as LegacyDurableLifecycleStore,
    LeaseLostError,
    LeaseToken,
    OutboxItem,
)

PR182_DURABLE_TIME_SCHEMA = "pr182.durable-time-domains.v1"

_TIME_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS durable_lease_time_domains(
 resource_key TEXT PRIMARY KEY,
 boot_id TEXT NOT NULL,
 process_generation INTEGER NOT NULL CHECK(process_generation>=1),
 acquired_monotonic_ns INTEGER NOT NULL,
 expires_monotonic_ns INTEGER NOT NULL,
 acquired_utc_ns INTEGER NOT NULL,
 expires_utc_ns INTEGER NOT NULL,
 time_source_status TEXT NOT NULL,
 max_uncertainty_ns INTEGER NOT NULL,
 CHECK(expires_monotonic_ns>acquired_monotonic_ns),
 CHECK(expires_utc_ns>acquired_utc_ns));
CREATE TABLE IF NOT EXISTS durable_outbox_claim_time_domains(
 outbox_id INTEGER PRIMARY KEY,
 owner_id TEXT NOT NULL,
 fencing_token INTEGER NOT NULL CHECK(fencing_token>=1),
 boot_id TEXT NOT NULL,
 process_generation INTEGER NOT NULL CHECK(process_generation>=1),
 claimed_at_monotonic_ns INTEGER NOT NULL,
 claimed_until_monotonic_ns INTEGER NOT NULL,
 claimed_at_utc_ns INTEGER NOT NULL,
 claimed_until_utc_ns INTEGER NOT NULL,
 CHECK(claimed_until_monotonic_ns>claimed_at_monotonic_ns),
 CHECK(claimed_until_utc_ns>claimed_at_utc_ns));
CREATE TABLE IF NOT EXISTS durable_time_incidents(
 incident_id INTEGER PRIMARY KEY,
 kind TEXT NOT NULL,
 resource_key TEXT,
 boot_id TEXT NOT NULL,
 process_generation INTEGER NOT NULL,
 observed_utc_ns INTEGER NOT NULL,
 observed_monotonic_ns INTEGER NOT NULL,
 evidence_json TEXT NOT NULL,
 created_at_ns INTEGER NOT NULL);
"""


class ClockSafeDurableLifecycleStore(LegacyDurableLifecycleStore):
    """PR-041 lifecycle store with PR-182 clock-safe ownership semantics."""

    def __init__(
        self,
        path: str | Path,
        *,
        topology: str = "single-node",
        busy_timeout_ms: int = 5_000,
        time_authority: TimeAuthority | None = None,
        clock_ns: Callable[[], int] | None = None,
    ) -> None:
        if time_authority is not None and clock_ns is not None:
            raise ValueError("provide time_authority or legacy clock_ns, not both")
        self.time_authority = time_authority or _authority_from_legacy_clock(clock_ns)
        super().__init__(
            path,
            topology=topology,
            busy_timeout_ms=busy_timeout_ms,
            clock_ns=self._audit_utc_ns,
        )
        with self.db:
            self.db.executescript(_TIME_SCHEMA_SQL)

    def _audit_utc_ns(self) -> int:
        return self.time_authority.snapshot().utc_ns

    def _ownership_snapshot(self, resource_key: str | None = None) -> TimeSnapshot:
        snapshot = self.time_authority.snapshot()
        if snapshot.time_source_status is TimeSourceStatus.ANOMALOUS:
            self._record_time_incident(
                ClockAnomalyKind.UTC_ROLLBACK.value,
                snapshot,
                resource_key=resource_key,
                evidence={"reason": "time-authority-reported-anomaly"},
            )
            raise ClockUnhealthyError(
                "clock anomaly freezes durable ownership transitions"
            )
        return snapshot

    def _record_time_incident(
        self,
        kind: str,
        snapshot: TimeSnapshot,
        *,
        resource_key: str | None,
        evidence: dict[str, Any],
    ) -> None:
        payload = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        self.db.execute(
            "INSERT INTO durable_time_incidents(kind,resource_key,boot_id,"
            "process_generation,observed_utc_ns,observed_monotonic_ns,"
            "evidence_json,created_at_ns) VALUES(?,?,?,?,?,?,?,?)",
            (
                kind,
                resource_key,
                snapshot.boot_id,
                snapshot.process_generation,
                snapshot.utc_ns,
                snapshot.monotonic_ns,
                payload,
                snapshot.utc_ns,
            ),
        )

    def acquire_lease(
        self,
        resource_key: str,
        *,
        owner_id: str,
        ttl_ns: int,
    ) -> LeaseToken:
        if not resource_key or not owner_id or ttl_ns <= 0:
            raise ValueError("resource, owner and positive ttl are required")
        now = self._ownership_snapshot(resource_key)
        expires_monotonic = now.monotonic_ns + ttl_ns
        expires_utc = now.utc_ns + ttl_ns
        with self.db:
            row = self.db.execute(
                "SELECT l.*,d.boot_id,d.process_generation,"
                "d.expires_monotonic_ns FROM durable_leases AS l "
                "LEFT JOIN durable_lease_time_domains AS d USING(resource_key) "
                "WHERE l.resource_key=?",
                (resource_key,),
            ).fetchone()
            if row is not None:
                domain_present = row["boot_id"] is not None
                if not domain_present and row["owner_id"] != owner_id:
                    raise LeaseLostError(
                        "legacy lease has no boot/time-domain identity; operator "
                        "reconciliation or same-owner upgrade is required"
                    )
                if domain_present:
                    same_domain = (
                        str(row["boot_id"]) == now.boot_id
                        and int(row["process_generation"])
                        == now.process_generation
                    )
                    live = same_domain and (
                        int(row["expires_monotonic_ns"]) > now.monotonic_ns
                    )
                    if live and row["owner_id"] != owner_id:
                        raise LeaseLostError("resource has another live owner")
                    if not same_domain:
                        self._record_time_incident(
                            ClockAnomalyKind.BOOT_DOMAIN_CHANGED.value,
                            now,
                            resource_key=resource_key,
                            evidence={
                                "previous_boot_id": row["boot_id"],
                                "previous_process_generation": row[
                                    "process_generation"
                                ],
                                "action": "old-monotonic-lease-invalidated",
                            },
                        )
            fence = int(row["fencing_token"]) + 1 if row is not None else 1
            self.db.execute(
                "INSERT INTO durable_leases VALUES(?,?,?,?,?) "
                "ON CONFLICT(resource_key) DO UPDATE SET "
                "owner_id=excluded.owner_id,"
                "fencing_token=excluded.fencing_token,"
                "expires_at_ns=excluded.expires_at_ns,"
                "updated_at_ns=excluded.updated_at_ns",
                (resource_key, owner_id, fence, expires_utc, now.utc_ns),
            )
            self.db.execute(
                "INSERT INTO durable_lease_time_domains VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(resource_key) DO UPDATE SET "
                "boot_id=excluded.boot_id,"
                "process_generation=excluded.process_generation,"
                "acquired_monotonic_ns=excluded.acquired_monotonic_ns,"
                "expires_monotonic_ns=excluded.expires_monotonic_ns,"
                "acquired_utc_ns=excluded.acquired_utc_ns,"
                "expires_utc_ns=excluded.expires_utc_ns,"
                "time_source_status=excluded.time_source_status,"
                "max_uncertainty_ns=excluded.max_uncertainty_ns",
                (
                    resource_key,
                    now.boot_id,
                    now.process_generation,
                    now.monotonic_ns,
                    expires_monotonic,
                    now.utc_ns,
                    expires_utc,
                    now.time_source_status.value,
                    now.max_uncertainty_ns,
                ),
            )
        # ``expires_at_ns`` remains the durable UTC upper bound for compatibility.
        # Verification below intentionally ignores it for same-boot ownership.
        return LeaseToken(resource_key, owner_id, fence, expires_utc)

    def _verify_lease(self, token: LeaseToken, resource: str) -> None:
        now = self._ownership_snapshot(resource)
        row = self.db.execute(
            "SELECT l.owner_id,l.fencing_token,d.boot_id,"
            "d.process_generation,d.expires_monotonic_ns "
            "FROM durable_leases AS l "
            "LEFT JOIN durable_lease_time_domains AS d USING(resource_key) "
            "WHERE l.resource_key=?",
            (resource,),
        ).fetchone()
        if row is None or row["boot_id"] is None:
            raise LeaseLostError("lease lacks trusted boot/time-domain identity")
        valid = (
            row["owner_id"] == token.owner_id
            and int(row["fencing_token"]) == token.fencing_token
            and str(row["boot_id"]) == now.boot_id
            and int(row["process_generation"]) == now.process_generation
            and int(row["expires_monotonic_ns"]) > now.monotonic_ns
        )
        if not valid:
            raise LeaseLostError("stale, expired, or cross-boot fencing token")

    def claim_outbox(
        self,
        *,
        topic: str,
        owner_id: str,
        limit: int = 100,
        lease_ns: int = 30_000_000_000,
    ) -> tuple[OutboxItem, ...]:
        if limit < 1 or lease_ns <= 0:
            raise ValueError("positive limit and lease required")
        now = self._ownership_snapshot(f"outbox:{topic}")
        lease = self.acquire_lease(
            f"outbox:{topic}", owner_id=owner_id, ttl_ns=lease_ns
        )
        until_monotonic = now.monotonic_ns + lease_ns
        until_utc = now.utc_ns + lease_ns
        output: list[OutboxItem] = []
        with self.db:
            rows = self.db.execute(
                "SELECT * FROM durable_outbox WHERE topic=? "
                "AND status='pending' AND available_at_ns<=? "
                "ORDER BY outbox_id LIMIT ?",
                (topic, now.utc_ns, max(limit * 4, limit)),
            ).fetchall()
            for row in rows:
                if len(output) >= limit:
                    break
                claim = self.db.execute(
                    "INSERT INTO durable_outbox_claim_time_domains VALUES(?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(outbox_id) DO UPDATE SET "
                    "owner_id=excluded.owner_id,"
                    "fencing_token=excluded.fencing_token,"
                    "boot_id=excluded.boot_id,"
                    "process_generation=excluded.process_generation,"
                    "claimed_at_monotonic_ns=excluded.claimed_at_monotonic_ns,"
                    "claimed_until_monotonic_ns=excluded.claimed_until_monotonic_ns,"
                    "claimed_at_utc_ns=excluded.claimed_at_utc_ns,"
                    "claimed_until_utc_ns=excluded.claimed_until_utc_ns "
                    "WHERE durable_outbox_claim_time_domains.boot_id<>excluded.boot_id "
                    "OR durable_outbox_claim_time_domains.process_generation<>"
                    "excluded.process_generation "
                    "OR durable_outbox_claim_time_domains.claimed_until_monotonic_ns<=?",
                    (
                        row["outbox_id"],
                        owner_id,
                        lease.fencing_token,
                        now.boot_id,
                        now.process_generation,
                        now.monotonic_ns,
                        until_monotonic,
                        now.utc_ns,
                        until_utc,
                        now.monotonic_ns,
                    ),
                )
                if claim.rowcount != 1:
                    continue
                cur = self.db.execute(
                    "UPDATE durable_outbox SET owner_id=?,fencing_token=?,"
                    "claimed_until_ns=?,attempt_count=attempt_count+1 "
                    "WHERE outbox_id=? AND status='pending'",
                    (
                        owner_id,
                        lease.fencing_token,
                        until_utc,
                        row["outbox_id"],
                    ),
                )
                if cur.rowcount != 1:
                    self.db.execute(
                        "DELETE FROM durable_outbox_claim_time_domains "
                        "WHERE outbox_id=? AND owner_id=? AND fencing_token=?",
                        (row["outbox_id"], owner_id, lease.fencing_token),
                    )
                    continue
                output.append(
                    OutboxItem(
                        int(row["outbox_id"]),
                        str(row["event_id"]),
                        str(row["attempt_id"]),
                        str(row["topic"]),
                        json.loads(str(row["payload_json"])),
                        lease.fencing_token,
                    )
                )
        return tuple(output)

    def complete_outbox(
        self,
        item: OutboxItem,
        *,
        owner_id: str,
    ) -> bool:
        now = self._ownership_snapshot(f"outbox-item:{item.outbox_id}")
        with self.db:
            claim = self.db.execute(
                "SELECT * FROM durable_outbox_claim_time_domains "
                "WHERE outbox_id=?",
                (item.outbox_id,),
            ).fetchone()
            if claim is None:
                return False
            valid = (
                claim["owner_id"] == owner_id
                and int(claim["fencing_token"]) == item.fencing_token
                and str(claim["boot_id"]) == now.boot_id
                and int(claim["process_generation"]) == now.process_generation
                and int(claim["claimed_until_monotonic_ns"]) > now.monotonic_ns
            )
            if not valid:
                return False
            cur = self.db.execute(
                "UPDATE durable_outbox SET status='completed',"
                "completed_at_ns=?,claimed_until_ns=NULL WHERE outbox_id=? "
                "AND status='pending' AND owner_id=? AND fencing_token=?",
                (now.utc_ns, item.outbox_id, owner_id, item.fencing_token),
            )
            if cur.rowcount == 1:
                self.db.execute(
                    "DELETE FROM durable_outbox_claim_time_domains "
                    "WHERE outbox_id=?",
                    (item.outbox_id,),
                )
                return True
            return False

    def trusted_time_status(self) -> dict[str, object]:
        snapshot = self.time_authority.snapshot()
        incidents = int(
            self.db.execute("SELECT COUNT(*) FROM durable_time_incidents").fetchone()[0]
        )
        return {
            "schema_version": PR182_DURABLE_TIME_SCHEMA,
            "snapshot": snapshot.to_json(),
            "incident_count": incidents,
            "lease_correctness_clock": "boot-bound-monotonic",
            "utc_role": "audit-and-durable-upper-bound-only",
            "live_permit_issuance_allowed": (
                snapshot.healthy_for_sensitive_operations and incidents == 0
            ),
            "live_enabled": False,
        }


def _authority_from_legacy_clock(
    clock_ns: Callable[[], int] | None,
) -> TimeAuthority:
    if clock_ns is None:
        # Paper/durable ownership is safe with same-boot monotonic time even when
        # host UTC synchronization is not yet attested.  Live-sensitive issuance
        # still fails closed because status is DEGRADED rather than SYNCHRONIZED.
        return SystemTimeAuthority(source_status=TimeSourceStatus.DEGRADED)
    return SystemTimeAuthority(
        boot_id="legacy-injected-clock-domain",
        source_status=TimeSourceStatus.SYNCHRONIZED,
        max_uncertainty_ns=0,
        max_step_ns=2**62,
        utc_clock_ns=clock_ns,
        monotonic_clock_ns=clock_ns,
    )


# Public compatibility name used by ``src.durability``.
DurableLifecycleStore = ClockSafeDurableLifecycleStore


__all__ = [
    "ClockSafeDurableLifecycleStore",
    "DurableLifecycleStore",
    "PR182_DURABLE_TIME_SCHEMA",
]
