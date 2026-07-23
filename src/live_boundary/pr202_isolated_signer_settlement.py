"""PR-202 isolated signer, reviewed permit and finalized settlement evidence.

This module is intentionally default-off and sender-free. It does not load
wallets, private keys, network clients, signers or senders. It provides
fail-closed evidence primitives for the PR-202 vertical: isolated signer
boundary evidence, short-lived reviewed permits, durable one-time permit
consumption, one selected transport intent per attempt and settlement decisions
that require finalized rooted reconciliation rather than transport ACKs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

PR202_SCHEMA_VERSION = "pr202.isolated-signer-settlement.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_BLOCKHASH_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,88}$")


class PR202EvidenceError(ValueError):
    """Fail-closed PR-202 validation error with a stable reason code."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(message or reason_code)


class TransportKind(StrEnum):
    RPC_SINGLE = "rpc_single"
    JITO_SINGLE = "jito_single"
    JITO_BUNDLE = "jito_bundle"


class AckStatus(StrEnum):
    NOT_SENT = "not_sent"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"


class SettlementStatus(StrEnum):
    FINALIZED = "finalized"
    LOCKED_MANUAL = "locked_manual"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class IsolatedSignerBoundaryEvidence:
    signer_service_id: str
    image_digest: str
    release_hash: str
    separate_process: bool
    separate_container: bool
    narrow_ipc: bool
    key_never_enters_main_runtime: bool
    key_not_in_logs: bool
    key_not_in_files: bool
    deny_by_default_egress: bool
    no_general_network_access: bool
    no_unreviewed_signing_method: bool
    secret_rotation_drill_hash: str
    compromise_drill_hash: str
    break_glass_policy_hash: str
    operator_break_glass_enabled: bool = False
    live_enabled: bool = False

    def __post_init__(self) -> None:
        _require_safe_id(self.signer_service_id, "signer_service_id")
        _require_image_digest(self.image_digest, "image_digest")
        _require_sha256(self.release_hash, "release_hash")
        _require_sha256(self.secret_rotation_drill_hash, "secret_rotation_drill_hash")
        _require_sha256(self.compromise_drill_hash, "compromise_drill_hash")
        _require_sha256(self.break_glass_policy_hash, "break_glass_policy_hash")
        if self.live_enabled:
            raise PR202EvidenceError("PR202_LIVE_MUST_REMAIN_DISABLED")

    def evaluate(self) -> dict[str, object]:
        blockers: list[str] = []
        checks = {
            "separate_process": self.separate_process,
            "separate_container": self.separate_container,
            "narrow_ipc": self.narrow_ipc,
            "key_never_enters_main_runtime": self.key_never_enters_main_runtime,
            "key_not_in_logs": self.key_not_in_logs,
            "key_not_in_files": self.key_not_in_files,
            "deny_by_default_egress": self.deny_by_default_egress,
            "no_general_network_access": self.no_general_network_access,
            "no_unreviewed_signing_method": self.no_unreviewed_signing_method,
        }
        for name, ok in checks.items():
            if not ok:
                blockers.append(f"PR202_SIGNER_BOUNDARY_FAILED:{name}")
        if self.operator_break_glass_enabled:
            blockers.append("PR202_OPERATOR_BREAK_GLASS_ENABLED")

        return {
            "schema_version": PR202_SCHEMA_VERSION,
            "signer_service_id": self.signer_service_id,
            "signer_boundary_healthy": not blockers,
            "live_enabled": False,
            "signer_reachable_from_main_runtime": False,
            "general_network_access": False,
            "unreviewed_signing_method": False,
            "blockers": tuple(blockers),
            "evidence_hash": _sha256_json(
                {
                    "signer_service_id": self.signer_service_id,
                    "image_digest": self.image_digest,
                    "release_hash": self.release_hash,
                    "secret_rotation": self.secret_rotation_drill_hash,
                    "compromise": self.compromise_drill_hash,
                    "break_glass": self.break_glass_policy_hash,
                    "checks": checks,
                }
            ),
        }


