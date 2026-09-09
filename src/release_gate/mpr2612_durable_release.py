"""Durable MPR-2612 state transitions on the accepted PR-02 SQLite authority.

This module is support code for the canonical final gate in
``mpr31_final_promotion_gate``.  It never opens a second database connection and
never commits or rolls back a caller-owned transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3
from typing import Iterable

from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority
from src.release_gate.mpr31_final_promotion_gate import (
    FinalReleaseDecision,
    ReleaseApproval,
    ReleaseState,
    TARGET_PRODUCT_STATE,
)

MPR2612_DURABLE_SCHEMA = "mpr-2612.durable-release-state.v1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mpr2612_release_state(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 release_generation INTEGER NOT NULL CHECK(release_generation>=0),
 state TEXT NOT NULL,
 release_id TEXT,
 qualification_digest TEXT,
 proposal_digest TEXT,
 revision INTEGER NOT NULL CHECK(revision>=0),
 receipt_digest TEXT,
 live_enabled INTEGER NOT NULL CHECK(live_enabled=0),
 unrestricted_live_allowed INTEGER NOT NULL CHECK(unrestricted_live_allowed=0),
 automatic_scale_up_allowed INTEGER NOT NULL CHECK(automatic_scale_up_allowed=0));
CREATE TABLE IF NOT EXISTS mpr2612_consumed_approval(
 approval_digest TEXT PRIMARY KEY,
 release_id TEXT NOT NULL,
 release_generation INTEGER NOT NULL CHECK(release_generation>=1),
 principal_id TEXT NOT NULL,
 public_key_id TEXT NOT NULL,
 proposal_digest TEXT NOT NULL,
 qualification_digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mpr2612_release_receipt(
 receipt_digest TEXT PRIMARY KEY,
 release_id TEXT NOT NULL,
 release_generation INTEGER NOT NULL UNIQUE CHECK(release_generation>=1),
 previous_generation INTEGER NOT NULL CHECK(previous_generation>=0),
 proposal_digest TEXT NOT NULL,
 qualification_digest TEXT NOT NULL,
 reviewer_principals_json TEXT NOT NULL,
 state TEXT NOT NULL,
 product_state TEXT NOT NULL,
 live_enabled INTEGER NOT NULL CHECK(live_enabled=0),
 unrestricted_live_allowed INTEGER NOT NULL CHECK(unrestricted_live_allowed=0),
 automatic_scale_up_allowed INTEGER NOT NULL CHECK(automatic_scale_up_allowed=0),
 payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mpr2612_release_transition(
 transition_digest TEXT PRIMARY KEY,
 release_generation INTEGER NOT NULL CHECK(release_generation>=0),
 from_state TEXT NOT NULL,
 to_state TEXT NOT NULL,
 reason_code TEXT NOT NULL,
 receipt_digest TEXT,
 payload_json TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS mpr2612_receipt_no_update
BEFORE UPDATE ON mpr2612_release_receipt
BEGIN SELECT RAISE(ABORT, 'MPR2612_IMMUTABLE_RECEIPT'); END;
CREATE TRIGGER IF NOT EXISTS mpr2612_receipt_no_delete
BEFORE DELETE ON mpr2612_release_receipt
BEGIN SELECT RAISE(ABORT, 'MPR2612_IMMUTABLE_RECEIPT'); END;
"""


class DurableReleaseError(RuntimeError):
    """Fail-closed durable release transition error."""


@dataclass(frozen=True, slots=True)
class FinalReleaseReceipt:
    receipt_digest: str
    release_id: str
    release_generation: int
    previous_generation: int
    proposal_digest: str
    qualification_digest: str
    reviewer_principals: tuple[str, ...]
    state: ReleaseState
    product_state: str
    live_enabled: bool = False
    unrestricted_live_allowed: bool = False
    automatic_scale_up_allowed: bool = False

    def verify(self) -> bool:
        return self.receipt_digest == _receipt_digest(
            release_id=self.release_id,
            release_generation=self.release_generation,
            previous_generation=self.previous_generation,
            proposal_digest=self.proposal_digest,
            qualification_digest=self.qualification_digest,
            reviewer_principals=self.reviewer_principals,
            state=self.state,
            product_state=self.product_state,
        )


