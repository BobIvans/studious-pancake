"""MEGA-PR B3 durable Helius inbox processing and rooted recovery.

This module consumes the SQLite inbox committed by :mod:`src.providers.helius.delivery`.
It adds worker leases, fencing, bounded retries, dead-letter handling, rooted gap
recovery and one transactional handoff into the A3 database authority.  It performs
no signing, sending or live transaction action.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Callable, Protocol

from .delivery import HeliusDeliveryStore, canonical_event_identity

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_VERSION = "mega-pr-b3.rooted-recovery.v1"


class RecoveryStatus(StrEnum):
    ADMITTED = "admitted"
    DUPLICATE = "duplicate"
    GAP_BLOCKED = "gap_blocked"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"
    IDLE = "idle"


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    lease_duration_ns: int = 30_000_000_000
    retry_delay_ns: int = 1_000_000_000
    max_attempts: int = 5

    def __post_init__(self) -> None:
        values = (
            self.lease_duration_ns,
            self.retry_delay_ns,
            self.max_attempts,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in values
        ):
            raise ValueError("recovery policy limits must be positive integers")


@dataclass(frozen=True, slots=True)
class InboxClaim:
    inbox_id: int
    delivery_id: str
    webhook_id: str
    dedup_key: str
    signature: str
    slot: int | None
    event_index: int
    payload_hash: str
    payload_json: str
    failed: bool
    worker_id: str
    fencing_token: int
    attempt: int
    lease_expires_monotonic_ns: int

    @property
    def event_identity(self) -> str:
        return canonical_event_identity(
            webhook_id=self.webhook_id,
            signature=self.signature,
            slot=self.slot,
            payload_hash=self.payload_hash,
        )


@dataclass(frozen=True, slots=True)
class RootedBackfillResult:
    accepted: bool
    webhook_id: str
    gap_from_slot: int
    gap_to_slot: int
    rooted_through_slot: int | None
    rpc_evidence_hash: str | None
    chain_context_hash: str | None
    release_digest: str
    policy_bundle_hash: str
    expires_at_monotonic_ns: int
    reason: str

    def __post_init__(self) -> None:
        if not self.webhook_id or not self.reason:
            raise ValueError("backfill identity and reason are required")
        for name, value in (
            ("gap_from_slot", self.gap_from_slot),
            ("gap_to_slot", self.gap_to_slot),
            ("expires_at_monotonic_ns", self.expires_at_monotonic_ns),
        ):
            _non_negative_int(value, name)
        if self.gap_to_slot < self.gap_from_slot:
            raise ValueError("gap_to_slot cannot precede gap_from_slot")
        _digest(self.release_digest, "release_digest")
        _digest(self.policy_bundle_hash, "policy_bundle_hash")
        if self.accepted:
            if self.rooted_through_slot is None:
                raise ValueError("accepted backfill requires rooted_through_slot")
            _non_negative_int(self.rooted_through_slot, "rooted_through_slot")
            if self.rooted_through_slot < self.gap_to_slot:
                raise ValueError("backfill does not cover the complete gap")
            _digest(self.rpc_evidence_hash, "rpc_evidence_hash")
            _digest(self.chain_context_hash, "chain_context_hash")


@dataclass(frozen=True, slots=True)
class VerifiedProviderEvent:
    event_identity: str
    inbox_id: int
    webhook_id: str
    signature: str
    slot: int | None
    payload_hash: str
    payload_json: str
    release_digest: str
    policy_bundle_hash: str
    provider_evidence_hash: str
    rpc_evidence_hash: str
    chain_context_hash: str
    expires_at_monotonic_ns: int
    verifier_identity: str
    independently_verified: bool = True
    live_enabled: bool = False
    sender_reachable: bool = False

    def __post_init__(self) -> None:
        _digest(self.event_identity, "event_identity")
        _positive_int(self.inbox_id, "inbox_id")
        if not self.webhook_id or not self.signature:
            raise ValueError("provider event identity fields are required")
        if self.slot is not None:
            _non_negative_int(self.slot, "slot")
        for name, value in (
            ("payload_hash", self.payload_hash),
            ("release_digest", self.release_digest),
            ("policy_bundle_hash", self.policy_bundle_hash),
            ("provider_evidence_hash", self.provider_evidence_hash),
            ("rpc_evidence_hash", self.rpc_evidence_hash),
            ("chain_context_hash", self.chain_context_hash),
        ):
            _digest(value, name)
        _non_negative_int(
            self.expires_at_monotonic_ns,
            "expires_at_monotonic_ns",
        )
        if not self.verifier_identity:
            raise ValueError("verifier_identity is required")
        if not self.independently_verified:
            raise ValueError("provider event must be independently verified")
        if self.live_enabled or self.sender_reachable:
            raise ValueError("B3 evidence must remain sender-free and live-disabled")
        expected_identity = canonical_event_identity(
            webhook_id=self.webhook_id,
            signature=self.signature,
            slot=self.slot,
            payload_hash=self.payload_hash,
        )
        if self.event_identity != expected_identity:
            raise ValueError("provider event identity mismatch")

    @property
    def evidence_hash(self) -> str:
        return _hash_json(
            {
                "schema_version": SCHEMA_VERSION,
                "event_identity": self.event_identity,
                "inbox_id": self.inbox_id,
                "webhook_id": self.webhook_id,
                "signature": self.signature,
                "slot": self.slot,
                "payload_hash": self.payload_hash,
                "release_digest": self.release_digest,
                "policy_bundle_hash": self.policy_bundle_hash,
                "provider_evidence_hash": self.provider_evidence_hash,
                "rpc_evidence_hash": self.rpc_evidence_hash,
                "chain_context_hash": self.chain_context_hash,
                "expires_at_monotonic_ns": self.expires_at_monotonic_ns,
                "verifier_identity": self.verifier_identity,
                "independently_verified": self.independently_verified,
                "live_enabled": self.live_enabled,
                "sender_reachable": self.sender_reachable,
            }
        )


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    status: RecoveryStatus
    reason: str
    inbox_id: int | None = None
    event_identity: str | None = None
    a3_result_id: str | None = None
    attempt: int | None = None
    fencing_token: int | None = None
    evidence_hash: str | None = None
    live_enabled: bool = False
    sender_reachable: bool = False


class RootedBackfillPort(Protocol):
    def recover(
        self,
        *,
        webhook_id: str,
        gap_from_slot: int,
        gap_to_slot: int,
        release_digest: str,
        policy_bundle_hash: str,
        now_monotonic_ns: int,
    ) -> RootedBackfillResult: ...


class ProviderEvidenceVerifierPort(Protocol):
    def verify(
        self,
        claim: InboxClaim,
        *,
        release_digest: str,
        policy_bundle_hash: str,
        now_monotonic_ns: int,
    ) -> VerifiedProviderEvent: ...


class A3AdmissionSinkPort(Protocol):
    """Commit the A3 admission using the worker's active SQLite transaction."""

    def commit(
        self,
        connection: sqlite3.Connection,
        evidence: VerifiedProviderEvent,
    ) -> str: ...


