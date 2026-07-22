"""PR-154 durable data-plane reliability supervisor.

This boundary composes account-wide Jupiter quota admission, rooted independent
RPC quorum, durable identity/deduplication, webhook gap recovery and bounded
backpressure. It performs no provider request and starts no strategy task.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable

from src.data_plane.rpc import (
    RootedRpcQuorumDecision,
    RootedRpcQuorumGate,
    RootedRpcSample,
)
from src.providers.jupiter.quota import (
    JupiterQuotaError,
    JupiterQuotaManager,
    JupiterQuotaPurpose,
)
from src.webhook_ingest_pr135 import (
    GapRecoveryCursor,
    WebhookEnvelope,
    WebhookGapDecision,
)


class DataIngressSource(StrEnum):
    PROVIDER = "provider"
    WEBHOOK = "webhook"


class DataIngressStatus(StrEnum):
    ADMITTED = "admitted"
    DUPLICATE = "duplicate"
    DEADLINE_EXPIRED = "deadline_expired"
    BACKPRESSURE = "backpressure"
    QUOTA_BLOCKED = "quota_blocked"
    RPC_BLOCKED = "rpc_blocked"
    GAP_RECOVERY_REQUIRED = "gap_recovery_required"


@dataclass(frozen=True, slots=True)
class ProviderIngressRequest:
    event_key: str
    candidate_id: str
    quota_purpose: JupiterQuotaPurpose
    request_fingerprint: str
    deadline_monotonic_ms: int
    queue_depth: int
    queue_capacity: int
    rooted_samples: tuple[RootedRpcSample, ...]
    expected_genesis_hash: str
    expected_method: str
    expected_request_hash: str
    min_context_slot: int
    now_wall_ms: int
    now_monotonic_ms: int

    def __post_init__(self) -> None:
        if not all(
            (
                self.event_key,
                self.candidate_id,
                self.request_fingerprint,
                self.expected_genesis_hash,
                self.expected_method,
                self.expected_request_hash,
            )
        ):
            raise ValueError("provider ingress identity fields are required")
        _validate_queue(self.queue_depth, self.queue_capacity)
        if min(
            self.deadline_monotonic_ms,
            self.min_context_slot,
            self.now_wall_ms,
            self.now_monotonic_ms,
        ) < 0:
            raise ValueError(
                "provider ingress time and slot values must be non-negative"
            )


@dataclass(frozen=True, slots=True)
class WebhookIngressRequest:
    envelope: WebhookEnvelope
    queue_depth: int
    queue_capacity: int
    max_allowed_slot_gap: int
    now_monotonic_ms: int

    def __post_init__(self) -> None:
        _validate_queue(self.queue_depth, self.queue_capacity)
        if self.max_allowed_slot_gap < 0 or self.now_monotonic_ms < 0:
            raise ValueError("webhook gap and time values must be non-negative")


@dataclass(frozen=True, slots=True)
class DataIngressDecision:
    source: DataIngressSource
    status: DataIngressStatus
    reason: str
    event_key_hash: str
    accepted: bool
    durable_sequence: int | None = None
    canonical_slot: int | None = None
    payload_hash: str | None = None
    rpc_evidence_hash: str | None = None
    quota_reservation_id: str | None = None
    backfill_required: bool = False

    @property
    def evidence_hash(self) -> str:
        return _hash_json(
            {
                "source": self.source.value,
                "status": self.status.value,
                "reason": self.reason,
                "event_key_hash": self.event_key_hash,
                "accepted": self.accepted,
                "durable_sequence": self.durable_sequence,
                "canonical_slot": self.canonical_slot,
                "payload_hash": self.payload_hash,
                "rpc_evidence_hash": self.rpc_evidence_hash,
                "quota_reservation_id": self.quota_reservation_id,
                "backfill_required": self.backfill_required,
            }
        )


class DurableDataPlaneJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS data_plane_decisions (
                    sequence_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    event_key_hash TEXT NOT NULL,
                    canonical_slot INTEGER,
                    payload_hash TEXT,
                    rpc_evidence_hash TEXT,
                    quota_reservation_id TEXT,
                    backfill_required INTEGER NOT NULL,
                    created_monotonic_ms INTEGER NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_data_plane_webhook_slot
                ON data_plane_decisions(source, status, canonical_slot)
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS data_plane_event_state (
                    event_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latest_sequence INTEGER NOT NULL
                )
                """
            )

    def contains_admitted(self, event_key: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1 FROM data_plane_event_state
            WHERE event_key = ? AND status = ?
            """,
            (event_key, DataIngressStatus.ADMITTED.value),
        ).fetchone()
        return row is not None

    def record(
        self,
        *,
        event_key: str,
        source: DataIngressSource,
        status: DataIngressStatus,
        reason: str,
        canonical_slot: int | None,
        payload_hash: str | None,
        rpc_evidence_hash: str | None,
        quota_reservation_id: str | None,
        backfill_required: bool,
        created_monotonic_ms: int,
    ) -> DataIngressDecision:
        event_key_hash = hashlib.sha256(event_key.encode("utf-8")).hexdigest()
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO data_plane_decisions (
                    event_key,
                    source,
                    status,
                    reason,
                    event_key_hash,
                    canonical_slot,
                    payload_hash,
                    rpc_evidence_hash,
                    quota_reservation_id,
                    backfill_required,
                    created_monotonic_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key,
                    source.value,
                    status.value,
                    reason,
                    event_key_hash,
                    canonical_slot,
                    payload_hash,
                    rpc_evidence_hash,
                    quota_reservation_id,
                    int(backfill_required),
                    created_monotonic_ms,
                ),
            )
            sequence = int(cursor.lastrowid)
            self.connection.execute(
                """
                INSERT INTO data_plane_event_state (
                    event_key, source, status, latest_sequence
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(event_key) DO UPDATE SET
                    source = excluded.source,
                    status = excluded.status,
                    latest_sequence = excluded.latest_sequence
                """,
                (event_key, source.value, status.value, sequence),
            )
        return DataIngressDecision(
            source=source,
            status=status,
            reason=reason,
            event_key_hash=event_key_hash,
            accepted=status is DataIngressStatus.ADMITTED,
            durable_sequence=sequence,
            canonical_slot=canonical_slot,
            payload_hash=payload_hash,
            rpc_evidence_hash=rpc_evidence_hash,
            quota_reservation_id=quota_reservation_id,
            backfill_required=backfill_required,
        )

    def last_accepted_webhook_slot(self) -> int | None:
        row = self.connection.execute(
            """
            SELECT MAX(canonical_slot)
            FROM data_plane_decisions
            WHERE source = ? AND status = ?
            """,
            (DataIngressSource.WEBHOOK.value, DataIngressStatus.ADMITTED.value),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    def count(self) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM data_plane_decisions"
        ).fetchone()
        return int(row[0])

    def close(self) -> None:
        self.connection.close()


class DataReliabilitySupervisor:
    def __init__(
        self,
        *,
        quota: JupiterQuotaManager,
        rpc_quorum: RootedRpcQuorumGate,
        journal: DurableDataPlaneJournal,
        clock_monotonic_ms: Callable[[], int],
    ) -> None:
        self.quota = quota
        self.rpc_quorum = rpc_quorum
        self.journal = journal
        self.clock_monotonic_ms = clock_monotonic_ms

    async def admit_provider(
        self, request: ProviderIngressRequest
    ) -> DataIngressDecision:
        precheck = self._precheck(
            event_key=request.event_key,
            source=DataIngressSource.PROVIDER,
            queue_depth=request.queue_depth,
            queue_capacity=request.queue_capacity,
            deadline_monotonic_ms=request.deadline_monotonic_ms,
        )
        if precheck is not None:
            return precheck

        try:
            quota_token = await self.quota.reserve(
                request.quota_purpose,
                request_fingerprint=request.request_fingerprint,
            )
        except JupiterQuotaError as exc:
            return self.journal.record(
                event_key=request.event_key,
                source=DataIngressSource.PROVIDER,
                status=DataIngressStatus.QUOTA_BLOCKED,
                reason=f"PR154_QUOTA:{exc.reason}",
                canonical_slot=None,
                payload_hash=None,
                rpc_evidence_hash=None,
                quota_reservation_id=None,
                backfill_required=False,
                created_monotonic_ms=self.clock_monotonic_ms(),
            )

        quorum = self.rpc_quorum.evaluate(
            request.rooted_samples,
            expected_genesis_hash=request.expected_genesis_hash,
            expected_method=request.expected_method,
            expected_request_hash=request.expected_request_hash,
            min_context_slot=request.min_context_slot,
            now_wall_ms=request.now_wall_ms,
            now_monotonic_ms=request.now_monotonic_ms,
        )
        if not quorum.accepted:
            await self.quota.release_unissued(quota_token)
            return self._record_rpc_blocked(request, quorum)

        await self.quota.mark_used(quota_token)
        return self.journal.record(
            event_key=request.event_key,
            source=DataIngressSource.PROVIDER,
            status=DataIngressStatus.ADMITTED,
            reason="PR154_PROVIDER_READY",
            canonical_slot=quorum.canonical_slot,
            payload_hash=quorum.payload_hash,
            rpc_evidence_hash=quorum.evidence_hash,
            quota_reservation_id=quota_token.reservation_id,
            backfill_required=False,
            created_monotonic_ms=self.clock_monotonic_ms(),
        )

    def admit_webhook(self, request: WebhookIngressRequest) -> DataIngressDecision:
        event_key = request.envelope.identity.key
        if self.journal.contains_admitted(event_key):
            return _duplicate_decision(DataIngressSource.WEBHOOK, event_key)
        if request.queue_depth >= request.queue_capacity:
            return self.journal.record(
                event_key=event_key,
                source=DataIngressSource.WEBHOOK,
                status=DataIngressStatus.BACKPRESSURE,
                reason="PR154_WEBHOOK_QUEUE_FULL",
                canonical_slot=request.envelope.identity.slot,
                payload_hash=request.envelope.identity.payload_hash,
                rpc_evidence_hash=None,
                quota_reservation_id=None,
                backfill_required=False,
                created_monotonic_ms=request.now_monotonic_ms,
            )

        gap = GapRecoveryCursor(
            last_seen_slot=self.journal.last_accepted_webhook_slot(),
            incoming_slot=request.envelope.identity.slot,
            max_allowed_slot_gap=request.max_allowed_slot_gap,
        ).evaluate()
        if gap is WebhookGapDecision.GAP_RECOVERY_REQUIRED:
            return self.journal.record(
                event_key=event_key,
                source=DataIngressSource.WEBHOOK,
                status=DataIngressStatus.GAP_RECOVERY_REQUIRED,
                reason="PR154_ROOTED_BACKFILL_REQUIRED",
                canonical_slot=request.envelope.identity.slot,
                payload_hash=request.envelope.identity.payload_hash,
                rpc_evidence_hash=None,
                quota_reservation_id=None,
                backfill_required=True,
                created_monotonic_ms=request.now_monotonic_ms,
            )

        return self.journal.record(
            event_key=event_key,
            source=DataIngressSource.WEBHOOK,
            status=DataIngressStatus.ADMITTED,
            reason="PR154_WEBHOOK_READY",
            canonical_slot=request.envelope.identity.slot,
            payload_hash=request.envelope.identity.payload_hash,
            rpc_evidence_hash=None,
            quota_reservation_id=None,
            backfill_required=False,
            created_monotonic_ms=request.now_monotonic_ms,
        )

    def _precheck(
        self,
        *,
        event_key: str,
        source: DataIngressSource,
        queue_depth: int,
        queue_capacity: int,
        deadline_monotonic_ms: int,
    ) -> DataIngressDecision | None:
        if self.journal.contains_admitted(event_key):
            return _duplicate_decision(source, event_key)
        now_ms = self.clock_monotonic_ms()
        if now_ms > deadline_monotonic_ms:
            return self.journal.record(
                event_key=event_key,
                source=source,
                status=DataIngressStatus.DEADLINE_EXPIRED,
                reason="PR154_CANDIDATE_DEADLINE_EXPIRED",
                canonical_slot=None,
                payload_hash=None,
                rpc_evidence_hash=None,
                quota_reservation_id=None,
                backfill_required=False,
                created_monotonic_ms=now_ms,
            )
        if queue_depth >= queue_capacity:
            return self.journal.record(
                event_key=event_key,
                source=source,
                status=DataIngressStatus.BACKPRESSURE,
                reason="PR154_PROVIDER_QUEUE_FULL",
                canonical_slot=None,
                payload_hash=None,
                rpc_evidence_hash=None,
                quota_reservation_id=None,
                backfill_required=False,
                created_monotonic_ms=now_ms,
            )
        return None

    def _record_rpc_blocked(
        self,
        request: ProviderIngressRequest,
        quorum: RootedRpcQuorumDecision,
    ) -> DataIngressDecision:
        return self.journal.record(
            event_key=request.event_key,
            source=DataIngressSource.PROVIDER,
            status=DataIngressStatus.RPC_BLOCKED,
            reason=quorum.reason.value,
            canonical_slot=quorum.canonical_slot,
            payload_hash=quorum.payload_hash,
            rpc_evidence_hash=quorum.evidence_hash,
            quota_reservation_id=None,
            backfill_required=False,
            created_monotonic_ms=self.clock_monotonic_ms(),
        )


def _duplicate_decision(
    source: DataIngressSource, event_key: str
) -> DataIngressDecision:
    return DataIngressDecision(
        source=source,
        status=DataIngressStatus.DUPLICATE,
        reason="PR154_DURABLE_DUPLICATE",
        event_key_hash=hashlib.sha256(event_key.encode("utf-8")).hexdigest(),
        accepted=False,
    )


def _validate_queue(depth: int, capacity: int) -> None:
    if depth < 0 or capacity <= 0 or depth > capacity:
        raise ValueError("queue depth/capacity are invalid")


def _hash_json(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
