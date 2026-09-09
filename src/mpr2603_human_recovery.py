"""Atomic human-recovery consumer for MPR-2603.

This is the supported local mutation boundary for widening authority.  Permit
consumption, exact latch CAS, immutable receipt, and recovery intent commit in a
single SQLite transaction owned by the canonical control-plane connection.

No network request, signing operation, provider health assertion, or live-mode
change occurs here.  Recovery remains pending until the existing provider
runtime independently produces admissible evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3
from uuid import uuid4

from src.human_intervention import (
    HumanInterventionLedger,
    HumanInterventionPermit,
    InterventionAction,
    InterventionTarget,
    PermitConflict,
    install_human_intervention_schema,
)


class HumanRecoveryError(RuntimeError):
    """Base MPR-2603 recovery-boundary error."""


class RecoveryTargetConflict(HumanRecoveryError):
    """The requested latch is stale, inactive, or changed."""


@dataclass(frozen=True, slots=True)
class RecoveryReceipt:
    receipt_id: str
    command_hash: str
    permit_hash: str
    latch_id: str
    latch_evidence_hash: str
    recovery_intent_id: str
    committed_at_utc: str
    replayed: bool = False


def install_human_recovery_schema(db: sqlite3.Connection) -> None:
    """Explicit migration helper; never called implicitly by request handling."""

    install_human_intervention_schema(db)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS mpr2603_recovery_intents(
          intent_id TEXT PRIMARY KEY,
          permit_hash TEXT NOT NULL UNIQUE,
          latch_id TEXT NOT NULL,
          latch_evidence_hash TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('recovery_pending','completed','blocked')),
          created_at_utc TEXT NOT NULL,
          attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS mpr2603_intervention_receipts(
          receipt_id TEXT PRIMARY KEY,
          command_hash TEXT NOT NULL UNIQUE,
          permit_hash TEXT NOT NULL UNIQUE,
          latch_id TEXT NOT NULL,
          latch_evidence_hash TEXT NOT NULL,
          recovery_intent_id TEXT NOT NULL UNIQUE,
          committed_at_utc TEXT NOT NULL
        )
        """
    )