class RootedRecoveryStore:
    """Lease/fencing state layered onto the canonical Helius inbox database."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.delivery_store = HeliusDeliveryStore(self.path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        self.delivery_store.initialize()
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS helius_inbox_work (
                    inbox_id INTEGER PRIMARY KEY
                        REFERENCES helius_event_inbox(id),
                    status TEXT NOT NULL,
                    owner TEXT,
                    fencing_token INTEGER NOT NULL DEFAULT 0,
                    lease_expires_monotonic_ns INTEGER,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_monotonic_ns INTEGER NOT NULL DEFAULT 0,
                    last_reason TEXT,
                    updated_monotonic_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS helius_a3_handoff (
                    event_identity TEXT PRIMARY KEY,
                    inbox_id INTEGER UNIQUE NOT NULL
                        REFERENCES helius_event_inbox(id),
                    evidence_hash TEXT NOT NULL,
                    release_digest TEXT NOT NULL,
                    policy_bundle_hash TEXT NOT NULL,
                    a3_result_id TEXT NOT NULL,
                    committed_monotonic_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS helius_dead_letter (
                    inbox_id INTEGER PRIMARY KEY
                        REFERENCES helius_event_inbox(id),
                    event_identity TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    evidence_hash TEXT,
                    created_monotonic_ns INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_helius_inbox_work_claim
                ON helius_inbox_work(
                    status,
                    next_attempt_monotonic_ns,
                    lease_expires_monotonic_ns
                );
                """
            )
            self._seed_work(connection, 0)

    @staticmethod
    def _seed_work(
        connection: sqlite3.Connection,
        now_monotonic_ns: int,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO helius_inbox_work(
                inbox_id,
                status,
                owner,
                fencing_token,
                lease_expires_monotonic_ns,
                attempts,
                next_attempt_monotonic_ns,
                last_reason,
                updated_monotonic_ns
            )
            SELECT
                id,
                'pending',
                NULL,
                0,
                NULL,
                0,
                0,
                NULL,
                ?
            FROM helius_event_inbox
            WHERE processed_at_ns IS NULL
            """,
            (now_monotonic_ns,),
        )

    def claim_next(
        self,
        *,
        worker_id: str,
        now_monotonic_ns: int,
        policy: RecoveryPolicy,
    ) -> InboxClaim | None:
        if not worker_id:
            raise ValueError("worker_id is required")
        _non_negative_int(now_monotonic_ns, "now_monotonic_ns")
        self.initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._seed_work(connection, now_monotonic_ns)
            row = connection.execute(
                """
                SELECT
                    work.inbox_id,
                    inbox.delivery_id,
                    delivery.webhook_id,
                    inbox.dedup_key,
                    inbox.signature,
                    inbox.slot,
                    inbox.event_index,
                    inbox.payload_hash,
                    inbox.payload_json,
                    inbox.failed,
                    work.fencing_token,
                    work.attempts
                FROM helius_inbox_work AS work
                JOIN helius_event_inbox AS inbox
                    ON inbox.id = work.inbox_id
                JOIN helius_delivery AS delivery
                    ON delivery.delivery_id = inbox.delivery_id
                LEFT JOIN helius_a3_handoff AS handoff
                    ON handoff.inbox_id = inbox.id
                WHERE handoff.inbox_id IS NULL
                  AND inbox.processed_at_ns IS NULL
                  AND (
                    (
                        work.status IN ('pending', 'retry', 'gap_blocked')
                        AND work.next_attempt_monotonic_ns <= ?
                    )
                    OR (
                        work.status = 'processing'
                        AND work.lease_expires_monotonic_ns <= ?
                    )
                  )
                ORDER BY
                    CASE WHEN inbox.slot IS NULL THEN 1 ELSE 0 END,
                    inbox.slot,
                    inbox.event_index,
                    inbox.id
                LIMIT 1
                """,
                (now_monotonic_ns, now_monotonic_ns),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            if row["payload_json"] is None:
                self._dead_letter_missing_payload(
                    connection,
                    row,
                    now_monotonic_ns,
                )
                connection.commit()
                return None
            fencing_token = int(row["fencing_token"]) + 1
            attempt = int(row["attempts"]) + 1
            lease_expires = now_monotonic_ns + policy.lease_duration_ns
            updated = connection.execute(
                """
                UPDATE helius_inbox_work
                SET
                    status = 'processing',
                    owner = ?,
                    fencing_token = ?,
                    lease_expires_monotonic_ns = ?,
                    attempts = ?,
                    last_reason = NULL,
                    updated_monotonic_ns = ?
                WHERE inbox_id = ?
                """,
                (
                    worker_id,
                    fencing_token,
                    lease_expires,
                    attempt,
                    now_monotonic_ns,
                    int(row["inbox_id"]),
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise RuntimeError("B3 inbox claim lost")
            connection.commit()
            return InboxClaim(
                inbox_id=int(row["inbox_id"]),
                delivery_id=str(row["delivery_id"]),
                webhook_id=str(row["webhook_id"]),
                dedup_key=str(row["dedup_key"]),
                signature=str(row["signature"]),
                slot=None if row["slot"] is None else int(row["slot"]),
                event_index=int(row["event_index"]),
                payload_hash=str(row["payload_hash"]),
                payload_json=str(row["payload_json"]),
                failed=bool(row["failed"]),
                worker_id=worker_id,
                fencing_token=fencing_token,
                attempt=attempt,
                lease_expires_monotonic_ns=lease_expires,
            )

    @staticmethod
    def _dead_letter_missing_payload(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        now_monotonic_ns: int,
    ) -> None:
        event_identity = canonical_event_identity(
            webhook_id=str(row["webhook_id"]),
            signature=str(row["signature"]),
            slot=None if row["slot"] is None else int(row["slot"]),
            payload_hash=str(row["payload_hash"]),
        )
        attempts = int(row["attempts"]) + 1
        connection.execute(
            """
            INSERT OR REPLACE INTO helius_dead_letter(
                inbox_id,
                event_identity,
                reason,
                attempts,
                evidence_hash,
                created_monotonic_ns
            ) VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (
                int(row["inbox_id"]),
                event_identity,
                "B3_MISSING_CANONICAL_PAYLOAD",
                attempts,
                now_monotonic_ns,
            ),
        )
        connection.execute(
            """
            UPDATE helius_inbox_work
            SET
                status = 'dead_letter',
                owner = NULL,
                lease_expires_monotonic_ns = NULL,
                attempts = ?,
                last_reason = ?,
                updated_monotonic_ns = ?
            WHERE inbox_id = ?
            """,
            (
                attempts,
                "B3_MISSING_CANONICAL_PAYLOAD",
                now_monotonic_ns,
                int(row["inbox_id"]),
            ),
        )

    def gap(self, webhook_id: str) -> tuple[int, int, int | None] | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT gap_from_slot, gap_to_slot, last_slot
                FROM helius_gap_state
                WHERE webhook_id = ?
                """,
                (webhook_id,),
            ).fetchone()
        if (
            row is None
            or row["gap_from_slot"] is None
            or row["gap_to_slot"] is None
        ):
            return None
        return (
            int(row["gap_from_slot"]),
            int(row["gap_to_slot"]),
            None if row["last_slot"] is None else int(row["last_slot"]),
        )

    def close_gap(
        self,
        *,
        claim: InboxClaim,
        result: RootedBackfillResult,
        release_digest: str,
        policy_bundle_hash: str,
        now_monotonic_ns: int,
    ) -> None:
        if not result.accepted:
            raise ValueError("B3_ROOTED_BACKFILL_REJECTED")
        if result.webhook_id != claim.webhook_id:
            raise ValueError("B3_BACKFILL_WEBHOOK_MISMATCH")
        if result.release_digest != release_digest:
            raise ValueError("B3_BACKFILL_RELEASE_MISMATCH")
        if result.policy_bundle_hash != policy_bundle_hash:
            raise ValueError("B3_BACKFILL_POLICY_MISMATCH")
        if result.expires_at_monotonic_ns < now_monotonic_ns:
            raise ValueError("B3_BACKFILL_EVIDENCE_EXPIRED")
        gap = self.gap(claim.webhook_id)
        if gap is None:
            return
        gap_from, gap_to, _ = gap
        if (
            result.gap_from_slot != gap_from
            or result.gap_to_slot != gap_to
            or result.rooted_through_slot is None
            or result.rooted_through_slot < gap_to
        ):
            raise ValueError("B3_BACKFILL_RANGE_MISMATCH")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, claim)
            connection.execute(
                """
                UPDATE helius_gap_state
                SET
                    last_slot = CASE
                        WHEN last_slot IS NULL THEN ?
                        WHEN last_slot < ? THEN ?
                        ELSE last_slot
                    END,
                    gap_from_slot = NULL,
                    gap_to_slot = NULL,
                    updated_at_ns = ?
                WHERE webhook_id = ?
                  AND gap_from_slot = ?
                  AND gap_to_slot = ?
                """,
                (
                    result.rooted_through_slot,
                    result.rooted_through_slot,
                    result.rooted_through_slot,
                    time.time_ns(),
                    claim.webhook_id,
                    gap_from,
                    gap_to,
                ),
            )
            connection.execute(
                """
                INSERT INTO helius_delivery_audit(
                    delivery_id,
                    reason,
                    detail_hash,
                    created_at_ns
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    claim.delivery_id,
                    "rooted_gap_recovered",
                    _hash_json(
                        {
                            "rpc_evidence_hash": result.rpc_evidence_hash,
                            "chain_context_hash": result.chain_context_hash,
                            "release_digest": release_digest,
                            "policy_bundle_hash": policy_bundle_hash,
                            "gap_from_slot": gap_from,
                            "gap_to_slot": gap_to,
                        }
                    ),
                    time.time_ns(),
                ),
            )
            connection.commit()

    def commit_handoff(
        self,
        *,
        claim: InboxClaim,
        evidence: VerifiedProviderEvent,
        sink: A3AdmissionSinkPort,
        now_monotonic_ns: int,
    ) -> RecoveryOutcome:
        if evidence.inbox_id != claim.inbox_id:
            raise ValueError("B3_EVIDENCE_INBOX_MISMATCH")
        if evidence.event_identity != claim.event_identity:
            raise ValueError("B3_EVIDENCE_IDENTITY_MISMATCH")
        if evidence.payload_hash != claim.payload_hash:
            raise ValueError("B3_EVIDENCE_PAYLOAD_MISMATCH")
        if evidence.payload_json != claim.payload_json:
            raise ValueError("B3_EVIDENCE_CANONICAL_PAYLOAD_MISMATCH")
        if evidence.expires_at_monotonic_ns < now_monotonic_ns:
            raise ValueError("B3_PROVIDER_EVIDENCE_EXPIRED")
        self.initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, claim)
            existing = connection.execute(
                """
                SELECT a3_result_id, evidence_hash
                FROM helius_a3_handoff
                WHERE event_identity = ?
                """,
                (evidence.event_identity,),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE helius_inbox_work
                    SET
                        status = 'admitted',
                        owner = NULL,
                        lease_expires_monotonic_ns = NULL,
                        last_reason = 'B3_DUPLICATE_HANDOFF',
                        updated_monotonic_ns = ?
                    WHERE inbox_id = ?
                    """,
                    (now_monotonic_ns, claim.inbox_id),
                )
                connection.execute(
                    """
                    UPDATE helius_event_inbox
                    SET processed_at_ns = COALESCE(processed_at_ns, ?)
                    WHERE id = ?
                    """,
                    (time.time_ns(), claim.inbox_id),
                )
                connection.commit()
                return RecoveryOutcome(
                    RecoveryStatus.DUPLICATE,
                    "B3_DUPLICATE_HANDOFF",
                    claim.inbox_id,
                    evidence.event_identity,
                    str(existing["a3_result_id"]),
                    claim.attempt,
                    claim.fencing_token,
                    str(existing["evidence_hash"]),
                )

            a3_result_id = sink.commit(connection, evidence)
            if not a3_result_id:
                connection.rollback()
                raise ValueError("B3_A3_RESULT_ID_MISSING")
            connection.execute(
                """
                INSERT INTO helius_a3_handoff(
                    event_identity,
                    inbox_id,
                    evidence_hash,
                    release_digest,
                    policy_bundle_hash,
                    a3_result_id,
                    committed_monotonic_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.event_identity,
                    claim.inbox_id,
                    evidence.evidence_hash,
                    evidence.release_digest,
                    evidence.policy_bundle_hash,
                    a3_result_id,
                    now_monotonic_ns,
                ),
            )
            connection.execute(
                """
                UPDATE helius_inbox_work
                SET
                    status = 'admitted',
                    owner = NULL,
                    lease_expires_monotonic_ns = NULL,
                    last_reason = 'B3_A3_HANDOFF_COMMITTED',
                    updated_monotonic_ns = ?
                WHERE inbox_id = ?
                """,
                (now_monotonic_ns, claim.inbox_id),
            )
            connection.execute(
                """
                UPDATE helius_event_inbox
                SET processed_at_ns = ?
                WHERE id = ?
                """,
                (time.time_ns(), claim.inbox_id),
            )
            connection.commit()
            return RecoveryOutcome(
                RecoveryStatus.ADMITTED,
                "B3_A3_HANDOFF_COMMITTED",
                claim.inbox_id,
                evidence.event_identity,
                a3_result_id,
                claim.attempt,
                claim.fencing_token,
                evidence.evidence_hash,
            )

    def defer(
        self,
        *,
        claim: InboxClaim,
        reason: str,
        now_monotonic_ns: int,
        policy: RecoveryPolicy,
        evidence_hash: str | None = None,
        gap_blocked: bool = False,
    ) -> RecoveryOutcome:
        safe_reason = _safe_reason(reason)
        dead_letter = claim.attempt >= policy.max_attempts
        status = (
            RecoveryStatus.DEAD_LETTER
            if dead_letter
            else (
                RecoveryStatus.GAP_BLOCKED
                if gap_blocked
                else RecoveryStatus.RETRY
            )
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, claim)
            if dead_letter:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO helius_dead_letter(
                        inbox_id,
                        event_identity,
                        reason,
                        attempts,
                        evidence_hash,
                        created_monotonic_ns
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim.inbox_id,
                        claim.event_identity,
                        safe_reason,
                        claim.attempt,
                        evidence_hash,
                        now_monotonic_ns,
                    ),
                )
            connection.execute(
                """
                UPDATE helius_inbox_work
                SET
                    status = ?,
                    owner = NULL,
                    lease_expires_monotonic_ns = NULL,
                    next_attempt_monotonic_ns = ?,
                    last_reason = ?,
                    updated_monotonic_ns = ?
                WHERE inbox_id = ?
                """,
                (
                    status.value,
                    now_monotonic_ns + policy.retry_delay_ns,
                    safe_reason,
                    now_monotonic_ns,
                    claim.inbox_id,
                ),
            )
            connection.commit()
        return RecoveryOutcome(
            status,
            safe_reason,
            claim.inbox_id,
            claim.event_identity,
            None,
            claim.attempt,
            claim.fencing_token,
            evidence_hash,
        )

    @staticmethod
    def _assert_fence(
        connection: sqlite3.Connection,
        claim: InboxClaim,
    ) -> None:
        row = connection.execute(
            """
            SELECT owner, fencing_token, status
            FROM helius_inbox_work
            WHERE inbox_id = ?
            """,
            (claim.inbox_id,),
        ).fetchone()
        if (
            row is None
            or str(row["owner"]) != claim.worker_id
            or int(row["fencing_token"]) != claim.fencing_token
            or str(row["status"]) != "processing"
        ):
            raise RuntimeError("B3_WORKER_FENCE_LOST")

    def counts(self) -> dict[str, int]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*)
                FROM helius_inbox_work
                GROUP BY status
                """
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}


class RootedRecoveryWorker:
    """One bounded worker iteration with durable lease and rooted recovery."""

    def __init__(
        self,
        *,
        store: RootedRecoveryStore,
        backfill: RootedBackfillPort,
        verifier: ProviderEvidenceVerifierPort,
        sink: A3AdmissionSinkPort,
        release_digest: str,
        policy_bundle_hash: str,
        policy: RecoveryPolicy = RecoveryPolicy(),
        clock_monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        _digest(release_digest, "release_digest")
        _digest(policy_bundle_hash, "policy_bundle_hash")
        self.store = store
        self.backfill = backfill
        self.verifier = verifier
        self.sink = sink
        self.release_digest = release_digest
        self.policy_bundle_hash = policy_bundle_hash
        self.policy = policy
        self.clock_monotonic_ns = clock_monotonic_ns
        self.store.initialize()

    def run_once(self, worker_id: str) -> RecoveryOutcome:
        now_ns = self.clock_monotonic_ns()
        claim = self.store.claim_next(
            worker_id=worker_id,
            now_monotonic_ns=now_ns,
            policy=self.policy,
        )
        if claim is None:
            return RecoveryOutcome(RecoveryStatus.IDLE, "B3_INBOX_IDLE")

        gap = self.store.gap(claim.webhook_id)
        if gap is not None:
            gap_from, gap_to, _ = gap
            try:
                backfill = self.backfill.recover(
                    webhook_id=claim.webhook_id,
                    gap_from_slot=gap_from,
                    gap_to_slot=gap_to,
                    release_digest=self.release_digest,
                    policy_bundle_hash=self.policy_bundle_hash,
                    now_monotonic_ns=now_ns,
                )
                self.store.close_gap(
                    claim=claim,
                    result=backfill,
                    release_digest=self.release_digest,
                    policy_bundle_hash=self.policy_bundle_hash,
                    now_monotonic_ns=now_ns,
                )
            except (TypeError, ValueError, RuntimeError) as exc:
                return self.store.defer(
                    claim=claim,
                    reason=f"B3_BACKFILL_{type(exc).__name__.upper()}",
                    now_monotonic_ns=now_ns,
                    policy=self.policy,
                    gap_blocked=True,
                )

        try:
            evidence = self.verifier.verify(
                claim,
                release_digest=self.release_digest,
                policy_bundle_hash=self.policy_bundle_hash,
                now_monotonic_ns=now_ns,
            )
            return self.store.commit_handoff(
                claim=claim,
                evidence=evidence,
                sink=self.sink,
                now_monotonic_ns=now_ns,
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            return self.store.defer(
                claim=claim,
                reason=(
                    "B3_VERIFY_OR_HANDOFF_"
                    f"{type(exc).__name__.upper()}"
                ),
                now_monotonic_ns=now_ns,
                policy=self.policy,
            )


def _digest(value: str | None, name: str) -> None:
    if value is None or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase sha256 digest")


def _positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _non_negative_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _safe_reason(value: str) -> str:
    normalized = "".join(
        character
        for character in value.upper()
        if character.isalnum() or character == "_"
    )
    return (normalized or "B3_UNKNOWN_FAILURE")[:96]


def _hash_json(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "SCHEMA_VERSION",
    "A3AdmissionSinkPort",
    "InboxClaim",
    "ProviderEvidenceVerifierPort",
    "RecoveryOutcome",
    "RecoveryPolicy",
    "RecoveryStatus",
    "RootedBackfillPort",
    "RootedBackfillResult",
    "RootedRecoveryStore",
    "RootedRecoveryWorker",
    "VerifiedProviderEvent",
]
