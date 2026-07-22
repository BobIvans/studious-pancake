"""Canonical PR-181 operation identity and crash-safe paper handoff.

This module is an active SQLite boundary, not a readiness-only evaluator.  It
stores exact operation results and transfers ownership of an active durable
reservation to the next sender-free paper stage in one transaction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
import sqlite3
import time
from typing import Any, Callable

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_operation_results_pr181(
 operation_id TEXT PRIMARY KEY,
 domain TEXT NOT NULL,
 attempt_id TEXT NOT NULL,
 attempt_generation INTEGER NOT NULL CHECK(attempt_generation>=1),
 operation TEXT NOT NULL,
 request_payload_hash TEXT NOT NULL,
 policy_generation TEXT NOT NULL,
 target_state TEXT NOT NULL,
 result_digest TEXT NOT NULL,
 result_json TEXT NOT NULL,
 created_at_ns INTEGER NOT NULL,
 UNIQUE(
  attempt_id,
  attempt_generation,
  operation,
  request_payload_hash,
  policy_generation
 )
);
CREATE TABLE IF NOT EXISTS paper_reservation_handoffs_pr181(
 handoff_id TEXT PRIMARY KEY,
 operation_id TEXT NOT NULL UNIQUE
  REFERENCES canonical_operation_results_pr181(operation_id) ON DELETE RESTRICT,
 attempt_id TEXT NOT NULL UNIQUE,
 reservation_id TEXT NOT NULL UNIQUE,
 stage TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 fencing_token INTEGER NOT NULL CHECK(fencing_token>=1),
 lease_expires_at_ns INTEGER NOT NULL,
 max_age_ns INTEGER NOT NULL CHECK(max_age_ns>0),
 status TEXT NOT NULL,
 result_digest TEXT NOT NULL,
 created_at_ns INTEGER NOT NULL,
 acknowledged_at_ns INTEGER
);
CREATE TABLE IF NOT EXISTS paper_handoff_outbox_pr181(
 outbox_id INTEGER PRIMARY KEY,
 handoff_id TEXT NOT NULL UNIQUE
  REFERENCES paper_reservation_handoffs_pr181(handoff_id) ON DELETE RESTRICT,
 attempt_id TEXT NOT NULL,
 topic TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',
 owner_id TEXT,
 fencing_token INTEGER,
 available_at_ns INTEGER NOT NULL,
 claimed_until_ns INTEGER,
 attempt_count INTEGER NOT NULL DEFAULT 0,
 created_at_ns INTEGER NOT NULL,
 completed_at_ns INTEGER
);
"""


class IdempotencyConflict(RuntimeError):
    """The same logical operation was reused with different request identity."""


class HandoffRecoveryAction(StrEnum):
    ACTIVE_OWNER = "active_owner"
    RECLAIM_EXPIRED_LEASE = "reclaim_expired_lease"
    MANUAL_REVIEW_MAX_AGE = "manual_review_max_age"
    ACKNOWLEDGED = "acknowledged"


