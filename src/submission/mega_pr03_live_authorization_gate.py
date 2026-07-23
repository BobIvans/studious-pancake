"""MEGA-PR-03 default-off live authorization boundary.

This module is an offline acceptance gate for the V5 MEGA-PR-03 cutover. It
validates permit/message/transport/tip/resubmission identity before any future
signer or sender integration is allowed to consume the evidence. It never signs,
submits, calls RPC/Jito, reads private keys or enables live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping

MEGA_PR03_SCHEMA_VERSION = "mega-pr03.live-authorization-boundary.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_TRANSPORTS = frozenset({"rpc", "jito_bundle"})


class MegaPR03Error(ValueError):
    """Raised when live authorization evidence fails closed."""


class AuthorizationStatus(StrEnum):
    READY_DEFAULT_OFF = "READY_DEFAULT_OFF"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class PermitEvidence:
    attempt_id: str
    attempt_generation: int
    message_hash: str
    blockhash: str
    selected_transport: str
    jito_tip_lamports: int
    tip_account: str | None
    last_valid_block_height: int
    issued_at_ns: int
    expires_at_ns: int
    issuer_key_id: str
    reviewer_signature_hash: str
    predecessor_absence_hash: str | None = None
    resend_authorization_hash: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.blockhash, "blockhash")
        _require_text(self.issuer_key_id, "issuer_key_id")
        _strict_positive_int(self.attempt_generation, "attempt_generation")
        _digest(self.message_hash, "message_hash")
        _digest(self.reviewer_signature_hash, "reviewer_signature_hash")
        _strict_non_negative_int(self.jito_tip_lamports, "jito_tip_lamports")
        _strict_positive_int(self.last_valid_block_height, "last_valid_block_height")
        _strict_non_negative_int(self.issued_at_ns, "issued_at_ns")
        _strict_non_negative_int(self.expires_at_ns, "expires_at_ns")
        if self.issued_at_ns >= self.expires_at_ns:
            raise MegaPR03Error("MEGA_PR03_INVALID_PERMIT_TIME_WINDOW")
        if self.selected_transport not in _ALLOWED_TRANSPORTS:
            raise MegaPR03Error("MEGA_PR03_UNKNOWN_TRANSPORT")
        if self.selected_transport == "jito_bundle":
            if self.jito_tip_lamports <= 0 or not self.tip_account:
                raise MegaPR03Error("MEGA_PR03_JITO_TIP_REQUIRED")
        if self.selected_transport == "rpc" and self.jito_tip_lamports != 0:
            raise MegaPR03Error("MEGA_PR03_RPC_PERMIT_CANNOT_CARRY_JITO_TIP")
        if self.predecessor_absence_hash is not None:
            _digest(self.predecessor_absence_hash, "predecessor_absence_hash")
        if self.resend_authorization_hash is not None:
            _digest(self.resend_authorization_hash, "resend_authorization_hash")

    @property
    def permit_hash(self) -> str:
        return _hash_json(
            {
                "schema": MEGA_PR03_SCHEMA_VERSION,
                "attempt_id": self.attempt_id,
                "attempt_generation": self.attempt_generation,
                "message_hash": self.message_hash,
                "blockhash": self.blockhash,
                "selected_transport": self.selected_transport,
                "jito_tip_lamports": self.jito_tip_lamports,
                "tip_account": self.tip_account,
                "last_valid_block_height": self.last_valid_block_height,
                "issued_at_ns": self.issued_at_ns,
                "expires_at_ns": self.expires_at_ns,
                "issuer_key_id": self.issuer_key_id,
                "reviewer_signature_hash": self.reviewer_signature_hash,
                "predecessor_absence_hash": self.predecessor_absence_hash,
                "resend_authorization_hash": self.resend_authorization_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class SignedWireEvidence:
    message_hash: str
    signed_transaction_hash: str
    blockhash: str
    selected_transport: str
    wire_tip_lamports: int
    wire_tip_account: str | None
    wire_tip_static_account: bool

    def __post_init__(self) -> None:
        _digest(self.message_hash, "message_hash")
        _digest(self.signed_transaction_hash, "signed_transaction_hash")
        _require_text(self.blockhash, "blockhash")
        _strict_non_negative_int(self.wire_tip_lamports, "wire_tip_lamports")
        if self.selected_transport not in _ALLOWED_TRANSPORTS:
            raise MegaPR03Error("MEGA_PR03_UNKNOWN_WIRE_TRANSPORT")
        if self.selected_transport == "jito_bundle":
            if self.wire_tip_lamports <= 0 or not self.wire_tip_account:
                raise MegaPR03Error("MEGA_PR03_WIRE_JITO_TIP_REQUIRED")
            if self.wire_tip_static_account is not True:
                raise MegaPR03Error("MEGA_PR03_WIRE_TIP_ACCOUNT_NOT_STATIC")
        if self.selected_transport == "rpc" and self.wire_tip_lamports != 0:
            raise MegaPR03Error("MEGA_PR03_RPC_WIRE_CANNOT_CARRY_JITO_TIP")


@dataclass(frozen=True, slots=True)
class SubmissionIntentEvidence:
    permit_hash: str
    attempt_id: str
    attempt_generation: int
    message_hash: str
    signed_transaction_hash: str
    selected_transport: str
    jito_tip_lamports: int
    tip_account: str | None
    blockhash: str
    resend_authorization_hash: str | None = None

    def __post_init__(self) -> None:
        _digest(self.permit_hash, "permit_hash")
        _require_text(self.attempt_id, "attempt_id")
        _strict_positive_int(self.attempt_generation, "attempt_generation")
        _digest(self.message_hash, "message_hash")
        _digest(self.signed_transaction_hash, "signed_transaction_hash")
        _strict_non_negative_int(self.jito_tip_lamports, "jito_tip_lamports")
        _require_text(self.blockhash, "blockhash")
        if self.selected_transport not in _ALLOWED_TRANSPORTS:
            raise MegaPR03Error("MEGA_PR03_UNKNOWN_INTENT_TRANSPORT")
        if self.resend_authorization_hash is not None:
            _digest(self.resend_authorization_hash, "resend_authorization_hash")


@dataclass(frozen=True, slots=True)
class SettlementEvidence:
    permit_hash: str
    message_hash: str
    selected_transport: str
    jito_tip_lamports: int
    tip_account: str | None
    rooted_finalized: bool

    def __post_init__(self) -> None:
        _digest(self.permit_hash, "permit_hash")
        _digest(self.message_hash, "message_hash")
        _strict_non_negative_int(self.jito_tip_lamports, "jito_tip_lamports")
        if self.selected_transport not in _ALLOWED_TRANSPORTS:
            raise MegaPR03Error("MEGA_PR03_UNKNOWN_SETTLEMENT_TRANSPORT")


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    status: AuthorizationStatus
    reason_codes: tuple[str, ...]
    permit_hash: str | None
    authorization_hash: str | None

    @property
    def ready(self) -> bool:
        return self.status is AuthorizationStatus.READY_DEFAULT_OFF


class MegaPR03AuthorizationGate:
    """Default-off permit/transport/tip/resubmission consistency gate."""

    def evaluate(
        self,
        *,
        permit: PermitEvidence,
        wire: SignedWireEvidence,
        intent: SubmissionIntentEvidence,
        settlement: SettlementEvidence | None,
        now_ns: int,
        current_block_height: int,
        remaining_height_margin: int,
        live_runtime_enabled: bool = False,
        legacy_live_path_reachable: bool = False,
    ) -> AuthorizationDecision:
        _strict_non_negative_int(now_ns, "now_ns")
        _strict_positive_int(current_block_height, "current_block_height")
        _strict_non_negative_int(remaining_height_margin, "remaining_height_margin")
        reason_codes: list[str] = []

        if live_runtime_enabled:
            reason_codes.append("MEGA_PR03_LIVE_RUNTIME_MUST_REMAIN_DEFAULT_OFF")
        if legacy_live_path_reachable:
            reason_codes.append("MEGA_PR03_LEGACY_LIVE_PATH_REACHABLE")
        if now_ns < permit.issued_at_ns:
            reason_codes.append("MEGA_PR03_PERMIT_NOT_YET_VALID")
        if now_ns >= permit.expires_at_ns:
            reason_codes.append("MEGA_PR03_PERMIT_EXPIRED")
        if current_block_height + remaining_height_margin > permit.last_valid_block_height:
            reason_codes.append("MEGA_PR03_BLOCKHASH_HEIGHT_MARGIN_EXPIRED")
        if permit.attempt_generation == 1:
            if permit.predecessor_absence_hash is None:
                reason_codes.append("MEGA_PR03_FIRST_GENERATION_ABSENCE_PROOF_REQUIRED")
        elif permit.resend_authorization_hash is None:
            reason_codes.append("MEGA_PR03_RESEND_AUTHORIZATION_REQUIRED")

        _compare(
            reason_codes,
            "MEGA_PR03_WIRE_MESSAGE_MISMATCH",
            permit.message_hash,
            wire.message_hash,
        )
        _compare(
            reason_codes,
            "MEGA_PR03_WIRE_BLOCKHASH_MISMATCH",
            permit.blockhash,
            wire.blockhash,
        )
        _compare(
            reason_codes,
            "MEGA_PR03_WIRE_TRANSPORT_MISMATCH",
            permit.selected_transport,
            wire.selected_transport,
        )
        _compare(
            reason_codes,
            "MEGA_PR03_WIRE_TIP_AMOUNT_MISMATCH",
            permit.jito_tip_lamports,
            wire.wire_tip_lamports,
        )
        _compare(
            reason_codes,
            "MEGA_PR03_WIRE_TIP_ACCOUNT_MISMATCH",
            permit.tip_account,
            wire.wire_tip_account,
        )

        _compare(reason_codes, "MEGA_PR03_INTENT_PERMIT_HASH_MISMATCH", permit.permit_hash, intent.permit_hash)
        _compare(reason_codes, "MEGA_PR03_INTENT_ATTEMPT_MISMATCH", permit.attempt_id, intent.attempt_id)
        _compare(
            reason_codes,
            "MEGA_PR03_INTENT_GENERATION_MISMATCH",
            permit.attempt_generation,
            intent.attempt_generation,
        )
        _compare(reason_codes, "MEGA_PR03_INTENT_MESSAGE_MISMATCH", permit.message_hash, intent.message_hash)
        _compare(
            reason_codes,
            "MEGA_PR03_INTENT_SIGNED_TX_MISMATCH",
            wire.signed_transaction_hash,
            intent.signed_transaction_hash,
        )
        _compare(
            reason_codes,
            "MEGA_PR03_INTENT_TRANSPORT_MISMATCH",
            permit.selected_transport,
            intent.selected_transport,
        )
        _compare(
            reason_codes,
            "MEGA_PR03_INTENT_TIP_AMOUNT_MISMATCH",
            permit.jito_tip_lamports,
            intent.jito_tip_lamports,
        )
        _compare(
            reason_codes,
            "MEGA_PR03_INTENT_TIP_ACCOUNT_MISMATCH",
            permit.tip_account,
            intent.tip_account,
        )
        _compare(reason_codes, "MEGA_PR03_INTENT_BLOCKHASH_MISMATCH", permit.blockhash, intent.blockhash)
        _compare(
            reason_codes,
            "MEGA_PR03_INTENT_RESEND_AUTH_MISMATCH",
            permit.resend_authorization_hash,
            intent.resend_authorization_hash,
        )

        if settlement is not None:
            if settlement.rooted_finalized is not True:
                reason_codes.append("MEGA_PR03_SETTLEMENT_NOT_ROOTED_FINALIZED")
            _compare(
                reason_codes,
                "MEGA_PR03_SETTLEMENT_PERMIT_HASH_MISMATCH",
                permit.permit_hash,
                settlement.permit_hash,
            )
            _compare(
                reason_codes,
                "MEGA_PR03_SETTLEMENT_MESSAGE_MISMATCH",
                permit.message_hash,
                settlement.message_hash,
            )
            _compare(
                reason_codes,
                "MEGA_PR03_SETTLEMENT_TRANSPORT_MISMATCH",
                permit.selected_transport,
                settlement.selected_transport,
            )
            _compare(
                reason_codes,
                "MEGA_PR03_SETTLEMENT_TIP_AMOUNT_MISMATCH",
                permit.jito_tip_lamports,
                settlement.jito_tip_lamports,
            )
            _compare(
                reason_codes,
                "MEGA_PR03_SETTLEMENT_TIP_ACCOUNT_MISMATCH",
                permit.tip_account,
                settlement.tip_account,
            )

        if reason_codes:
            return AuthorizationDecision(
                AuthorizationStatus.BLOCKED,
                tuple(reason_codes),
                permit.permit_hash,
                None,
            )
        authorization_hash = _hash_json(
            {
                "schema": MEGA_PR03_SCHEMA_VERSION,
                "permit_hash": permit.permit_hash,
                "signed_transaction_hash": wire.signed_transaction_hash,
                "intent": _dataclass_payload(intent),
                "settlement": None if settlement is None else _dataclass_payload(settlement),
                "current_block_height": current_block_height,
                "remaining_height_margin": remaining_height_margin,
                "status": AuthorizationStatus.READY_DEFAULT_OFF.value,
            }
        )
        return AuthorizationDecision(
            AuthorizationStatus.READY_DEFAULT_OFF,
            ("MEGA_PR03_READY_BUT_LIVE_DEFAULT_OFF",),
            permit.permit_hash,
            authorization_hash,
        )


def _compare(reason_codes: list[str], code: str, left: object, right: object) -> None:
    if left != right:
        reason_codes.append(code)


def _dataclass_payload(value: object) -> Mapping[str, object]:
    return {name: getattr(value, name) for name in value.__dataclass_fields__}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _digest(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise MegaPR03Error(f"{name} must be lowercase sha256")


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MegaPR03Error(f"{name} is required")


def _strict_positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MegaPR03Error(f"{name} must be a positive integer")


def _strict_non_negative_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MegaPR03Error(f"{name} must be a non-negative integer")


__all__ = [
    "AuthorizationDecision",
    "AuthorizationStatus",
    "MEGA_PR03_SCHEMA_VERSION",
    "MegaPR03AuthorizationGate",
    "MegaPR03Error",
    "PermitEvidence",
    "SettlementEvidence",
    "SignedWireEvidence",
    "SubmissionIntentEvidence",
]