@dataclass(frozen=True, slots=True)
class ReviewedPermit:
    permit_id: str
    release_hash: str
    config_hash: str
    policy_hash: str
    attempt_id: str
    plan_hash: str
    message_hash: str
    blockhash: str
    transport: TransportKind
    tip_lamports: int
    risk_budget_hash: str
    boot_generation: int
    issued_at_ms: int
    expires_at_ms: int
    signer_service_id: str
    reviewer_hash: str
    live_enabled: bool = False

    def __post_init__(self) -> None:
        _require_safe_id(self.permit_id, "permit_id")
        _require_sha256(self.release_hash, "release_hash")
        _require_sha256(self.config_hash, "config_hash")
        _require_sha256(self.policy_hash, "policy_hash")
        _require_safe_id(self.attempt_id, "attempt_id")
        _require_sha256(self.plan_hash, "plan_hash")
        _require_sha256(self.message_hash, "message_hash")
        _require_blockhash(self.blockhash, "blockhash")
        _require_nonnegative_int(self.tip_lamports, "tip_lamports")
        _require_sha256(self.risk_budget_hash, "risk_budget_hash")
        _require_positive_int(self.boot_generation, "boot_generation")
        _require_nonnegative_int(self.issued_at_ms, "issued_at_ms")
        _require_positive_int(self.expires_at_ms, "expires_at_ms")
        _require_safe_id(self.signer_service_id, "signer_service_id")
        _require_sha256(self.reviewer_hash, "reviewer_hash")
        if self.expires_at_ms <= self.issued_at_ms:
            raise PR202EvidenceError("PR202_PERMIT_EXPIRY_NOT_AFTER_ISSUE")
        if self.expires_at_ms - self.issued_at_ms > 120_000:
            raise PR202EvidenceError("PR202_PERMIT_TTL_TOO_LONG")
        if self.live_enabled:
            raise PR202EvidenceError("PR202_LIVE_MUST_REMAIN_DISABLED")

    @property
    def permit_hash(self) -> str:
        return _sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": PR202_SCHEMA_VERSION,
            "permit_id": self.permit_id,
            "release_hash": self.release_hash,
            "config_hash": self.config_hash,
            "policy_hash": self.policy_hash,
            "attempt_id": self.attempt_id,
            "plan_hash": self.plan_hash,
            "message_hash": self.message_hash,
            "blockhash": self.blockhash,
            "transport": self.transport.value,
            "tip_lamports": self.tip_lamports,
            "risk_budget_hash": self.risk_budget_hash,
            "boot_generation": self.boot_generation,
            "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "signer_service_id": self.signer_service_id,
            "reviewer_hash": self.reviewer_hash,
            "live_enabled": False,
        }


@dataclass(frozen=True, slots=True)
class PermitUseRequest:
    permit: ReviewedPermit
    message_hash: str
    blockhash: str
    transport: TransportKind
    tip_lamports: int
    boot_generation: int
    now_ms: int

    def __post_init__(self) -> None:
        _require_sha256(self.message_hash, "message_hash")
        _require_blockhash(self.blockhash, "blockhash")
        _require_nonnegative_int(self.tip_lamports, "tip_lamports")
        _require_positive_int(self.boot_generation, "boot_generation")
        _require_nonnegative_int(self.now_ms, "now_ms")

    def validate_binding(self) -> None:
        if self.now_ms > self.permit.expires_at_ms:
            raise PR202EvidenceError("PR202_PERMIT_EXPIRED")
        if self.boot_generation != self.permit.boot_generation:
            raise PR202EvidenceError("PR202_BOOT_GENERATION_DRIFT")
        if self.message_hash != self.permit.message_hash:
            raise PR202EvidenceError("PR202_MESSAGE_HASH_MISMATCH")
        if self.blockhash != self.permit.blockhash:
            raise PR202EvidenceError("PR202_BLOCKHASH_MISMATCH")
        if self.transport != self.permit.transport:
            raise PR202EvidenceError("PR202_TRANSPORT_MISMATCH")
        if self.tip_lamports != self.permit.tip_lamports:
            raise PR202EvidenceError("PR202_TIP_MISMATCH")