class MPR2612DurableReleaseAuthority:
    """Atomic release-generation transitions on a caller-owned PR-02 connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        UnifiedLifecycleAuthority.assert_connection_is_authority(connection)
        self.db = connection

    def install_schema(self) -> None:
        """Install additive tables inside a caller-owned transaction."""
        self._require_transaction()
        self.db.executescript(_SCHEMA)
        row = self.db.execute(
            "SELECT release_generation FROM mpr2612_release_state WHERE singleton=1"
        ).fetchone()
        if row is None:
            self.db.execute(
                "INSERT INTO mpr2612_release_state(" 
                "singleton,release_generation,state,revision,live_enabled," 
                "unrestricted_live_allowed,automatic_scale_up_allowed) " 
                "VALUES(1,0,?,0,0,0,0)",
                (ReleaseState.UNQUALIFIED.value,),
            )

    def qualify_default_off(
        self,
        *,
        release_id: str,
        qualification_digest: str,
        expected_revision: int,
    ) -> None:
        self._require_transaction()
        row = self._state_row()
        if row["state"] in {
            ReleaseState.RELEASE_REVOKED.value,
            ReleaseState.ROLLED_BACK.value,
        }:
            raise DurableReleaseError("MPR2612_TERMINAL_STATE_CANNOT_REQUALIFY")
        cursor = self.db.execute(
            "UPDATE mpr2612_release_state SET state=?,release_id=?,"
            "qualification_digest=?,proposal_digest=NULL,receipt_digest=NULL,"
            "revision=revision+1 WHERE singleton=1 AND revision=?",
            (
                ReleaseState.QUALIFIED_DEFAULT_OFF.value,
                release_id,
                qualification_digest,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise DurableReleaseError("MPR2612_STALE_RELEASE_REVISION")

    def promote(
        self,
        decision: FinalReleaseDecision,
        approvals: Iterable[ReleaseApproval],
        *,
        expected_generation: int,
        expected_revision: int,
    ) -> FinalReleaseReceipt:
        self._require_transaction()
        if not decision.allowed:
            raise DurableReleaseError("MPR2612_BLOCKED_DECISION_CANNOT_PROMOTE")
        if decision.state is not ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF:
            raise DurableReleaseError("MPR2612_INVALID_PROMOTION_STATE")
        if decision.live_enabled or decision.unrestricted_live_allowed:
            raise DurableReleaseError("MPR2612_LIVE_PROMOTION_FORBIDDEN")
        if decision.automatic_scale_up_allowed:
            raise DurableReleaseError("MPR2612_AUTO_SCALE_PROMOTION_FORBIDDEN")

        row = self._state_row()
        if row["state"] == ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF.value:
            return self._exact_replay(decision, expected_generation)
        if row["state"] != ReleaseState.QUALIFIED_DEFAULT_OFF.value:
            raise DurableReleaseError("MPR2612_NOT_QUALIFIED_DEFAULT_OFF")
        if row["release_id"] != decision.release_id:
            raise DurableReleaseError("MPR2612_RELEASE_ID_DRIFT")
        if row["qualification_digest"] != decision.qualification_digest:
            raise DurableReleaseError("MPR2612_QUALIFICATION_DRIFT")
        if int(row["release_generation"]) != expected_generation:
            raise DurableReleaseError("MPR2612_STALE_RELEASE_GENERATION")
        if int(row["revision"]) != expected_revision:
            raise DurableReleaseError("MPR2612_STALE_RELEASE_REVISION")

        approval_tuple = tuple(approvals)
        principals = tuple(sorted({item.principal_id for item in approval_tuple}))
        if len(principals) < 2:
            raise DurableReleaseError("MPR2612_TWO_HUMANS_REQUIRED_AT_COMMIT")
        next_generation = expected_generation + 1
        receipt_digest = _receipt_digest(
            release_id=decision.release_id,
            release_generation=next_generation,
            previous_generation=expected_generation,
            proposal_digest=decision.proposal_digest,
            qualification_digest=decision.qualification_digest,
            reviewer_principals=principals,
            state=ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF,
            product_state=TARGET_PRODUCT_STATE,
        )
        payload = {
            "schema_version": MPR2612_DURABLE_SCHEMA,
            "release_id": decision.release_id,
            "release_generation": next_generation,
            "previous_generation": expected_generation,
            "proposal_digest": decision.proposal_digest,
            "qualification_digest": decision.qualification_digest,
            "reviewer_principals": list(principals),
            "state": ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF.value,
            "product_state": TARGET_PRODUCT_STATE,
            "production_ready": True,
            "release_claim_allowed": True,
            "live_enabled": False,
            "unrestricted_live_allowed": False,
            "automatic_scale_up_allowed": False,
        }
        payload_json = _canonical_json(payload)

        for item in approval_tuple:
            approval_digest = hashlib.sha256(item.signed_payload()).hexdigest()
            try:
                self.db.execute(
                    "INSERT INTO mpr2612_consumed_approval VALUES(?,?,?,?,?,?,?)",
                    (
                        approval_digest,
                        decision.release_id,
                        next_generation,
                        item.principal_id,
                        item.public_key_id,
                        decision.proposal_digest,
                        decision.qualification_digest,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DurableReleaseError("MPR2612_APPROVAL_ALREADY_CONSUMED") from exc

        self.db.execute(
            "INSERT INTO mpr2612_release_receipt VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                receipt_digest,
                decision.release_id,
                next_generation,
                expected_generation,
                decision.proposal_digest,
                decision.qualification_digest,
                _canonical_json(list(principals)),
                ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF.value,
                TARGET_PRODUCT_STATE,
                0,
                0,
                0,
                payload_json,
            ),
        )
        cursor = self.db.execute(
            "UPDATE mpr2612_release_state SET release_generation=?,state=?,"
            "proposal_digest=?,receipt_digest=?,revision=revision+1 "
            "WHERE singleton=1 AND release_generation=? AND revision=? "
            "AND state=? AND live_enabled=0 AND unrestricted_live_allowed=0 "
            "AND automatic_scale_up_allowed=0",
            (
                next_generation,
                ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF.value,
                decision.proposal_digest,
                receipt_digest,
                expected_generation,
                expected_revision,
                ReleaseState.QUALIFIED_DEFAULT_OFF.value,
            ),
        )
        if cursor.rowcount != 1:
            raise DurableReleaseError("MPR2612_PROMOTION_CAS_LOST")
        self._record_transition(
            release_generation=next_generation,
            from_state=ReleaseState.QUALIFIED_DEFAULT_OFF,
            to_state=ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF,
            reason_code="MPR2612_PROMOTED_DEFAULT_OFF",
            receipt_digest=receipt_digest,
            payload=payload,
        )
        return FinalReleaseReceipt(
            receipt_digest=receipt_digest,
            release_id=decision.release_id,
            release_generation=next_generation,
            previous_generation=expected_generation,
            proposal_digest=decision.proposal_digest,
            qualification_digest=decision.qualification_digest,
            reviewer_principals=principals,
            state=ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF,
            product_state=TARGET_PRODUCT_STATE,
        )

    def suspend(self, *, reason_code: str, expected_revision: int) -> None:
        self._transition_from_released(
            ReleaseState.RELEASE_SUSPENDED,
            reason_code=reason_code,
            expected_revision=expected_revision,
        )

    def revoke(self, *, reason_code: str, expected_revision: int) -> None:
        self._transition_from_any_nonterminal(
            ReleaseState.RELEASE_REVOKED,
            reason_code=reason_code,
            expected_revision=expected_revision,
        )

    def rollback(
        self,
        *,
        target_receipt_digest: str,
        reason_code: str,
        expected_revision: int,
    ) -> None:
        self._require_transaction()
        target = self.db.execute(
            "SELECT receipt_digest FROM mpr2612_release_receipt WHERE receipt_digest=?",
            (target_receipt_digest,),
        ).fetchone()
        if target is None:
            raise DurableReleaseError("MPR2612_ROLLBACK_TARGET_UNQUALIFIED")
        self._transition_from_any_nonterminal(
            ReleaseState.ROLLED_BACK,
            reason_code=reason_code,
            expected_revision=expected_revision,
            receipt_digest=target_receipt_digest,
        )

    def read_receipt(self, receipt_digest: str) -> FinalReleaseReceipt:
        row = self.db.execute(
            "SELECT * FROM mpr2612_release_receipt WHERE receipt_digest=?",
            (receipt_digest,),
        ).fetchone()
        if row is None:
            raise DurableReleaseError("MPR2612_RECEIPT_NOT_FOUND")
        principals = tuple(json.loads(row["reviewer_principals_json"]))
        receipt = FinalReleaseReceipt(
            receipt_digest=row["receipt_digest"],
            release_id=row["release_id"],
            release_generation=int(row["release_generation"]),
            previous_generation=int(row["previous_generation"]),
            proposal_digest=row["proposal_digest"],
            qualification_digest=row["qualification_digest"],
            reviewer_principals=principals,
            state=ReleaseState(row["state"]),
            product_state=row["product_state"],
        )
        if not receipt.verify():
            raise DurableReleaseError("MPR2612_RECEIPT_DIGEST_MISMATCH")
        return receipt

    def state(self) -> dict[str, object]:
        row = self._state_row()
        return dict(row)

    def _exact_replay(
        self,
        decision: FinalReleaseDecision,
        expected_generation: int,
    ) -> FinalReleaseReceipt:
        row = self._state_row()
        if (
            int(row["release_generation"]) != expected_generation + 1
            or row["release_id"] != decision.release_id
            or row["proposal_digest"] != decision.proposal_digest
            or row["qualification_digest"] != decision.qualification_digest
            or not row["receipt_digest"]
        ):
            raise DurableReleaseError("MPR2612_PROMOTION_REPLAY_CONFLICT")
        return self.read_receipt(str(row["receipt_digest"]))

    def _transition_from_released(
        self,
        target: ReleaseState,
        *,
        reason_code: str,
        expected_revision: int,
    ) -> None:
        self._require_transaction()
        row = self._state_row()
        if row["state"] != ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF.value:
            raise DurableReleaseError("MPR2612_RELEASE_NOT_ACTIVE")
        self._transition(
            row,
            target,
            reason_code=reason_code,
            expected_revision=expected_revision,
        )

    def _transition_from_any_nonterminal(
        self,
        target: ReleaseState,
        *,
        reason_code: str,
        expected_revision: int,
        receipt_digest: str | None = None,
    ) -> None:
        self._require_transaction()
        row = self._state_row()
        if row["state"] in {
            ReleaseState.RELEASE_REVOKED.value,
            ReleaseState.ROLLED_BACK.value,
        }:
            raise DurableReleaseError("MPR2612_TERMINAL_RELEASE_STATE")
        self._transition(
            row,
            target,
            reason_code=reason_code,
            expected_revision=expected_revision,
            receipt_digest=receipt_digest,
        )

    def _transition(
        self,
        row: sqlite3.Row,
        target: ReleaseState,
        *,
        reason_code: str,
        expected_revision: int,
        receipt_digest: str | None = None,
    ) -> None:
        if not reason_code.strip():
            raise DurableReleaseError("MPR2612_TRANSITION_REASON_REQUIRED")
        cursor = self.db.execute(
            "UPDATE mpr2612_release_state SET state=?,revision=revision+1 "
            "WHERE singleton=1 AND revision=? AND state=?",
            (target.value, expected_revision, row["state"]),
        )
        if cursor.rowcount != 1:
            raise DurableReleaseError("MPR2612_TRANSITION_CAS_LOST")
        payload = {
            "release_id": row["release_id"],
            "release_generation": int(row["release_generation"]),
            "from_state": row["state"],
            "to_state": target.value,
            "reason_code": reason_code,
            "receipt_digest": receipt_digest or row["receipt_digest"],
        }
        self._record_transition(
            release_generation=int(row["release_generation"]),
            from_state=ReleaseState(row["state"]),
            to_state=target,
            reason_code=reason_code,
            receipt_digest=receipt_digest or row["receipt_digest"],
            payload=payload,
        )

    def _record_transition(
        self,
        *,
        release_generation: int,
        from_state: ReleaseState,
        to_state: ReleaseState,
        reason_code: str,
        receipt_digest: str | None,
        payload: dict[str, object],
    ) -> None:
        payload_json = _canonical_json(payload)
        transition_digest = hashlib.sha256(payload_json.encode()).hexdigest()
        self.db.execute(
            "INSERT INTO mpr2612_release_transition VALUES(?,?,?,?,?,?,?)",
            (
                transition_digest,
                release_generation,
                from_state.value,
                to_state.value,
                reason_code,
                receipt_digest,
                payload_json,
            ),
        )

    def _state_row(self) -> sqlite3.Row:
        previous_factory = self.db.row_factory
        self.db.row_factory = sqlite3.Row
        try:
            row = self.db.execute(
                "SELECT * FROM mpr2612_release_state WHERE singleton=1"
            ).fetchone()
        finally:
            self.db.row_factory = previous_factory
        if row is None:
            raise DurableReleaseError("MPR2612_SCHEMA_NOT_INSTALLED")
        return row

    def _require_transaction(self) -> None:
        if not self.db.in_transaction:
            raise DurableReleaseError("MPR2612_CALLER_TRANSACTION_REQUIRED")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _receipt_digest(
    *,
    release_id: str,
    release_generation: int,
    previous_generation: int,
    proposal_digest: str,
    qualification_digest: str,
    reviewer_principals: tuple[str, ...],
    state: ReleaseState,
    product_state: str,
) -> str:
    payload = {
        "schema_version": MPR2612_DURABLE_SCHEMA,
        "release_id": release_id,
        "release_generation": release_generation,
        "previous_generation": previous_generation,
        "proposal_digest": proposal_digest,
        "qualification_digest": qualification_digest,
        "reviewer_principals": list(reviewer_principals),
        "state": state.value,
        "product_state": product_state,
        "live_enabled": False,
        "unrestricted_live_allowed": False,
        "automatic_scale_up_allowed": False,
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


__all__ = [
    "DurableReleaseError",
    "FinalReleaseReceipt",
    "MPR2612DurableReleaseAuthority",
    "MPR2612_DURABLE_SCHEMA",
]
