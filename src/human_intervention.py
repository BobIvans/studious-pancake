"""Authenticated-control primitives for MPR-2603.

This module is intentionally sender-free.  It owns no trading key and grants no
live capability.  Its only purpose is to bind an already-verified human review
request to a short-lived one-shot local permit that can be consumed inside the
caller's canonical SQLite transaction.

Schema installation is explicit so constructing or using the ledger never
commits or rolls back a caller-owned transaction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
import re
import sqlite3

SCHEMA_VERSION = "mpr2603.human-intervention.v1"
PERMIT_SCHEMA_VERSION = "mpr2603.human-intervention-permit.v1"
MAX_PERMIT_TTL_SECONDS = 15 * 60
REQUIRED_APPROVALS = 2
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class HumanInterventionError(ValueError):
    """Base class for human-control validation failures."""


class InterventionBlocked(HumanInterventionError):
    """The requested expansion of authority is not currently admissible."""


class PermitConflict(HumanInterventionError):
    """The durable permit state conflicts with the requested operation."""


class InterventionAction(StrEnum):
    CLEAR_SAFETY_LATCH = "clear-safety-latch"
    AUTHORIZE_PROVIDER_RECOVERY = "authorize-provider-recovery"


@dataclass(frozen=True, slots=True)
class InterventionTarget:
    subject_type: str
    subject_id: str
    subject_hash: str
    evidence_hash: str
    release_hash: str
    config_hash: str

    def __post_init__(self) -> None:
        if not self.subject_type.strip() or not self.subject_id.strip():
            raise HumanInterventionError("subject_type and subject_id are required")
        for name in ("subject_hash", "evidence_hash", "release_hash", "config_hash"):
            _require_sha256(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class VerifiedApproval:
    """Verification result produced by a real external signature backend.

    The cryptographic adapter is deliberately separate from this ledger.  The
    ledger only accepts immutable verification results and still enforces two
    independent enrolled subjects and exact request binding.
    """

    principal_id: str
    credential_id: str
    request_hash: str
    decision: str
    verified_payload_hash: str
    trust_epoch: str
    valid_from_utc: str
    expires_at_utc: str

    def __post_init__(self) -> None:
        if not self.principal_id.strip() or not self.credential_id.strip():
            raise HumanInterventionError("principal and credential are required")
        if self.decision not in {"APPROVE", "REJECT"}:
            raise HumanInterventionError("decision must be APPROVE or REJECT")
        _require_sha256(self.request_hash, "request_hash")
        _require_sha256(self.verified_payload_hash, "verified_payload_hash")
        _require_sha256(self.trust_epoch, "trust_epoch")
        _parse_utc(self.valid_from_utc)
        _parse_utc(self.expires_at_utc)


@dataclass(frozen=True, slots=True)
class HumanInterventionRequest:
    action: InterventionAction
    target: InterventionTarget
    request_id: str
    nonce: str
    requested_at_utc: str
    expires_at_utc: str
    trust_epoch: str
    approvals: tuple[VerifiedApproval, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise HumanInterventionError("unsupported intervention schema")
        if not self.request_id.strip() or not self.nonce.strip():
            raise HumanInterventionError("request_id and nonce are required")
        _require_sha256(self.trust_epoch, "trust_epoch")
        start = _parse_utc(self.requested_at_utc)
        end = _parse_utc(self.expires_at_utc)
        if end <= start:
            raise HumanInterventionError("request expiry must follow not-before")
        if end - start > timedelta(seconds=MAX_PERMIT_TTL_SECONDS):
            raise HumanInterventionError("permit ttl exceeds hard maximum")
        if len(self.approvals) < REQUIRED_APPROVALS:
            raise HumanInterventionError("two independent approvals are required")

    @property
    def request_hash(self) -> str:
        return _sha256_json(
            {
                "schema": self.schema_version,
                "action": self.action.value,
                "target": asdict(self.target),
                "request_id": self.request_id,
                "nonce": self.nonce,
                "requested_at_utc": self.requested_at_utc,
                "expires_at_utc": self.expires_at_utc,
                "trust_epoch": self.trust_epoch,
            }
        )


@dataclass(frozen=True, slots=True)
class HumanInterventionPermit:
    permit_hash: str
    request_hash: str
    action: InterventionAction
    target: InterventionTarget
    requested_at_utc: str
    expires_at_utc: str
    trust_epoch: str
    principal_ids: tuple[str, ...]
    approval_hashes: tuple[str, ...]
    schema_version: str = PERMIT_SCHEMA_VERSION


def install_human_intervention_schema(db: sqlite3.Connection) -> None:
    """Install tables without opening or completing a transaction.

    Callers must invoke this from the repository's accepted migration boundary.
    It is intentionally not called by ``HumanInterventionLedger.__init__``.
    """

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS mpr2603_human_permits(
          permit_hash TEXT PRIMARY KEY,
          request_hash TEXT NOT NULL UNIQUE,
          action TEXT NOT NULL,
          subject_type TEXT NOT NULL,
          subject_id TEXT NOT NULL,
          subject_hash TEXT NOT NULL,
          evidence_hash TEXT NOT NULL,
          release_hash TEXT NOT NULL,
          config_hash TEXT NOT NULL,
          requested_at_utc TEXT NOT NULL,
          expires_at_utc TEXT NOT NULL,
          trust_epoch TEXT NOT NULL,
          principal_ids_json TEXT NOT NULL,
          approval_hashes_json TEXT NOT NULL,
          consumed_at_utc TEXT,
          consume_idempotency_key TEXT UNIQUE,
          consume_command_hash TEXT
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_mpr2603_permit_target "
        "ON mpr2603_human_permits(subject_type,subject_id)"
    )


class HumanInterventionLedger:
    """Caller-owned permit ledger.

    No method commits, rolls back, executes schema scripts, or opens its own
    connection.  This is required so permit consumption can linearize with the
    exact latch mutation and recovery intent in one outer transaction.
    """

    def __init__(self, db: sqlite3.Connection) -> None:
        if not isinstance(db, sqlite3.Connection):
            raise TypeError("db must be an existing sqlite3.Connection")
        self.db = db

    def issue(self, request: HumanInterventionRequest, *, current_utc: str) -> HumanInterventionPermit:
        permit = evaluate_human_intervention(request, current_utc=current_utc)
        values = (
            permit.permit_hash,
            permit.request_hash,
            permit.action.value,
            permit.target.subject_type,
            permit.target.subject_id,
            permit.target.subject_hash,
            permit.target.evidence_hash,
            permit.target.release_hash,
            permit.target.config_hash,
            permit.requested_at_utc,
            permit.expires_at_utc,
            permit.trust_epoch,
            json.dumps(permit.principal_ids, separators=(",", ":")),
            json.dumps(permit.approval_hashes, separators=(",", ":")),
        )
        try:
            self.db.execute(
                """
                INSERT INTO mpr2603_human_permits(
                  permit_hash,request_hash,action,subject_type,subject_id,
                  subject_hash,evidence_hash,release_hash,config_hash,
                  requested_at_utc,expires_at_utc,trust_epoch,
                  principal_ids_json,approval_hashes_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                values,
            )
        except sqlite3.IntegrityError as exc:
            row = self.db.execute(
                "SELECT permit_hash FROM mpr2603_human_permits WHERE request_hash=?",
                (permit.request_hash,),
            ).fetchone()
            if row is None or row[0] != permit.permit_hash:
                raise PermitConflict("MPR2603_PERMIT_ISSUE_CONFLICT") from exc
        return permit

    def consume_in_transaction(
        self,
        permit: HumanInterventionPermit,
        *,
        action: InterventionAction,
        target: InterventionTarget,
        current_utc: str,
        current_trust_epoch: str,
        idempotency_key: str,
        command_hash: str,
    ) -> bool:
        """Consume a permit without ending the caller's transaction.

        Returns ``True`` only for an exact replay of an already committed
        semantic command.  All durable binding is checked *before* the replay
        return, closing the consumed-row early-return weakness from B02.
        """

        if not idempotency_key.strip():
            raise PermitConflict("MPR2603_IDEMPOTENCY_KEY_REQUIRED")
        _require_sha256(command_hash, "command_hash")
        _require_sha256(current_trust_epoch, "current_trust_epoch")
        now = _parse_utc(current_utc)
        if now < _parse_utc(permit.requested_at_utc):
            raise PermitConflict("MPR2603_PERMIT_NOT_YET_VALID")
        if now >= _parse_utc(permit.expires_at_utc):
            raise PermitConflict("MPR2603_PERMIT_EXPIRED")
        if current_trust_epoch != permit.trust_epoch:
            raise PermitConflict("MPR2603_TRUST_EPOCH_CHANGED")
        if action is not permit.action or target != permit.target:
            raise PermitConflict("MPR2603_PERMIT_BINDING_MISMATCH")

        row = self.db.execute(
            """
            SELECT request_hash,action,subject_type,subject_id,subject_hash,
                   evidence_hash,release_hash,config_hash,requested_at_utc,
                   expires_at_utc,trust_epoch,consumed_at_utc,
                   consume_idempotency_key,consume_command_hash
            FROM mpr2603_human_permits WHERE permit_hash=?
            """,
            (permit.permit_hash,),
        ).fetchone()
        if row is None:
            raise PermitConflict("MPR2603_PERMIT_NOT_ISSUED")

        expected = (
            permit.request_hash,
            action.value,
            target.subject_type,
            target.subject_id,
            target.subject_hash,
            target.evidence_hash,
            target.release_hash,
            target.config_hash,
            permit.requested_at_utc,
            permit.expires_at_utc,
            current_trust_epoch,
        )
        if tuple(row[:11]) != expected:
            raise PermitConflict("MPR2603_DURABLE_BINDING_MISMATCH")
        if now < _parse_utc(str(row[8])):
            raise PermitConflict("MPR2603_PERMIT_NOT_YET_VALID")
        if now >= _parse_utc(str(row[9])):
            raise PermitConflict("MPR2603_PERMIT_EXPIRED")

        if row[11] is not None:
            if row[12] == idempotency_key and row[13] == command_hash:
                return True
            raise PermitConflict("MPR2603_PERMIT_ALREADY_CONSUMED")

        cur = self.db.execute(
            """
            UPDATE mpr2603_human_permits
            SET consumed_at_utc=?,consume_idempotency_key=?,consume_command_hash=?
            WHERE permit_hash=? AND consumed_at_utc IS NULL
            """,
            (current_utc, idempotency_key, command_hash, permit.permit_hash),
        )
        if cur.rowcount != 1:
            raise PermitConflict("MPR2603_PERMIT_CONSUME_CONFLICT")
        return False