@dataclass(frozen=True, slots=True)
class PermitConsumption:
    permit_id: str
    permit_hash: str
    attempt_id: str
    message_hash: str
    consumed_at_ms: int
    consumption_id: str


@dataclass(frozen=True, slots=True)
class SubmissionIntent:
    attempt_id: str
    permit_id: str
    message_hash: str
    transport: TransportKind
    tip_lamports: int
    intent_hash: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class TransportAck:
    attempt_id: str
    message_hash: str
    transport: TransportKind
    status: AckStatus
    ack_hash: str
    accepted_at_ms: int
    realized_pnl_lamports: int = 0

    def __post_init__(self) -> None:
        _require_safe_id(self.attempt_id, "attempt_id")
        _require_sha256(self.message_hash, "message_hash")
        _require_sha256(self.ack_hash, "ack_hash")
        _require_nonnegative_int(self.accepted_at_ms, "accepted_at_ms")
        if self.realized_pnl_lamports != 0:
            raise PR202EvidenceError("PR202_ACK_CANNOT_SET_REALIZED_PNL")


class SQLitePermitAuthority:
    """Durable permit-consumption and submission-intent authority.

    This store is intentionally not a sender. It records one reviewed permit
    consumption and one selected transport intent so crash recovery cannot blind
    resend, switch transports or reuse an already-consumed permit.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._db_path, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA trusted_schema=OFF")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS permit_consumptions ("
            "permit_id TEXT PRIMARY KEY, "
            "permit_hash TEXT NOT NULL, "
            "attempt_id TEXT NOT NULL UNIQUE, "
            "message_hash TEXT NOT NULL, "
            "consumed_at_ms INTEGER NOT NULL, "
            "consumption_id TEXT NOT NULL)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS submission_intents ("
            "attempt_id TEXT PRIMARY KEY, "
            "permit_id TEXT NOT NULL, "
            "message_hash TEXT NOT NULL, "
            "transport TEXT NOT NULL, "
            "tip_lamports INTEGER NOT NULL, "
            "intent_hash TEXT NOT NULL, "
            "created_at_ms INTEGER NOT NULL)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS transport_acks ("
            "attempt_id TEXT PRIMARY KEY, "
            "message_hash TEXT NOT NULL, "
            "transport TEXT NOT NULL, "
            "status TEXT NOT NULL, "
            "ack_hash TEXT NOT NULL, "
            "accepted_at_ms INTEGER NOT NULL)"
        )

    def consume_permit(self, request: PermitUseRequest) -> PermitConsumption:
        request.validate_binding()
        permit = request.permit
        permit_hash = permit.permit_hash
        consumption_id = _sha256_json(
            {
                "permit_id": permit.permit_id,
                "permit_hash": permit_hash,
                "attempt_id": permit.attempt_id,
                "message_hash": permit.message_hash,
                "consumed_at_ms": request.now_ms,
            }
        )

        self._begin()
        try:
            existing = self._connection.execute(
                "SELECT permit_id FROM permit_consumptions WHERE permit_id=?",
                (permit.permit_id,),
            ).fetchone()
            if existing is not None:
                raise PR202EvidenceError("PR202_PERMIT_ALREADY_CONSUMED")

            attempt_existing = self._connection.execute(
                "SELECT permit_id FROM permit_consumptions WHERE attempt_id=?",
                (permit.attempt_id,),
            ).fetchone()
            if attempt_existing is not None:
                raise PR202EvidenceError("PR202_ATTEMPT_ALREADY_HAS_PERMIT")

            self._connection.execute(
                "INSERT INTO permit_consumptions("
                "permit_id, permit_hash, attempt_id, message_hash, "
                "consumed_at_ms, consumption_id) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    permit.permit_id,
                    permit_hash,
                    permit.attempt_id,
                    permit.message_hash,
                    request.now_ms,
                    consumption_id,
                ),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

        return PermitConsumption(
            permit_id=permit.permit_id,
            permit_hash=permit_hash,
            attempt_id=permit.attempt_id,
            message_hash=permit.message_hash,
            consumed_at_ms=request.now_ms,
            consumption_id=consumption_id,
        )

    def record_submission_intent(
        self,
        *,
        attempt_id: str,
        permit_id: str,
        message_hash: str,
        transport: TransportKind,
        tip_lamports: int,
        created_at_ms: int,
    ) -> SubmissionIntent:
        _require_safe_id(attempt_id, "attempt_id")
        _require_safe_id(permit_id, "permit_id")
        _require_sha256(message_hash, "message_hash")
        _require_nonnegative_int(tip_lamports, "tip_lamports")
        _require_nonnegative_int(created_at_ms, "created_at_ms")
        intent_hash = _sha256_json(
            {
                "attempt_id": attempt_id,
                "permit_id": permit_id,
                "message_hash": message_hash,
                "transport": transport.value,
                "tip_lamports": tip_lamports,
                "created_at_ms": created_at_ms,
            }
        )

        self._begin()
        try:
            row = self._connection.execute(
                "SELECT permit_id, message_hash, transport, tip_lamports, "
                "intent_hash, created_at_ms FROM submission_intents "
                "WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is not None:
                stored = SubmissionIntent(
                    attempt_id=attempt_id,
                    permit_id=str(row[0]),
                    message_hash=str(row[1]),
                    transport=TransportKind(str(row[2])),
                    tip_lamports=_strict_int(row[3], "tip_lamports"),
                    intent_hash=str(row[4]),
                    created_at_ms=_strict_int(row[5], "created_at_ms"),
                )
                if (
                    stored.permit_id != permit_id
                    or stored.message_hash != message_hash
                    or stored.transport != transport
                    or stored.tip_lamports != tip_lamports
                ):
                    raise PR202EvidenceError(
                        "PR202_TRANSPORT_FALLBACK_OR_RESEND_REJECTED"
                    )
                self._connection.commit()
                return stored

            consumed = self._connection.execute(
                "SELECT permit_id, message_hash FROM permit_consumptions "
                "WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if consumed is None:
                raise PR202EvidenceError("PR202_INTENT_WITHOUT_CONSUMED_PERMIT")
            if str(consumed[0]) != permit_id or str(consumed[1]) != message_hash:
                raise PR202EvidenceError("PR202_INTENT_PERMIT_BINDING_MISMATCH")

            self._connection.execute(
                "INSERT INTO submission_intents("
                "attempt_id, permit_id, message_hash, transport, tip_lamports, "
                "intent_hash, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt_id,
                    permit_id,
                    message_hash,
                    transport.value,
                    tip_lamports,
                    intent_hash,
                    created_at_ms,
                ),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

        return SubmissionIntent(
            attempt_id=attempt_id,
            permit_id=permit_id,
            message_hash=message_hash,
            transport=transport,
            tip_lamports=tip_lamports,
            intent_hash=intent_hash,
            created_at_ms=created_at_ms,
        )

    def record_transport_ack(self, ack: TransportAck) -> TransportAck:
        self._begin()
        try:
            intent = self._connection.execute(
                "SELECT message_hash, transport FROM submission_intents "
                "WHERE attempt_id=?",
                (ack.attempt_id,),
            ).fetchone()
            if intent is None:
                raise PR202EvidenceError("PR202_ACK_WITHOUT_SUBMISSION_INTENT")
            if (
                str(intent[0]) != ack.message_hash
                or str(intent[1]) != ack.transport.value
            ):
                raise PR202EvidenceError("PR202_ACK_INTENT_MISMATCH")

            existing = self._connection.execute(
                "SELECT message_hash, transport, status, ack_hash, accepted_at_ms "
                "FROM transport_acks WHERE attempt_id=?",
                (ack.attempt_id,),
            ).fetchone()
            if existing is not None:
                stored = TransportAck(
                    attempt_id=ack.attempt_id,
                    message_hash=str(existing[0]),
                    transport=TransportKind(str(existing[1])),
                    status=AckStatus(str(existing[2])),
                    ack_hash=str(existing[3]),
                    accepted_at_ms=_strict_int(existing[4], "accepted_at_ms"),
                )
                if stored != ack:
                    raise PR202EvidenceError("PR202_ACK_ALREADY_RECORDED")
                self._connection.commit()
                return stored

            self._connection.execute(
                "INSERT INTO transport_acks("
                "attempt_id, message_hash, transport, status, ack_hash, "
                "accepted_at_ms) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ack.attempt_id,
                    ack.message_hash,
                    ack.transport.value,
                    ack.status.value,
                    ack.ack_hash,
                    ack.accepted_at_ms,
                ),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return ack

    def close(self) -> None:
        self._connection.close()

    def _begin(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")


@dataclass(frozen=True, slots=True)
class SettlementEvidence:
    attempt_id: str
    message_hash: str
    selected_transport: TransportKind
    ack_status: AckStatus
    signature_hash: str
    signature_finalized: bool
    transaction_meta_hash: str
    native_balance_delta_hash: str
    token_balance_delta_hash: str
    repayment_verified: bool
    minimum_rooted_slot: int
    observed_rooted_slot: int
    ambiguous_transport: bool
    accounting_hash: str
    live_enabled: bool = False

    def __post_init__(self) -> None:
        _require_safe_id(self.attempt_id, "attempt_id")
        _require_sha256(self.message_hash, "message_hash")
        _require_sha256(self.signature_hash, "signature_hash")
        _require_sha256(self.transaction_meta_hash, "transaction_meta_hash")
        _require_sha256(self.native_balance_delta_hash, "native_balance_delta_hash")
        _require_sha256(self.token_balance_delta_hash, "token_balance_delta_hash")
        _require_nonnegative_int(self.minimum_rooted_slot, "minimum_rooted_slot")
        _require_nonnegative_int(self.observed_rooted_slot, "observed_rooted_slot")
        _require_sha256(self.accounting_hash, "accounting_hash")
        if self.live_enabled:
            raise PR202EvidenceError("PR202_LIVE_MUST_REMAIN_DISABLED")

    def evaluate(self) -> dict[str, object]:
        blockers: list[str] = []
        if self.ack_status != AckStatus.ACCEPTED:
            blockers.append("PR202_TRANSPORT_NOT_ACCEPTED")
        if self.ambiguous_transport:
            blockers.append("PR202_AMBIGUOUS_TRANSPORT_MANUAL_LOCK")
        if not self.signature_finalized:
            blockers.append("PR202_SIGNATURE_NOT_FINALIZED")
        if self.observed_rooted_slot < self.minimum_rooted_slot:
            blockers.append("PR202_ROOTED_SLOT_BELOW_MINIMUM")
        if not self.repayment_verified:
            blockers.append("PR202_REPAYMENT_NOT_VERIFIED")

        finalized = not blockers
        status = (
            SettlementStatus.FINALIZED
            if finalized
            else SettlementStatus.LOCKED_MANUAL
        )
        return {
            "schema_version": PR202_SCHEMA_VERSION,
            "attempt_id": self.attempt_id,
            "status": status.value,
            "finalized": finalized,
            "realized_pnl_allowed": finalized,
            "ack_counts_as_realized_pnl": False,
            "manual_review_required": not finalized,
            "selected_transport": self.selected_transport.value,
            "blockers": tuple(blockers),
            "settlement_hash": _sha256_json(
                {
                    "attempt_id": self.attempt_id,
                    "message_hash": self.message_hash,
                    "signature_hash": self.signature_hash,
                    "transaction_meta_hash": self.transaction_meta_hash,
                    "native_balance_delta_hash": self.native_balance_delta_hash,
                    "token_balance_delta_hash": self.token_balance_delta_hash,
                    "repayment_verified": self.repayment_verified,
                    "minimum_rooted_slot": self.minimum_rooted_slot,
                    "observed_rooted_slot": self.observed_rooted_slot,
                    "accounting_hash": self.accounting_hash,
                }
            ),
        }


def pr202_readiness_report(
    *,
    signer_boundary: IsolatedSignerBoundaryEvidence,
    permit_consumption: PermitConsumption,
    submission_intent: SubmissionIntent,
    settlement: SettlementEvidence,
) -> dict[str, object]:
    signer = signer_boundary.evaluate()
    settlement_result = settlement.evaluate()
    blockers: list[str] = []

    if not signer["signer_boundary_healthy"]:
        blockers.extend(str(item) for item in signer["blockers"])
    if permit_consumption.attempt_id != submission_intent.attempt_id:
        blockers.append("PR202_PERMIT_INTENT_ATTEMPT_MISMATCH")
    if permit_consumption.message_hash != submission_intent.message_hash:
        blockers.append("PR202_PERMIT_INTENT_MESSAGE_MISMATCH")
    if submission_intent.attempt_id != settlement.attempt_id:
        blockers.append("PR202_INTENT_SETTLEMENT_ATTEMPT_MISMATCH")
    if submission_intent.message_hash != settlement.message_hash:
        blockers.append("PR202_INTENT_SETTLEMENT_MESSAGE_MISMATCH")

    return {
        "schema_version": PR202_SCHEMA_VERSION,
        "ready_for_live": False,
        "live_enabled": False,
        "signer_reachable": False,
        "sender_reachable": False,
        "submission_allowed": False,
        "single_transport": submission_intent.transport.value,
        "permit_consumed_once": True,
        "finalized_settlement": bool(settlement_result["finalized"]),
        "manual_review_required": bool(settlement_result["manual_review_required"]),
        "blockers": tuple(blockers),
        "report_hash": _sha256_json(
            {
                "signer": signer["evidence_hash"],
                "consumption": permit_consumption.consumption_id,
                "intent": submission_intent.intent_hash,
                "settlement": settlement_result["settlement_hash"],
                "blockers": blockers,
            }
        ),
    }


def _sha256_json(payload: Mapping[str, object]) -> str:
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(rendered).hexdigest()


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise PR202EvidenceError(f"PR202_INVALID_SHA256:{field_name}")


def _require_image_digest(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or "@sha256:" not in value
        or not _SHA256_RE.fullmatch(value.rsplit("@sha256:", 1)[1])
    ):
        raise PR202EvidenceError(f"PR202_INVALID_IMAGE_DIGEST:{field_name}")


def _require_safe_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise PR202EvidenceError(f"PR202_INVALID_SAFE_ID:{field_name}")


def _require_blockhash(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _BLOCKHASH_RE.fullmatch(value):
        raise PR202EvidenceError(f"PR202_INVALID_BLOCKHASH:{field_name}")


def _require_nonnegative_int(value: int, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise PR202EvidenceError(f"PR202_INVALID_NONNEGATIVE_INT:{field_name}")


def _require_positive_int(value: int, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise PR202EvidenceError(f"PR202_INVALID_POSITIVE_INT:{field_name}")


def _strict_int(value: Any, field_name: str) -> int:
    if type(value) is not int:
        raise PR202EvidenceError(f"PR202_INVALID_INT:{field_name}")
    return value
