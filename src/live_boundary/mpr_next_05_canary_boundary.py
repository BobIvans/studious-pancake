"""MPR-NEXT-05 default-off signer/Jito/canary boundary primitives.

This module is intentionally side-effect-limited and network-free. It does not
sign messages, submit transactions, call RPC/Jito, load wallets, or enable live
mode. It models the gate that must be satisfied before an isolated signer would
be allowed to receive exactly one permit-bound message.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "mpr-next-05.signer-jito-canary-boundary.v1"
PERMIT_LEDGER_SCHEMA_VERSION = "mpr-next-05.permit-consumption-ledger.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROGRAM_ID = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,64}$")


class CanaryBoundaryError(ValueError):
    """Raised when canary boundary inputs are malformed."""


class CanarySigningState(StrEnum):
    BLOCKED = "blocked"
    READY_FOR_ISOLATED_SIGNER = "ready-for-isolated-signer"


class JitoLifecycleState(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    LANDED = "landed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    FAILED = "failed"
    EXPIRED = "expired"
    RECONCILED = "reconciled"


@dataclass(frozen=True, slots=True)
class CanaryApprovalArtifact:
    approval_id: str
    operator: str
    second_reviewer: str
    approved_at_unix_ms: int
    expires_at_unix_ms: int
    runtime_artifact_digest: str
    config_digest: str
    capability_manifest_digest: str
    max_spend_lamports: int
    max_tip_lamports: int
    max_loss_lamports: int
    allowed_program_ids: tuple[str, ...]
    one_transaction_limit: bool
    approved: bool
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        _text(self.approval_id, "approval_id")
        _text(self.operator, "operator")
        _text(self.second_reviewer, "second_reviewer")
        if self.operator == self.second_reviewer:
            raise CanaryBoundaryError("approval requires an independent second reviewer")
        _non_negative_int(self.approved_at_unix_ms, "approved_at_unix_ms")
        _non_negative_int(self.expires_at_unix_ms, "expires_at_unix_ms")
        if self.expires_at_unix_ms <= self.approved_at_unix_ms:
            raise CanaryBoundaryError("approval expiry must be after approval time")
        for field_name in (
            "runtime_artifact_digest",
            "config_digest",
            "capability_manifest_digest",
        ):
            _sha(getattr(self, field_name), field_name)
        _positive_int(self.max_spend_lamports, "max_spend_lamports")
        _non_negative_int(self.max_tip_lamports, "max_tip_lamports")
        _non_negative_int(self.max_loss_lamports, "max_loss_lamports")
        if self.max_tip_lamports > self.max_spend_lamports:
            raise CanaryBoundaryError("tip budget cannot exceed spend budget")
        if self.max_loss_lamports > self.max_spend_lamports:
            raise CanaryBoundaryError("loss budget cannot exceed spend budget")
        _program_tuple(self.allowed_program_ids, "allowed_program_ids")
        _bool(self.one_transaction_limit, "one_transaction_limit")
        _bool(self.approved, "approved")

    @property
    def digest(self) -> str:
        return _hash_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class CanaryPermit:
    permit_id: str
    approval_digest: str
    attempt_id: str
    final_message_digest: str
    route_digest: str
    simulation_digest: str
    account_metas_digest: str
    allowed_program_ids: tuple[str, ...]
    max_fee_lamports: int
    max_tip_lamports: int
    max_loss_lamports: int
    expires_at_unix_ms: int
    nonce_digest: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        _text(self.permit_id, "permit_id")
        _text(self.attempt_id, "attempt_id")
        for field_name in (
            "approval_digest",
            "final_message_digest",
            "route_digest",
            "simulation_digest",
            "account_metas_digest",
            "nonce_digest",
        ):
            _sha(getattr(self, field_name), field_name)
        _program_tuple(self.allowed_program_ids, "allowed_program_ids")
        _non_negative_int(self.max_fee_lamports, "max_fee_lamports")
        _non_negative_int(self.max_tip_lamports, "max_tip_lamports")
        _non_negative_int(self.max_loss_lamports, "max_loss_lamports")
        _positive_int(self.expires_at_unix_ms, "expires_at_unix_ms")

    @property
    def digest(self) -> str:
        return _hash_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class CanarySigningRequest:
    permit_id: str
    final_message_digest: str
    route_digest: str
    simulation_digest: str
    account_metas_digest: str
    program_ids: tuple[str, ...]
    fee_lamports: int
    tip_lamports: int
    requested_at_unix_ms: int
    kill_switch_active: bool
    jito_requested: bool
    jito_policy_allowed: bool
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        _text(self.permit_id, "permit_id")
        for field_name in (
            "final_message_digest",
            "route_digest",
            "simulation_digest",
            "account_metas_digest",
        ):
            _sha(getattr(self, field_name), field_name)
        _program_tuple(self.program_ids, "program_ids")
        _non_negative_int(self.fee_lamports, "fee_lamports")
        _non_negative_int(self.tip_lamports, "tip_lamports")
        _positive_int(self.requested_at_unix_ms, "requested_at_unix_ms")
        _bool(self.kill_switch_active, "kill_switch_active")
        _bool(self.jito_requested, "jito_requested")
        _bool(self.jito_policy_allowed, "jito_policy_allowed")

    @property
    def spend_lamports(self) -> int:
        return self.fee_lamports + self.tip_lamports

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class CanarySigningVerdict:
    state: CanarySigningState
    signer_refuses: bool
    live_ready: bool
    canary_available: bool
    blockers: tuple[str, ...]
    signing_intent_digest: str | None
    permit_consumed: bool
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


class FilePermitLedger:
    """Tiny durable permit-consumption ledger for tests and canary plumbing.

    The ledger stores only permit ids and redacted permit digests. It never stores
    private keys, signatures or transaction bytes.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def consumed(self, permit_id: str) -> bool:
        return permit_id in self._load()["consumed_permits"]

    def consume_once(self, permit_id: str, permit_digest: str) -> bool:
        _text(permit_id, "permit_id")
        _sha(permit_digest, "permit_digest")
        document = self._load()
        consumed = document["consumed_permits"]
        existing = consumed.get(permit_id)
        if existing is not None:
            if existing != permit_digest:
                raise CanaryBoundaryError("permit id was consumed with a different digest")
            return False
        consumed[permit_id] = permit_digest
        self._write(document)
        return True

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": PERMIT_LEDGER_SCHEMA_VERSION,
                "consumed_permits": {},
            }
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise CanaryBoundaryError("permit ledger must be a JSON object")
        if loaded.get("schema_version") != PERMIT_LEDGER_SCHEMA_VERSION:
            raise CanaryBoundaryError("permit ledger schema mismatch")
        consumed = loaded.get("consumed_permits")
        if not isinstance(consumed, dict):
            raise CanaryBoundaryError("permit ledger consumed_permits must be an object")
        for key, value in consumed.items():
            _text(str(key), "permit ledger id")
            _sha(str(value), "permit ledger digest")
        return {
            "schema_version": PERMIT_LEDGER_SCHEMA_VERSION,
            "consumed_permits": {str(k): str(v) for k, v in consumed.items()},
        }

    def _write(self, document: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise


@dataclass(frozen=True, slots=True)
class JitoTransportReceipt:
    state: JitoLifecycleState
    bundle_id: str | None
    transaction_signature: str | None
    transport_acknowledged: bool
    landed: bool
    confirmed: bool
    finalized: bool
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        _bool(self.transport_acknowledged, "transport_acknowledged")
        _bool(self.landed, "landed")
        _bool(self.confirmed, "confirmed")
        _bool(self.finalized, "finalized")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class FinalizedSettlementEvidence:
    transaction_signature: str
    final_message_digest: str
    finalized_slot: int
    token_balance_deltas_digest: str
    native_balance_deltas_digest: str
    actual_fee_lamports: int
    rent_delta_lamports: int
    ata_delta_lamports: int
    wsol_delta_lamports: int
    flashloan_repaid: bool
    realized_net_pnl_lamports: int
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        _text(self.transaction_signature, "transaction_signature")
        for field_name in (
            "final_message_digest",
            "token_balance_deltas_digest",
            "native_balance_deltas_digest",
        ):
            _sha(getattr(self, field_name), field_name)
        _positive_int(self.finalized_slot, "finalized_slot")
        _non_negative_int(self.actual_fee_lamports, "actual_fee_lamports")
        _int_not_bool(self.rent_delta_lamports, "rent_delta_lamports")
        _int_not_bool(self.ata_delta_lamports, "ata_delta_lamports")
        _int_not_bool(self.wsol_delta_lamports, "wsol_delta_lamports")
        _bool(self.flashloan_repaid, "flashloan_repaid")
        _int_not_bool(self.realized_net_pnl_lamports, "realized_net_pnl_lamports")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class SettlementVerdict:
    settled: bool
    realized_profit_allowed: bool
    blockers: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_canary_signing_request(
    *,
    approval: CanaryApprovalArtifact,
    permit: CanaryPermit,
    request: CanarySigningRequest,
    ledger: FilePermitLedger,
) -> CanarySigningVerdict:
    blockers: list[str] = []

    def block(condition: bool, reason: str) -> None:
        if not condition:
            blockers.append(reason)

    block(approval.approved, "HUMAN_APPROVAL_NOT_APPROVED")
    block(approval.one_transaction_limit, "ONE_TRANSACTION_LIMIT_REQUIRED")
    block(request.requested_at_unix_ms < approval.expires_at_unix_ms, "APPROVAL_EXPIRED")
    block(permit.approval_digest == approval.digest, "PERMIT_APPROVAL_DIGEST_MISMATCH")
    block(request.permit_id == permit.permit_id, "REQUEST_PERMIT_ID_MISMATCH")
    block(request.requested_at_unix_ms < permit.expires_at_unix_ms, "PERMIT_EXPIRED")
    block(request.final_message_digest == permit.final_message_digest, "FINAL_MESSAGE_DIGEST_MISMATCH")
    block(request.route_digest == permit.route_digest, "ROUTE_DIGEST_MISMATCH")
    block(request.simulation_digest == permit.simulation_digest, "SIMULATION_DIGEST_MISMATCH")
    block(request.account_metas_digest == permit.account_metas_digest, "ACCOUNT_METAS_DIGEST_MISMATCH")
    block(not request.kill_switch_active, "KILL_SWITCH_ACTIVE")
    block(request.fee_lamports <= permit.max_fee_lamports, "FEE_EXCEEDS_PERMIT")
    block(request.tip_lamports <= permit.max_tip_lamports, "TIP_EXCEEDS_PERMIT")
    block(request.tip_lamports <= approval.max_tip_lamports, "TIP_EXCEEDS_APPROVAL")
    block(permit.max_loss_lamports <= approval.max_loss_lamports, "LOSS_EXCEEDS_APPROVAL")
    block(request.spend_lamports <= approval.max_spend_lamports, "SPEND_EXCEEDS_APPROVAL")
    if request.jito_requested:
        block(request.jito_policy_allowed, "JITO_DISABLED_FOR_CANARY")
    for program_id in request.program_ids:
        block(program_id in permit.allowed_program_ids, f"PROGRAM_NOT_IN_PERMIT:{program_id}")
        block(program_id in approval.allowed_program_ids, f"PROGRAM_NOT_IN_APPROVAL:{program_id}")
    if ledger.consumed(permit.permit_id):
        blockers.append("PERMIT_ALREADY_CONSUMED")

    unique_blockers = tuple(dict.fromkeys(blockers))
    if unique_blockers:
        return CanarySigningVerdict(
            state=CanarySigningState.BLOCKED,
            signer_refuses=True,
            live_ready=False,
            canary_available=False,
            blockers=unique_blockers,
            signing_intent_digest=None,
            permit_consumed=False,
        )

    consumed = ledger.consume_once(permit.permit_id, permit.digest)
    if not consumed:
        return CanarySigningVerdict(
            state=CanarySigningState.BLOCKED,
            signer_refuses=True,
            live_ready=False,
            canary_available=False,
            blockers=("PERMIT_ALREADY_CONSUMED",),
            signing_intent_digest=None,
            permit_consumed=False,
        )
    return CanarySigningVerdict(
        state=CanarySigningState.READY_FOR_ISOLATED_SIGNER,
        signer_refuses=False,
        live_ready=False,
        canary_available=True,
        blockers=(),
        signing_intent_digest=_hash_json(
            {
                "domain": "mpr-next-05-signing-intent",
                "approval_digest": approval.digest,
                "permit_digest": permit.digest,
                "request": request.to_dict(),
            }
        ),
        permit_consumed=True,
    )


def evaluate_finalized_settlement(
    *,
    receipt: JitoTransportReceipt,
    evidence: FinalizedSettlementEvidence | None,
    expected_final_message_digest: str,
) -> SettlementVerdict:
    _sha(expected_final_message_digest, "expected_final_message_digest")
    blockers: list[str] = []
    if receipt.transport_acknowledged and evidence is None:
        blockers.append("JITO_ACK_IS_NOT_SETTLEMENT")
    if receipt.landed and evidence is None:
        blockers.append("JITO_LANDED_IS_NOT_FINAL_ECONOMIC_PROOF")
    if evidence is None:
        blockers.append("FINALIZED_CHAIN_EVIDENCE_REQUIRED")
    else:
        if not receipt.finalized or receipt.state is not JitoLifecycleState.FINALIZED:
            blockers.append("TRANSPORT_NOT_FINALIZED")
        if evidence.final_message_digest != expected_final_message_digest:
            blockers.append("SETTLEMENT_MESSAGE_DIGEST_MISMATCH")
        if not evidence.flashloan_repaid:
            blockers.append("FLASHLOAN_REPAYMENT_NOT_PROVEN")
        if evidence.token_balance_deltas_digest == evidence.native_balance_deltas_digest:
            blockers.append("BALANCE_DELTA_DOMAINS_NOT_SEPARATE")
    unique = tuple(dict.fromkeys(blockers))
    return SettlementVerdict(
        settled=not unique,
        realized_profit_allowed=not unique,
        blockers=unique,
    )


def _schema(value: str) -> None:
    if value != SCHEMA_VERSION:
        raise CanaryBoundaryError("schema version mismatch")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {name: _jsonable(item) for name, item in asdict(value).items()}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CanaryBoundaryError(f"{field} is required")


def _sha(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value) or value == "0" * 64:
        raise CanaryBoundaryError(f"{field} must be non-placeholder sha256")


def _program_tuple(value: Sequence[str], field: str) -> None:
    if not isinstance(value, tuple) or not value:
        raise CanaryBoundaryError(f"{field} must be a non-empty tuple")
    for item in value:
        if not isinstance(item, str) or not _PROGRAM_ID.fullmatch(item):
            raise CanaryBoundaryError(f"{field} contains invalid program id")


def _bool(value: bool, field: str) -> None:
    if not isinstance(value, bool):
        raise CanaryBoundaryError(f"{field} must be bool")


def _int_not_bool(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CanaryBoundaryError(f"{field} must be int")


def _non_negative_int(value: int, field: str) -> None:
    _int_not_bool(value, field)
    if value < 0:
        raise CanaryBoundaryError(f"{field} must be non-negative")


def _positive_int(value: int, field: str) -> None:
    _int_not_bool(value, field)
    if value <= 0:
        raise CanaryBoundaryError(f"{field} must be positive")


__all__ = [
    "CanaryApprovalArtifact",
    "CanaryBoundaryError",
    "CanaryPermit",
    "CanarySigningRequest",
    "CanarySigningState",
    "CanarySigningVerdict",
    "FilePermitLedger",
    "FinalizedSettlementEvidence",
    "JitoLifecycleState",
    "JitoTransportReceipt",
    "SCHEMA_VERSION",
    "SettlementVerdict",
    "evaluate_canary_signing_request",
    "evaluate_finalized_settlement",
]