def evaluate_human_intervention(
    request: HumanInterventionRequest, *, current_utc: str
) -> HumanInterventionPermit:
    now = _parse_utc(current_utc)
    start = _parse_utc(request.requested_at_utc)
    end = _parse_utc(request.expires_at_utc)
    if now < start:
        raise InterventionBlocked("MPR2603_REQUEST_NOT_YET_VALID")
    if now >= end:
        raise InterventionBlocked("MPR2603_REQUEST_EXPIRED")

    principals: list[str] = []
    approval_hashes: list[str] = []
    for approval in request.approvals:
        if approval.decision == "REJECT":
            raise InterventionBlocked("MPR2603_REQUEST_REJECTED")
        if approval.request_hash != request.request_hash:
            raise InterventionBlocked("MPR2603_APPROVAL_REQUEST_MISMATCH")
        if approval.trust_epoch != request.trust_epoch:
            raise InterventionBlocked("MPR2603_APPROVAL_TRUST_EPOCH_MISMATCH")
        if now < _parse_utc(approval.valid_from_utc) or now >= _parse_utc(approval.expires_at_utc):
            raise InterventionBlocked("MPR2603_APPROVAL_OUTSIDE_VALIDITY")
        principals.append(approval.principal_id)
        approval_hashes.append(approval.verified_payload_hash)

    if len(set(principals)) < REQUIRED_APPROVALS:
        raise InterventionBlocked("MPR2603_APPROVERS_MUST_BE_INDEPENDENT")

    body = {
        "schema": PERMIT_SCHEMA_VERSION,
        "request_hash": request.request_hash,
        "action": request.action.value,
        "target": asdict(request.target),
        "requested_at_utc": request.requested_at_utc,
        "expires_at_utc": request.expires_at_utc,
        "trust_epoch": request.trust_epoch,
        "principal_ids": sorted(principals),
        "approval_hashes": sorted(approval_hashes),
        "execution_capability_allowed": False,
        "live_submission_allowed": False,
    }
    return HumanInterventionPermit(
        permit_hash=_sha256_json(body),
        request_hash=request.request_hash,
        action=request.action,
        target=request.target,
        requested_at_utc=request.requested_at_utc,
        expires_at_utc=request.expires_at_utc,
        trust_epoch=request.trust_epoch,
        principal_ids=tuple(sorted(principals)),
        approval_hashes=tuple(sorted(approval_hashes)),
    )


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HumanInterventionError("timestamp must be UTC Z format")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HumanInterventionError("invalid UTC timestamp") from exc
    return parsed.astimezone(timezone.utc)


def _require_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value) or value == "0" * 64:
        raise HumanInterventionError(f"{field_name} must be a non-placeholder sha256 digest")
    return value


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
            default=lambda item: item.value if isinstance(item, StrEnum) else asdict(item),
        ).encode("utf-8")
    ).hexdigest()