def apply_clear_and_authorize_recovery(
    db: sqlite3.Connection,
    *,
    permit: HumanInterventionPermit,
    target: InterventionTarget,
    current_utc: str,
    current_trust_epoch: str,
    idempotency_key: str,
) -> RecoveryReceipt:
    """Consume one permit and clear one exact latch atomically.

    ``target.subject_id`` is the exact PR-195 latch id and
    ``target.subject_hash`` must equal its current evidence hash.  This provides
    occurrence-style ABA protection for the current schema: reopening the same
    named latch with different evidence invalidates the old authorization.
    """

    if permit.action is not InterventionAction.CLEAR_SAFETY_LATCH:
        raise PermitConflict("MPR2603_CLEAR_REQUIRES_CLEAR_ACTION")
    if target.subject_type != "pr195-latch":
        raise RecoveryTargetConflict("MPR2603_UNSUPPORTED_TARGET_TYPE")

    command_hash = _command_hash(
        permit_hash=permit.permit_hash,
        target=target,
        trust_epoch=current_trust_epoch,
        idempotency_key=idempotency_key,
    )
    ledger = HumanInterventionLedger(db)

    db.execute("BEGIN IMMEDIATE")
    try:
        # Exact duplicate receipt is checked only after validating the permit's
        # durable semantic binding through consume_in_transaction.
        replayed = ledger.consume_in_transaction(
            permit,
            action=InterventionAction.CLEAR_SAFETY_LATCH,
            target=target,
            current_utc=current_utc,
            current_trust_epoch=current_trust_epoch,
            idempotency_key=idempotency_key,
            command_hash=command_hash,
        )
        if replayed:
            row = db.execute(
                "SELECT * FROM mpr2603_intervention_receipts WHERE command_hash=?",
                (command_hash,),
            ).fetchone()
            if row is None:
                raise RecoveryTargetConflict("MPR2603_REPLAY_RECEIPT_MISSING")
            db.execute("COMMIT")
            return RecoveryReceipt(
                receipt_id=str(row[0]),
                command_hash=str(row[1]),
                permit_hash=str(row[2]),
                latch_id=str(row[3]),
                latch_evidence_hash=str(row[4]),
                recovery_intent_id=str(row[5]),
                committed_at_utc=str(row[6]),
                replayed=True,
            )

        latch = db.execute(
            "SELECT active,evidence_hash FROM pr195_latches WHERE latch_id=?",
            (target.subject_id,),
        ).fetchone()
        if latch is None:
            raise RecoveryTargetConflict("MPR2603_LATCH_NOT_FOUND")
        if int(latch[0]) != 1:
            raise RecoveryTargetConflict("MPR2603_LATCH_NOT_ACTIVE")
        if str(latch[1]) != target.subject_hash:
            raise RecoveryTargetConflict("MPR2603_LATCH_OCCURRENCE_CHANGED")

        # Do not call CanonicalControlPlaneStore.clear_latch(): that method owns
        # its own sqlite context manager.  The supported MPR-2603 consumer keeps
        # permit + mutation + receipt/outbox under this one transaction.
        cur = db.execute(
            """
            UPDATE pr195_latches
            SET active=0,acknowledged_by=?,clear_approval_hash=?
            WHERE latch_id=? AND active=1 AND evidence_hash=?
            """,
            (
                "mpr2603:" + ",".join(permit.principal_ids),
                permit.permit_hash,
                target.subject_id,
                target.subject_hash,
            ),
        )
        if cur.rowcount != 1:
            raise RecoveryTargetConflict("MPR2603_LATCH_CAS_CONFLICT")

        intent_id = "recovery-" + uuid4().hex
        receipt_id = "receipt-" + uuid4().hex
        db.execute(
            """
            INSERT INTO mpr2603_recovery_intents(
              intent_id,permit_hash,latch_id,latch_evidence_hash,status,created_at_utc
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                intent_id,
                permit.permit_hash,
                target.subject_id,
                target.subject_hash,
                "recovery_pending",
                current_utc,
            ),
        )
        db.execute(
            """
            INSERT INTO mpr2603_intervention_receipts(
              receipt_id,command_hash,permit_hash,latch_id,latch_evidence_hash,
              recovery_intent_id,committed_at_utc
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                receipt_id,
                command_hash,
                permit.permit_hash,
                target.subject_id,
                target.subject_hash,
                intent_id,
                current_utc,
            ),
        )
    except BaseException:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")

    return RecoveryReceipt(
        receipt_id=receipt_id,
        command_hash=command_hash,
        permit_hash=permit.permit_hash,
        latch_id=target.subject_id,
        latch_evidence_hash=target.subject_hash,
        recovery_intent_id=intent_id,
        committed_at_utc=current_utc,
    )


def recovery_pending(db: sqlite3.Connection, intent_id: str) -> bool:
    row = db.execute(
        "SELECT status FROM mpr2603_recovery_intents WHERE intent_id=?",
        (intent_id,),
    ).fetchone()
    return row is not None and str(row[0]) == "recovery_pending"


def _command_hash(
    *,
    permit_hash: str,
    target: InterventionTarget,
    trust_epoch: str,
    idempotency_key: str,
) -> str:
    payload = {
        "schema": "mpr2603.atomic-clear.v1",
        "permit_hash": permit_hash,
        "target": {
            "subject_type": target.subject_type,
            "subject_id": target.subject_id,
            "subject_hash": target.subject_hash,
            "evidence_hash": target.evidence_hash,
            "release_hash": target.release_hash,
            "config_hash": target.config_hash,
        },
        "trust_epoch": trust_epoch,
        "idempotency_key": idempotency_key,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
