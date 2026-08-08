"""PR-2 canonical human-intervention authority.

Offline and sender-free. It turns human review evidence into a short-lived,
content-addressed, one-shot permit consumed through a caller-owned SQLite
connection. It never loads keys, signs, submits, enables live mode, or grants
execution capability.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
import re
import sqlite3

from src.operator_ack_pr143 import (
    PR143Decision,
    acknowledgement_fingerprint,
    evaluate_operator_acknowledgement,
)

SCHEMA_VERSION = "pr2.human-intervention.v1"
PERMIT_SCHEMA_VERSION = "pr2.human-intervention-permit.v1"
MAX_PERMIT_TTL_SECONDS = 15 * 60
REQUIRED_APPROVALS = 2
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class HumanInterventionError(ValueError):
    pass


class InterventionBlocked(HumanInterventionError):
    pass


class PermitConflict(HumanInterventionError):
    pass


class InterventionAction(StrEnum):
    CLEAR_SAFETY_LATCH = "clear-safety-latch"
    ACTIVATE_CONFIG = "activate-config"
    RELEASE_PROMOTION_REVIEW = "release-promotion-review"
    LIVE_CANARY_REVIEW = "live-canary-review"
    MANUAL_OVERRIDE = "manual-override"


_ACTION_TO_PR143_INTENT = {
    InterventionAction.CLEAR_SAFETY_LATCH: "manual-override",
    InterventionAction.ACTIVATE_CONFIG: "manual-override",
    InterventionAction.RELEASE_PROMOTION_REVIEW: "release-promotion",
    InterventionAction.LIVE_CANARY_REVIEW: "live-canary",
    InterventionAction.MANUAL_OVERRIDE: "manual-override",
}


@dataclass(frozen=True, slots=True)
class InterventionTarget:
    subject_type: str
    subject_id: str
    subject_hash: str
    evidence_hash: str
    release_hash: str
    config_hash: str

    def __post_init__(self) -> None:
        for field_name in ("subject_type", "subject_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise HumanInterventionError(f"{field_name} is required")
        for field_name in (
            "subject_hash",
            "evidence_hash",
            "release_hash",
            "config_hash",
        ):
            _require_sha256(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class HumanInterventionRequest:
    action: InterventionAction
    target: InterventionTarget
    requested_at_utc: str
    expires_at_utc: str
    acknowledgements: tuple[Mapping[str, object], ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise HumanInterventionError("unsupported intervention schema")
        start = _parse_utc(self.requested_at_utc)
        end = _parse_utc(self.expires_at_utc)
        if end <= start:
            raise HumanInterventionError("permit must expire after request time")
        if end - start > timedelta(seconds=MAX_PERMIT_TTL_SECONDS):
            raise HumanInterventionError("permit ttl exceeds hard maximum")
        if len(self.acknowledgements) < REQUIRED_APPROVALS:
            raise HumanInterventionError("two distinct human approvals are required")

    @property
    def request_hash(self) -> str:
        return intervention_request_hash(
            action=self.action,
            target=self.target,
            requested_at_utc=self.requested_at_utc,
            expires_at_utc=self.expires_at_utc,
        )


@dataclass(frozen=True, slots=True)
class HumanInterventionPermit:
    action: InterventionAction
    target: InterventionTarget
    requested_at_utc: str
    expires_at_utc: str
    request_hash: str
    approval_fingerprints: tuple[str, ...]
    operator_ids: tuple[str, ...]
    permit_hash: str
    execution_capability_allowed: bool = False
    live_submission_allowed: bool = False
    automatic_scale_up_allowed: bool = False
    schema_version: str = PERMIT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["action"] = self.action.value
        return payload


def intervention_request_hash(
    *,
    action: InterventionAction,
    target: InterventionTarget,
    requested_at_utc: str,
    expires_at_utc: str,
) -> str:
    return _sha256_json(
        {
            "schema_version": SCHEMA_VERSION,
            "action": action.value,
            "target": asdict(target),
            "requested_at_utc": requested_at_utc,
            "expires_at_utc": expires_at_utc,
        }
    )


def evaluate_human_intervention(
    request: HumanInterventionRequest,
    *,
    current_utc: str,
) -> HumanInterventionPermit:
    now = _parse_utc(current_utc)
    requested = _parse_utc(request.requested_at_utc)
    expires = _parse_utc(request.expires_at_utc)
    if now < requested:
        raise InterventionBlocked("PR2_REQUEST_NOT_YET_VALID")
    if now >= expires:
        raise InterventionBlocked("PR2_REQUEST_EXPIRED")

    expected_intent = _ACTION_TO_PR143_INTENT[request.action]
    fingerprints: list[str] = []
    operator_ids: list[str] = []

    for index, acknowledgement in enumerate(request.acknowledgements):
        result = evaluate_operator_acknowledgement(
            acknowledgement,
            current_utc=current_utc,
        )
        if result.decision is not PR143Decision.ACKNOWLEDGED:
            details = ",".join(result.blockers or result.warnings)
            raise InterventionBlocked(
                f"PR2_APPROVAL_{index}_BLOCKED:{details or 'not-acknowledged'}"
            )
        if acknowledgement.get("intent") != expected_intent:
            raise InterventionBlocked(f"PR2_APPROVAL_{index}_INTENT_MISMATCH")
        if acknowledgement.get("request_id") != request.request_hash:
            raise InterventionBlocked(f"PR2_APPROVAL_{index}_REQUEST_HASH_MISMATCH")
        if acknowledgement.get("evidence_bundle_hash") != request.target.evidence_hash:
            raise InterventionBlocked(f"PR2_APPROVAL_{index}_EVIDENCE_HASH_MISMATCH")
        if acknowledgement.get("policy_hash") != request.target.config_hash:
            raise InterventionBlocked(f"PR2_APPROVAL_{index}_CONFIG_HASH_MISMATCH")
        if acknowledgement.get("decision_hash") != request.target.subject_hash:
            raise InterventionBlocked(f"PR2_APPROVAL_{index}_SUBJECT_HASH_MISMATCH")

        ack_body = acknowledgement.get("acknowledgement")
        if not isinstance(ack_body, Mapping):
            raise InterventionBlocked(f"PR2_APPROVAL_{index}_ACK_OBJECT_MISSING")
        operator_id = ack_body.get("operator_id")
        if not isinstance(operator_id, str) or not operator_id.strip():
            raise InterventionBlocked(f"PR2_APPROVAL_{index}_OPERATOR_ID_MISSING")
        fingerprints.append(acknowledgement_fingerprint(acknowledgement))
        operator_ids.append(operator_id)

    if len(set(operator_ids)) != len(operator_ids):
        raise InterventionBlocked("PR2_APPROVERS_MUST_BE_DISTINCT")
    if len(set(fingerprints)) != len(fingerprints):
        raise InterventionBlocked("PR2_DUPLICATE_APPROVAL_PACKAGE")

    permit_body = {
        "schema_version": PERMIT_SCHEMA_VERSION,
        "action": request.action.value,
        "target": asdict(request.target),
        "requested_at_utc": request.requested_at_utc,
        "expires_at_utc": request.expires_at_utc,
        "request_hash": request.request_hash,
        "approval_fingerprints": sorted(fingerprints),
        "operator_ids": sorted(operator_ids),
        "execution_capability_allowed": False,
        "live_submission_allowed": False,
        "automatic_scale_up_allowed": False,
    }
    return HumanInterventionPermit(
        action=request.action,
        target=request.target,
        requested_at_utc=request.requested_at_utc,
        expires_at_utc=request.expires_at_utc,
        request_hash=request.request_hash,
        approval_fingerprints=tuple(sorted(fingerprints)),
        operator_ids=tuple(sorted(operator_ids)),
        permit_hash=_sha256_json(permit_body),
    )


class HumanInterventionLedger:
    """One-shot permit ledger over a caller-owned SQLite connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        if not isinstance(db, sqlite3.Connection):
            raise TypeError("db must be an existing sqlite3.Connection")
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS pr2_human_intervention_permits(
              permit_hash TEXT PRIMARY KEY,
              request_hash TEXT NOT NULL,
              action TEXT NOT NULL,
              subject_type TEXT NOT NULL,
              subject_id TEXT NOT NULL,
              subject_hash TEXT NOT NULL,
              evidence_hash TEXT NOT NULL,
              release_hash TEXT NOT NULL,
              config_hash TEXT NOT NULL,
              requested_at_utc TEXT NOT NULL,
              expires_at_utc TEXT NOT NULL,
              approval_fingerprints_json TEXT NOT NULL,
              operator_ids_json TEXT NOT NULL,
              consumed_at_utc TEXT,
              consume_idempotency_key TEXT UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_pr2_intervention_subject
              ON pr2_human_intervention_permits(subject_type, subject_id);
            """)

    def issue(
        self,
        request: HumanInterventionRequest,
        *,
        current_utc: str,
    ) -> HumanInterventionPermit:
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
            json.dumps(permit.approval_fingerprints, separators=(",", ":")),
            json.dumps(permit.operator_ids, separators=(",", ":")),
        )
        try:
            with self.db:
                self.db.execute(
                    """
                    INSERT INTO pr2_human_intervention_permits(
                      permit_hash,request_hash,action,subject_type,subject_id,
                      subject_hash,evidence_hash,release_hash,config_hash,
                      requested_at_utc,expires_at_utc,
                      approval_fingerprints_json,operator_ids_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    values,
                )
        except sqlite3.IntegrityError:
            existing = self.db.execute(
                "SELECT request_hash FROM pr2_human_intervention_permits "
                "WHERE permit_hash=?",
                (permit.permit_hash,),
            ).fetchone()
            if existing is None or existing[0] != permit.request_hash:
                raise PermitConflict("PR2_PERMIT_HASH_CONFLICT") from None
        return permit

    def consume(
        self,
        permit: HumanInterventionPermit,
        *,
        action: InterventionAction,
        target: InterventionTarget,
        current_utc: str,
        idempotency_key: str,
    ) -> None:
        if not idempotency_key.strip():
            raise PermitConflict("PR2_IDEMPOTENCY_KEY_REQUIRED")
        now = _parse_utc(current_utc)
        if now >= _parse_utc(permit.expires_at_utc):
            raise PermitConflict("PR2_PERMIT_EXPIRED")
        if action is not permit.action or target != permit.target:
            raise PermitConflict("PR2_PERMIT_BINDING_MISMATCH")

        with self.db:
            row = self.db.execute(
                """
                SELECT action,subject_type,subject_id,subject_hash,evidence_hash,
                       release_hash,config_hash,expires_at_utc,consumed_at_utc,
                       consume_idempotency_key
                FROM pr2_human_intervention_permits
                WHERE permit_hash=?
                """,
                (permit.permit_hash,),
            ).fetchone()
            if row is None:
                raise PermitConflict("PR2_PERMIT_NOT_ISSUED")
            if row[8] is not None:
                if row[9] == idempotency_key:
                    return
                raise PermitConflict("PR2_PERMIT_ALREADY_CONSUMED")

            expected = (
                action.value,
                target.subject_type,
                target.subject_id,
                target.subject_hash,
                target.evidence_hash,
                target.release_hash,
                target.config_hash,
            )
            if tuple(row[:7]) != expected:
                raise PermitConflict("PR2_DURABLE_BINDING_MISMATCH")
            if now >= _parse_utc(row[7]):
                raise PermitConflict("PR2_PERMIT_EXPIRED")

            cur = self.db.execute(
                """
                UPDATE pr2_human_intervention_permits
                SET consumed_at_utc=?,consume_idempotency_key=?
                WHERE permit_hash=? AND consumed_at_utc IS NULL
                """,
                (current_utc, idempotency_key, permit.permit_hash),
            )
            if cur.rowcount != 1:
                raise PermitConflict("PR2_PERMIT_CONSUME_CONFLICT")


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HumanInterventionError("timestamp must be UTC Z format")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HumanInterventionError("invalid UTC timestamp") from exc
    return parsed.astimezone(timezone.utc)


def _require_sha256(value: str, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not _SHA256_RE.fullmatch(value)
        or value == "0" * 64
    ):
        raise HumanInterventionError(
            f"{field_name} must be a non-placeholder sha256 digest"
        )
    return value


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _sha256_json(value: object) -> str:
    raw = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