@dataclass(frozen=True, slots=True)
class CanonicalOperationIdentity:
    domain: str
    attempt_id: str
    attempt_generation: int
    operation: str
    request_payload_hash: str
    policy_generation: str

    def __post_init__(self) -> None:
        for name in ("domain", "attempt_id", "operation", "policy_generation"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} is required")
        if isinstance(self.attempt_generation, bool) or self.attempt_generation < 1:
            raise ValueError("attempt_generation must be a positive integer")
        if not _SHA256.fullmatch(self.request_payload_hash):
            raise ValueError("request_payload_hash must be lowercase sha256")

    @classmethod
    def derive(
        cls,
        *,
        domain: str,
        attempt_id: str,
        attempt_generation: int,
        operation: str,
        request_payload: Mapping[str, object],
        policy_generation: str,
    ) -> "CanonicalOperationIdentity":
        return cls(
            domain=domain,
            attempt_id=attempt_id,
            attempt_generation=attempt_generation,
            operation=operation,
            request_payload_hash=canonical_digest(request_payload),
            policy_generation=policy_generation,
        )

    @property
    def operation_id(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class PaperHandoffReceipt:
    handoff_id: str
    operation_id: str
    attempt_id: str
    reservation_id: str
    owner_id: str
    fencing_token: int
    lease_expires_at_ns: int
    max_age_ns: int
    result_digest: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class HandoffRecoveryDecision:
    handoff_id: str
    attempt_id: str
    reservation_id: str
    action: HandoffRecoveryAction
    owner_id: str
    fencing_token: int
    lease_expires_at_ns: int
    age_ns: int


class CanonicalIdempotencyStore:
    """Exact-result idempotency and atomic reservation handoff on one SQLite DB."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.db = connection
        self.clock_ns = clock_ns
        with self.db:
            self.db.executescript(_SCHEMA)

    def commit_paper_handoff(
        self,
        *,
        identity: CanonicalOperationIdentity,
        reservation_id: str,
        result: Mapping[str, object],
        owner_id: str,
        lease_ttl_ns: int = 30_000_000_000,
        max_age_ns: int = 300_000_000_000,
        target_state: str = "ready_for_durable_paper",
    ) -> PaperHandoffReceipt:
        if identity.operation != "paper_handoff":
            raise ValueError("paper handoff requires paper_handoff operation")
        if not reservation_id or not owner_id:
            raise ValueError("reservation_id and owner_id are required")
        if lease_ttl_ns <= 0 or max_age_ns < lease_ttl_ns:
            raise ValueError("invalid handoff lease/max-age")
        result_json = canonical_json(result)
        result_digest = hashlib.sha256(result_json.encode("utf-8")).hexdigest()
        now = self.clock_ns()

        with self.db:
            existing = self.db.execute(
                "SELECT * FROM canonical_operation_results_pr181 "
                "WHERE operation_id=?",
                (identity.operation_id,),
            ).fetchone()
            if existing is not None:
                self._verify_exact_replay(
                    existing,
                    identity=identity,
                    target_state=target_state,
                    result_digest=result_digest,
                )
                return self._receipt(identity.operation_id, replayed=True)

            conflict = self.db.execute(
                "SELECT operation_id FROM canonical_operation_results_pr181 "
                "WHERE attempt_id=? AND attempt_generation=? AND operation=? "
                "AND policy_generation=?",
                (
                    identity.attempt_id,
                    identity.attempt_generation,
                    identity.operation,
                    identity.policy_generation,
                ),
            ).fetchone()
            if conflict is not None:
                raise IdempotencyConflict("IDEMPOTENCY_CONFLICT")

            attempt = self.db.execute(
                "SELECT generation,reservation_id,reservation_state "
                "FROM durable_attempts WHERE attempt_id=?",
                (identity.attempt_id,),
            ).fetchone()
            if attempt is None:
                raise IdempotencyConflict("HANDOFF_ATTEMPT_NOT_FOUND")
            if int(attempt["generation"]) != identity.attempt_generation:
                raise IdempotencyConflict("HANDOFF_ATTEMPT_GENERATION_MISMATCH")
            if str(attempt["reservation_id"] or "") != reservation_id:
                raise IdempotencyConflict("HANDOFF_RESERVATION_MISMATCH")
            if str(attempt["reservation_state"] or "") != "active":
                raise IdempotencyConflict("HANDOFF_RESERVATION_NOT_ACTIVE")

            reservation = self.db.execute(
                "SELECT state FROM durable_reservations "
                "WHERE attempt_id=? AND reservation_id=?",
                (identity.attempt_id, reservation_id),
            ).fetchone()
            if reservation is None or str(reservation["state"]) != "active":
                raise IdempotencyConflict("HANDOFF_DURABLE_RESERVATION_NOT_ACTIVE")

            self.db.execute(
                "INSERT INTO canonical_operation_results_pr181 VALUES"
                "(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identity.operation_id,
                    identity.domain,
                    identity.attempt_id,
                    identity.attempt_generation,
                    identity.operation,
                    identity.request_payload_hash,
                    identity.policy_generation,
                    target_state,
                    result_digest,
                    result_json,
                    now,
                ),
            )
            handoff_id = hashlib.sha256(
                f"paper-handoff\0{identity.operation_id}".encode("utf-8")
            ).hexdigest()
            lease_expires = now + lease_ttl_ns
            self.db.execute(
                "INSERT INTO paper_reservation_handoffs_pr181 VALUES"
                "(?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    handoff_id,
                    identity.operation_id,
                    identity.attempt_id,
                    reservation_id,
                    "durable_paper_outcome",
                    owner_id,
                    1,
                    lease_expires,
                    max_age_ns,
                    "pending",
                    result_digest,
                    now,
                ),
            )
            outbox_payload = canonical_json(
                {
                    "handoff_id": handoff_id,
                    "operation_id": identity.operation_id,
                    "attempt_id": identity.attempt_id,
                    "reservation_id": reservation_id,
                    "result_digest": result_digest,
                    "owner_id": owner_id,
                    "fencing_token": 1,
                }
            )
            self.db.execute(
                "INSERT INTO paper_handoff_outbox_pr181("
                "handoff_id,attempt_id,topic,payload_json,available_at_ns,"
                "created_at_ns) VALUES(?,?,?,?,?,?)",
                (
                    handoff_id,
                    identity.attempt_id,
                    "paper.outcome.persist",
                    outbox_payload,
                    now,
                    now,
                ),
            )
        return self._receipt(identity.operation_id, replayed=False)

    def acknowledge_handoff(
        self,
        handoff_id: str,
        *,
        owner_id: str,
        fencing_token: int,
    ) -> bool:
        now = self.clock_ns()
        with self.db:
            cursor = self.db.execute(
                "UPDATE paper_reservation_handoffs_pr181 "
                "SET status='acknowledged',acknowledged_at_ns=? "
                "WHERE handoff_id=? AND status='pending' AND owner_id=? "
                "AND fencing_token=?",
                (now, handoff_id, owner_id, fencing_token),
            )
            if cursor.rowcount:
                self.db.execute(
                    "UPDATE paper_handoff_outbox_pr181 "
                    "SET status='completed',completed_at_ns=? "
                    "WHERE handoff_id=? AND status='pending'",
                    (now, handoff_id),
                )
            return cursor.rowcount == 1

    def recovery_decisions(
        self,
        *,
        now_ns: int | None = None,
    ) -> tuple[HandoffRecoveryDecision, ...]:
        now = self.clock_ns() if now_ns is None else now_ns
        rows = self.db.execute(
            "SELECT * FROM paper_reservation_handoffs_pr181 "
            "ORDER BY created_at_ns,handoff_id"
        ).fetchall()
        decisions: list[HandoffRecoveryDecision] = []
        for row in rows:
            age = max(0, now - int(row["created_at_ns"]))
            if str(row["status"]) == "acknowledged":
                action = HandoffRecoveryAction.ACKNOWLEDGED
            elif age >= int(row["max_age_ns"]):
                action = HandoffRecoveryAction.MANUAL_REVIEW_MAX_AGE
            elif now >= int(row["lease_expires_at_ns"]):
                action = HandoffRecoveryAction.RECLAIM_EXPIRED_LEASE
            else:
                action = HandoffRecoveryAction.ACTIVE_OWNER
            decisions.append(
                HandoffRecoveryDecision(
                    handoff_id=str(row["handoff_id"]),
                    attempt_id=str(row["attempt_id"]),
                    reservation_id=str(row["reservation_id"]),
                    action=action,
                    owner_id=str(row["owner_id"]),
                    fencing_token=int(row["fencing_token"]),
                    lease_expires_at_ns=int(row["lease_expires_at_ns"]),
                    age_ns=age,
                )
            )
        return tuple(decisions)

    def _verify_exact_replay(
        self,
        row: sqlite3.Row,
        *,
        identity: CanonicalOperationIdentity,
        target_state: str,
        result_digest: str,
    ) -> None:
        expected = {
            "domain": identity.domain,
            "attempt_id": identity.attempt_id,
            "attempt_generation": identity.attempt_generation,
            "operation": identity.operation,
            "request_payload_hash": identity.request_payload_hash,
            "policy_generation": identity.policy_generation,
            "target_state": target_state,
            "result_digest": result_digest,
        }
        actual = {name: row[name] for name in expected}
        if actual != expected:
            raise IdempotencyConflict("IDEMPOTENCY_CONFLICT")

    def _receipt(self, operation_id: str, *, replayed: bool) -> PaperHandoffReceipt:
        row = self.db.execute(
            "SELECT * FROM paper_reservation_handoffs_pr181 "
            "WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            raise IdempotencyConflict("HANDOFF_RESULT_MISSING")
        return PaperHandoffReceipt(
            handoff_id=str(row["handoff_id"]),
            operation_id=operation_id,
            attempt_id=str(row["attempt_id"]),
            reservation_id=str(row["reservation_id"]),
            owner_id=str(row["owner_id"]),
            fencing_token=int(row["fencing_token"]),
            lease_expires_at_ns=int(row["lease_expires_at_ns"]),
            max_age_ns=int(row["max_age_ns"]),
            result_digest=str(row["result_digest"]),
            replayed=replayed,
        )


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


__all__ = [
    "CanonicalIdempotencyStore",
    "CanonicalOperationIdentity",
    "HandoffRecoveryAction",
    "HandoffRecoveryDecision",
    "IdempotencyConflict",
    "PaperHandoffReceipt",
    "canonical_digest",
    "canonical_json",
]
