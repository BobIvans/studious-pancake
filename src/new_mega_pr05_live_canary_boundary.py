"""NEW-MEGA-PR-05 authenticated isolated signer and bounded live canary boundary.

This module is deliberately offline and fail-closed.  It does not load a real
private key, submit transactions, poll RPC/Jito, or enable unrestricted live
trading.  It codifies the acceptance boundary needed before a bounded live
canary can be reviewed: authenticated two-person permits, exact-message signer
binding, durable one-time permit consumption, blockheight validity, immutable
transport/tip identity, finalized settlement reconciliation, and hard canary
latches.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import hmac
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "new-mega-pr05.live-canary-boundary.v1"
_SHA256_HEX_LENGTH = 64
_MIN_ATTEMPT_GENERATION = 1


class BoundaryState(str, Enum):
    READY_FOR_BOUNDED_CANARY_REVIEW = "ready_for_bounded_canary_review"
    BLOCKED = "blocked"
    MANUAL_REVIEW = "manual_review"


class Transport(str, Enum):
    RPC = "rpc"
    JITO = "jito"


class PermitStatus(str, Enum):
    ISSUED = "issued"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class SettlementStatus(str, Enum):
    TRANSPORT_ACK = "transport_ack"
    LANDED = "landed"
    FINALIZED = "finalized"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Blocker:
    code: str
    message: str


@dataclass(frozen=True)
class ReviewerKey:
    key_id: str
    secret: str
    role: str
    revoked: bool = False

    def __post_init__(self) -> None:
        _text(self.key_id, "key_id")
        _text(self.secret, "secret")
        if self.role not in {"issuer", "reviewer"}:
            raise ValueError("PR05_UNSUPPORTED_REVIEWER_ROLE")


@dataclass(frozen=True)
class MessageAuthorization:
    attempt_id: str
    attempt_generation: int
    wallet: str
    market: str
    asset: str
    exact_message_hash: str
    final_simulation_hash: str
    policy_hash: str
    evidence_bundle_hash: str
    selected_transport: Transport
    tip_lamports: int
    last_valid_block_height: int
    safety_margin_blocks: int
    unrestricted_live: bool = False

    def __post_init__(self) -> None:
        _text(self.attempt_id, "attempt_id")
        _text(self.wallet, "wallet")
        _text(self.market, "market")
        _text(self.asset, "asset")
        _strict_positive_int(self.attempt_generation, "attempt_generation")
        _sha(self.exact_message_hash, "exact_message_hash")
        _sha(self.final_simulation_hash, "final_simulation_hash")
        _sha(self.policy_hash, "policy_hash")
        _sha(self.evidence_bundle_hash, "evidence_bundle_hash")
        _strict_non_negative_int(self.tip_lamports, "tip_lamports")
        _strict_positive_int(self.last_valid_block_height, "last_valid_block_height")
        _strict_non_negative_int(self.safety_margin_blocks, "safety_margin_blocks")
        if self.attempt_generation < _MIN_ATTEMPT_GENERATION:
            raise ValueError("PR05_ATTEMPT_GENERATION_TOO_LOW")


@dataclass(frozen=True)
class PermitRequest:
    nonce: str
    attempt_id: str
    attempt_generation: int
    wallet: str
    market: str
    asset: str
    exact_message_hash: str
    transport: Transport
    tip_lamports: int
    evidence_bundle_hash: str
    issued_at_unix_ns: int
    expires_at_unix_ns: int
    policy_hash: str
    session_hash: str
    reviewer_set_hash: str
    resend_authorization_hash: str | None = None

    def __post_init__(self) -> None:
        _text(self.nonce, "nonce")
        _text(self.attempt_id, "attempt_id")
        _strict_positive_int(self.attempt_generation, "attempt_generation")
        if self.attempt_generation < _MIN_ATTEMPT_GENERATION:
            raise ValueError("PR05_ATTEMPT_GENERATION_TOO_LOW")
        _text(self.wallet, "wallet")
        _text(self.market, "market")
        _text(self.asset, "asset")
        _sha(self.exact_message_hash, "exact_message_hash")
        _strict_non_negative_int(self.tip_lamports, "tip_lamports")
        _sha(self.evidence_bundle_hash, "evidence_bundle_hash")
        _strict_non_negative_int(self.issued_at_unix_ns, "issued_at_unix_ns")
        _strict_non_negative_int(self.expires_at_unix_ns, "expires_at_unix_ns")
        if self.issued_at_unix_ns >= self.expires_at_unix_ns:
            raise ValueError("PR05_INVALID_PERMIT_TIME_WINDOW")
        _sha(self.policy_hash, "policy_hash")
        _sha(self.session_hash, "session_hash")
        _sha(self.reviewer_set_hash, "reviewer_set_hash")
        if self.resend_authorization_hash is not None:
            _sha(self.resend_authorization_hash, "resend_authorization_hash")


@dataclass(frozen=True)
class AuthenticatedPermit:
    request: PermitRequest
    issuer_key_id: str
    issuer_signature: str
    reviewer_key_id: str
    reviewer_signature: str

    @property
    def permit_hash(self) -> str:
        return _sha256_json(
            {
                "request": _normalize(self.request),
                "issuer_key_id": self.issuer_key_id,
                "issuer_signature": self.issuer_signature,
                "reviewer_key_id": self.reviewer_key_id,
                "reviewer_signature": self.reviewer_signature,
            }
        )


@dataclass(frozen=True)
class PermitValidation:
    state: BoundaryState
    blockers: tuple[Blocker, ...]
    permit_hash: str


@dataclass(frozen=True)
class SignedWireEvidence:
    signer_id: str
    signer_public_key_hash: str
    exact_message_hash: str
    signature_hash: str
    signed_wire_hash: str
    selected_transport: Transport
    tip_lamports: int
    current_block_height: int


class IsolatedSigner:
    """Deterministic isolated-signing façade used for offline boundary tests.

    The signer owns the secret.  The runtime only receives a signed-wire evidence
    record.  The implementation uses HMAC as a deterministic local stand-in for
    a real signer/KMS/HSM signature so the safety contract can be tested without
    handling private keys in the runtime.
    """

    def __init__(self, *, signer_id: str, signer_secret: str, public_key: str) -> None:
        _text(signer_id, "signer_id")
        _text(signer_secret, "signer_secret")
        _text(public_key, "public_key")
        self._signer_id = signer_id
        self._signer_secret = signer_secret.encode("utf-8")
        self._public_key_hash = _sha256_text(public_key)

    @property
    def signer_id(self) -> str:
        return self._signer_id

    def sign_authorized_message(
        self,
        *,
        authorization: MessageAuthorization,
        exact_message_bytes: bytes,
        current_block_height: int,
    ) -> SignedWireEvidence:
        _strict_positive_int(current_block_height, "current_block_height")
        actual_message_hash = hashlib.sha256(exact_message_bytes).hexdigest()
        if actual_message_hash != authorization.exact_message_hash:
            raise ValueError("PR05_SIGNER_MESSAGE_HASH_MISMATCH")
        _assert_blockheight_valid(
            current_block_height=current_block_height,
            last_valid_block_height=authorization.last_valid_block_height,
            safety_margin_blocks=authorization.safety_margin_blocks,
        )
        if authorization.unrestricted_live:
            raise ValueError("PR05_UNRESTRICTED_LIVE_FORBIDDEN")
        signature = hmac.new(
            self._signer_secret,
            exact_message_bytes + authorization.policy_hash.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        signed_wire_hash = hashlib.sha256(
            exact_message_bytes + signature.encode("ascii")
        ).hexdigest()
        return SignedWireEvidence(
            signer_id=self._signer_id,
            signer_public_key_hash=self._public_key_hash,
            exact_message_hash=actual_message_hash,
            signature_hash=signature,
            signed_wire_hash=signed_wire_hash,
            selected_transport=authorization.selected_transport,
            tip_lamports=authorization.tip_lamports,
            current_block_height=current_block_height,
        )


@dataclass(frozen=True)
class TipEvidence:
    source: str
    signed_wire_hash: str
    transport: Transport
    tip_lamports: int

    def __post_init__(self) -> None:
        if self.source != "signed_wire":
            raise ValueError("PR05_TIP_EVIDENCE_NOT_WIRE_DERIVED")
        _sha(self.signed_wire_hash, "signed_wire_hash")
        _strict_non_negative_int(self.tip_lamports, "tip_lamports")


@dataclass(frozen=True)
class SubmissionIntent:
    permit_hash: str
    attempt_id: str
    attempt_generation: int
    exact_message_hash: str
    signed_wire_hash: str
    selected_transport: Transport
    tip_lamports: int
    status: SettlementStatus
    ack_or_bundle_id: str | None = None

    def __post_init__(self) -> None:
        _sha(self.permit_hash, "permit_hash")
        _text(self.attempt_id, "attempt_id")
        _strict_positive_int(self.attempt_generation, "attempt_generation")
        _sha(self.exact_message_hash, "exact_message_hash")
        _sha(self.signed_wire_hash, "signed_wire_hash")
        _strict_non_negative_int(self.tip_lamports, "tip_lamports")


@dataclass(frozen=True)
class FinalizedSettlementEvidence:
    status: SettlementStatus
    signature_hash: str
    finalized_slot: int | None
    exact_message_hash: str
    signed_wire_hash: str
    instruction_hash: str
    fee_lamports: int
    payer_delta_lamports: int
    token_delta_hash: str
    realized_pnl_lamports: int | None
    selected_transport: Transport
    tip_lamports: int

    def __post_init__(self) -> None:
        _sha(self.signature_hash, "signature_hash")
        if self.finalized_slot is not None:
            _strict_positive_int(self.finalized_slot, "finalized_slot")
        _sha(self.exact_message_hash, "exact_message_hash")
        _sha(self.signed_wire_hash, "signed_wire_hash")
        _sha(self.instruction_hash, "instruction_hash")
        _strict_non_negative_int(self.fee_lamports, "fee_lamports")
        _strict_int(self.payer_delta_lamports, "payer_delta_lamports")
        _sha(self.token_delta_hash, "token_delta_hash")
        if self.realized_pnl_lamports is not None:
            _strict_int(self.realized_pnl_lamports, "realized_pnl_lamports")
        _strict_non_negative_int(self.tip_lamports, "tip_lamports")


@dataclass(frozen=True)
class ReconciliationReport:
    state: BoundaryState
    blockers: tuple[Blocker, ...]
    finalized_settlement: bool
    realized_pnl_lamports: int | None
    manual_review_required: bool


@dataclass(frozen=True)
class CanaryBudget:
    wallet: str
    market: str
    asset: str
    max_count: int
    max_notional_lamports: int
    max_tip_lamports: int
    max_daily_loss_lamports: int
    max_total_loss_lamports: int
    not_before_unix_ns: int
    not_after_unix_ns: int
    evidence_bundle_hash: str
    unrestricted_live_allowed: bool = False

    def __post_init__(self) -> None:
        _text(self.wallet, "wallet")
        _text(self.market, "market")
        _text(self.asset, "asset")
        _strict_positive_int(self.max_count, "max_count")
        _strict_non_negative_int(self.max_notional_lamports, "max_notional_lamports")
        _strict_non_negative_int(self.max_tip_lamports, "max_tip_lamports")
        _strict_non_negative_int(self.max_daily_loss_lamports, "max_daily_loss_lamports")
        _strict_non_negative_int(self.max_total_loss_lamports, "max_total_loss_lamports")
        _strict_non_negative_int(self.not_before_unix_ns, "not_before_unix_ns")
        _strict_non_negative_int(self.not_after_unix_ns, "not_after_unix_ns")
        if self.not_before_unix_ns >= self.not_after_unix_ns:
            raise ValueError("PR05_INVALID_CANARY_WINDOW")
        _sha(self.evidence_bundle_hash, "evidence_bundle_hash")


@dataclass(frozen=True)
class CanaryUsage:
    count: int
    notional_lamports: int
    tip_lamports: int
    daily_loss_lamports: int
    total_loss_lamports: int

    def __post_init__(self) -> None:
        _strict_non_negative_int(self.count, "count")
        _strict_non_negative_int(self.notional_lamports, "notional_lamports")
        _strict_non_negative_int(self.tip_lamports, "tip_lamports")
        _strict_non_negative_int(self.daily_loss_lamports, "daily_loss_lamports")
        _strict_non_negative_int(self.total_loss_lamports, "total_loss_lamports")


@dataclass(frozen=True)
class CanaryLatchReport:
    state: BoundaryState
    kill_latch_triggered: bool
    blockers: tuple[Blocker, ...]


class DurablePermitAuthority:
    """SQLite-backed one-per-attempt-generation permit authority."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS permits (
                    attempt_id TEXT NOT NULL,
                    attempt_generation INTEGER NOT NULL,
                    permit_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    issued_at_unix_ns INTEGER NOT NULL,
                    consumed_at_unix_ns INTEGER,
                    PRIMARY KEY (attempt_id, attempt_generation),
                    UNIQUE (permit_hash),
                    CHECK (attempt_generation >= 1),
                    CHECK (status IN ('issued', 'consumed', 'expired'))
                )
                """
            )

    def issue_once(self, permit: AuthenticatedPermit) -> bool:
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO permits (
                        attempt_id,
                        attempt_generation,
                        permit_hash,
                        status,
                        issued_at_unix_ns
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        permit.request.attempt_id,
                        permit.request.attempt_generation,
                        permit.permit_hash,
                        PermitStatus.ISSUED.value,
                        permit.request.issued_at_unix_ns,
                    ),
                )
                connection.commit()
                return True
            except sqlite3.IntegrityError:
                connection.rollback()
                return False

    def consume_once(self, permit: AuthenticatedPermit, *, now_unix_ns: int) -> bool:
        _strict_non_negative_int(now_unix_ns, "now_unix_ns")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE permits
                   SET status = ?, consumed_at_unix_ns = ?
                 WHERE attempt_id = ?
                   AND attempt_generation = ?
                   AND permit_hash = ?
                   AND status = ?
                """,
                (
                    PermitStatus.CONSUMED.value,
                    now_unix_ns,
                    permit.request.attempt_id,
                    permit.request.attempt_generation,
                    permit.permit_hash,
                    PermitStatus.ISSUED.value,
                ),
            )
            connection.commit()
            return cursor.rowcount == 1


def sign_permit_request(request: PermitRequest, key: ReviewerKey) -> str:
    payload = _sha256_json(_normalize(request))
    return hmac.new(key.secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()


def make_authenticated_permit(
    *,
    request: PermitRequest,
    issuer: ReviewerKey,
    reviewer: ReviewerKey,
) -> AuthenticatedPermit:
    if issuer.key_id == reviewer.key_id:
        raise ValueError("PR05_SECOND_REVIEWER_REQUIRED")
    if issuer.role != "issuer" or reviewer.role != "reviewer":
        raise ValueError("PR05_INVALID_REVIEWER_ROLES")
    return AuthenticatedPermit(
        request=request,
        issuer_key_id=issuer.key_id,
        issuer_signature=sign_permit_request(request, issuer),
        reviewer_key_id=reviewer.key_id,
        reviewer_signature=sign_permit_request(request, reviewer),
    )


def validate_permit(
    *,
    permit: AuthenticatedPermit,
    authorization: MessageAuthorization,
    keyring: Mapping[str, ReviewerKey],
    trusted_now_unix_ns: int,
    current_evidence_bundle_hash: str,
) -> PermitValidation:
    blockers: list[Blocker] = []
    request = permit.request
    _strict_non_negative_int(trusted_now_unix_ns, "trusted_now_unix_ns")
    _sha(current_evidence_bundle_hash, "current_evidence_bundle_hash")
    issuer = keyring.get(permit.issuer_key_id)
    reviewer = keyring.get(permit.reviewer_key_id)
    if issuer is None or reviewer is None:
        _add(blockers, "PR05_UNKNOWN_REVIEWER_KEY", "issuer and reviewer keys must exist")
    elif issuer.revoked or reviewer.revoked:
        _add(blockers, "PR05_REVOKED_REVIEWER_KEY", "revoked keys cannot authorize live canary")
    elif issuer.key_id == reviewer.key_id:
        _add(blockers, "PR05_SECOND_REVIEWER_REQUIRED", "issuer and reviewer must be independent")
    else:
        if issuer.role != "issuer" or reviewer.role != "reviewer":
            _add(blockers, "PR05_INVALID_REVIEWER_ROLES", "reviewer roles are not valid")
        if permit.issuer_signature != sign_permit_request(request, issuer):
            _add(blockers, "PR05_BAD_ISSUER_SIGNATURE", "issuer signature mismatch")
        if permit.reviewer_signature != sign_permit_request(request, reviewer):
            _add(blockers, "PR05_BAD_REVIEWER_SIGNATURE", "reviewer signature mismatch")
    if not (request.issued_at_unix_ns <= trusted_now_unix_ns < request.expires_at_unix_ns):
        _add(blockers, "PR05_PERMIT_TIME_INVALID", "permit must satisfy issued_at <= now < expires_at")
    if request.evidence_bundle_hash != current_evidence_bundle_hash:
        _add(blockers, "PR05_EVIDENCE_BUNDLE_STALE", "permit must bind current evidence bundle")
    if request.attempt_id != authorization.attempt_id or request.attempt_generation != authorization.attempt_generation:
        _add(blockers, "PR05_ATTEMPT_IDENTITY_MISMATCH", "permit and authorization attempt differ")
    if request.wallet != authorization.wallet or request.market != authorization.market or request.asset != authorization.asset:
        _add(blockers, "PR05_SCOPE_MISMATCH", "wallet, market and asset must be immutable")
    if request.exact_message_hash != authorization.exact_message_hash:
        _add(blockers, "PR05_MESSAGE_HASH_MISMATCH", "permit must bind exact simulated message")
    if request.transport is not authorization.selected_transport or request.tip_lamports != authorization.tip_lamports:
        _add(blockers, "PR05_TRANSPORT_TIP_MISMATCH", "transport and tip cannot drift after permit")
    if request.policy_hash != authorization.policy_hash:
        _add(blockers, "PR05_POLICY_HASH_MISMATCH", "policy hash must match authorization")
    if request.attempt_generation > 1 and request.resend_authorization_hash is None:
        _add(blockers, "PR05_RESEND_PROOF_REQUIRED", "generation > 1 requires durable archive-complete resend proof")
    if authorization.unrestricted_live:
        _add(blockers, "PR05_UNRESTRICTED_LIVE_FORBIDDEN", "unrestricted live remains disabled")
    unique = tuple(_dedupe(blockers))
    return PermitValidation(
        state=BoundaryState.BLOCKED if unique else BoundaryState.READY_FOR_BOUNDED_CANARY_REVIEW,
        blockers=unique,
        permit_hash=permit.permit_hash,
    )


def assert_blockheight_allows_consumption(
    *,
    authorization: MessageAuthorization,
    current_block_height: int,
) -> None:
    _assert_blockheight_valid(
        current_block_height=current_block_height,
        last_valid_block_height=authorization.last_valid_block_height,
        safety_margin_blocks=authorization.safety_margin_blocks,
    )


def validate_submission_identity(
    *,
    permit: AuthenticatedPermit,
    authorization: MessageAuthorization,
    signed_wire: SignedWireEvidence,
    tip_evidence: TipEvidence,
) -> tuple[Blocker, ...]:
    blockers: list[Blocker] = []
    if permit.request.exact_message_hash != signed_wire.exact_message_hash:
        _add(blockers, "PR05_SIGNED_MESSAGE_PERMIT_MISMATCH", "signed message differs from permit")
    if authorization.exact_message_hash != signed_wire.exact_message_hash:
        _add(blockers, "PR05_SIGNED_MESSAGE_AUTHORIZATION_MISMATCH", "signed message differs from authorization")
    if tip_evidence.signed_wire_hash != signed_wire.signed_wire_hash:
        _add(blockers, "PR05_TIP_WIRE_HASH_MISMATCH", "tip evidence must come from signed wire")
    if tip_evidence.transport is not signed_wire.selected_transport:
        _add(blockers, "PR05_TIP_TRANSPORT_MISMATCH", "tip transport differs from signed wire")
    if tip_evidence.tip_lamports != signed_wire.tip_lamports:
        _add(blockers, "PR05_TIP_AMOUNT_MISMATCH", "tip amount differs from signed wire")
    if signed_wire.selected_transport is not authorization.selected_transport:
        _add(blockers, "PR05_SELECTED_TRANSPORT_DRIFT", "selected transport drifted after authorization")
    return tuple(_dedupe(blockers))


def reconcile_finalized_settlement(
    *,
    intent: SubmissionIntent,
    settlement: FinalizedSettlementEvidence,
) -> ReconciliationReport:
    blockers: list[Blocker] = []
    manual_review = False
    if intent.status in {SettlementStatus.TRANSPORT_ACK, SettlementStatus.UNKNOWN}:
        manual_review = True
        _add(blockers, "PR05_ACK_OR_UNKNOWN_NOT_FINAL", "ACK, bundle ID or unknown outcome is not finalized settlement")
    if settlement.status is not SettlementStatus.FINALIZED or settlement.finalized_slot is None:
        manual_review = True
        _add(blockers, "PR05_FINALIZED_EVIDENCE_REQUIRED", "realized PnL requires finalized Solana evidence")
    if intent.exact_message_hash != settlement.exact_message_hash:
        _add(blockers, "PR05_SETTLEMENT_MESSAGE_MISMATCH", "settlement message hash differs")
    if intent.signed_wire_hash != settlement.signed_wire_hash:
        _add(blockers, "PR05_SETTLEMENT_WIRE_MISMATCH", "settlement signed wire differs")
    if intent.selected_transport is not settlement.selected_transport or intent.tip_lamports != settlement.tip_lamports:
        _add(blockers, "PR05_SETTLEMENT_TRANSPORT_TIP_MISMATCH", "settlement transport/tip differs")
    if settlement.realized_pnl_lamports is None:
        manual_review = True
        _add(blockers, "PR05_REALIZED_PNL_MISSING", "realized PnL must be derived from finalized raw balance evidence")
    unique = tuple(_dedupe(blockers))
    accepted = not unique and settlement.status is SettlementStatus.FINALIZED
    return ReconciliationReport(
        state=(
            BoundaryState.READY_FOR_BOUNDED_CANARY_REVIEW
            if accepted
            else (BoundaryState.MANUAL_REVIEW if manual_review else BoundaryState.BLOCKED)
        ),
        blockers=unique,
        finalized_settlement=accepted,
        realized_pnl_lamports=settlement.realized_pnl_lamports if accepted else None,
        manual_review_required=not accepted,
    )


def evaluate_canary_latches(
    *,
    budget: CanaryBudget,
    usage: CanaryUsage,
    trusted_now_unix_ns: int,
    second_reviewer_present: bool,
    evidence_bundle_hash: str,
) -> CanaryLatchReport:
    blockers: list[Blocker] = []
    _strict_non_negative_int(trusted_now_unix_ns, "trusted_now_unix_ns")
    _sha(evidence_bundle_hash, "evidence_bundle_hash")
    if not (budget.not_before_unix_ns <= trusted_now_unix_ns < budget.not_after_unix_ns):
        _add(blockers, "PR05_CANARY_WINDOW_CLOSED", "canary window is not currently valid")
    if not second_reviewer_present:
        _add(blockers, "PR05_SECOND_REVIEWER_REQUIRED", "bounded live canary requires second reviewer")
    if budget.evidence_bundle_hash != evidence_bundle_hash:
        _add(blockers, "PR05_CANARY_EVIDENCE_STALE", "canary window requires current evidence bundle")
    if budget.unrestricted_live_allowed:
        _add(blockers, "PR05_UNRESTRICTED_LIVE_FORBIDDEN", "canary cannot authorize unrestricted live")
    if usage.count > budget.max_count:
        _add(blockers, "PR05_CANARY_COUNT_LATCH", "canary count exceeded")
    if usage.notional_lamports > budget.max_notional_lamports:
        _add(blockers, "PR05_CANARY_NOTIONAL_LATCH", "canary notional exceeded")
    if usage.tip_lamports > budget.max_tip_lamports:
        _add(blockers, "PR05_CANARY_TIP_LATCH", "canary tip budget exceeded")
    if usage.daily_loss_lamports > budget.max_daily_loss_lamports:
        _add(blockers, "PR05_CANARY_DAILY_LOSS_LATCH", "daily loss budget exceeded")
    if usage.total_loss_lamports > budget.max_total_loss_lamports:
        _add(blockers, "PR05_CANARY_TOTAL_LOSS_LATCH", "total loss budget exceeded")
    unique = tuple(_dedupe(blockers))
    return CanaryLatchReport(
        state=BoundaryState.BLOCKED if unique else BoundaryState.READY_FOR_BOUNDED_CANARY_REVIEW,
        kill_latch_triggered=bool(unique),
        blockers=unique,
    )


def sample_ready_flow() -> dict[str, Any]:
    digest_a = "a" * 64
    digest_b = "b" * 64
    digest_c = "c" * 64
    message = b"mpr05-exact-final-simulated-versioned-message"
    message_hash = hashlib.sha256(message).hexdigest()
    issuer = ReviewerKey("issuer-key", "issuer-secret", "issuer")
    reviewer = ReviewerKey("reviewer-key", "reviewer-secret", "reviewer")
    authorization = MessageAuthorization(
        attempt_id="attempt-1",
        attempt_generation=1,
        wallet="wallet-a",
        market="SOL/USDC",
        asset="SOL",
        exact_message_hash=message_hash,
        final_simulation_hash=digest_a,
        policy_hash=digest_b,
        evidence_bundle_hash=digest_c,
        selected_transport=Transport.JITO,
        tip_lamports=1_000,
        last_valid_block_height=10_000,
        safety_margin_blocks=100,
    )
    request = PermitRequest(
        nonce="nonce-1",
        attempt_id=authorization.attempt_id,
        attempt_generation=authorization.attempt_generation,
        wallet=authorization.wallet,
        market=authorization.market,
        asset=authorization.asset,
        exact_message_hash=authorization.exact_message_hash,
        transport=authorization.selected_transport,
        tip_lamports=authorization.tip_lamports,
        evidence_bundle_hash=authorization.evidence_bundle_hash,
        issued_at_unix_ns=100,
        expires_at_unix_ns=1_000,
        policy_hash=authorization.policy_hash,
        session_hash=digest_a,
        reviewer_set_hash=digest_b,
    )
    permit = make_authenticated_permit(request=request, issuer=issuer, reviewer=reviewer)
    validation = validate_permit(
        permit=permit,
        authorization=authorization,
        keyring={issuer.key_id: issuer, reviewer.key_id: reviewer},
        trusted_now_unix_ns=500,
        current_evidence_bundle_hash=authorization.evidence_bundle_hash,
    )
    signer = IsolatedSigner(signer_id="signer-1", signer_secret="signer-secret", public_key="pubkey-1")
    signed = signer.sign_authorized_message(
        authorization=authorization,
        exact_message_bytes=message,
        current_block_height=9_800,
    )
    tip = TipEvidence(
        source="signed_wire",
        signed_wire_hash=signed.signed_wire_hash,
        transport=signed.selected_transport,
        tip_lamports=signed.tip_lamports,
    )
    intent = SubmissionIntent(
        permit_hash=permit.permit_hash,
        attempt_id=authorization.attempt_id,
        attempt_generation=authorization.attempt_generation,
        exact_message_hash=signed.exact_message_hash,
        signed_wire_hash=signed.signed_wire_hash,
        selected_transport=signed.selected_transport,
        tip_lamports=signed.tip_lamports,
        status=SettlementStatus.LANDED,
        ack_or_bundle_id="bundle-transport-only",
    )
    settlement = FinalizedSettlementEvidence(
        status=SettlementStatus.FINALIZED,
        signature_hash=signed.signature_hash,
        finalized_slot=123_456,
        exact_message_hash=signed.exact_message_hash,
        signed_wire_hash=signed.signed_wire_hash,
        instruction_hash=digest_b,
        fee_lamports=5_000,
        payer_delta_lamports=25_000,
        token_delta_hash=digest_c,
        realized_pnl_lamports=19_000,
        selected_transport=signed.selected_transport,
        tip_lamports=signed.tip_lamports,
    )
    reconciliation = reconcile_finalized_settlement(intent=intent, settlement=settlement)
    latch = evaluate_canary_latches(
        budget=CanaryBudget(
            wallet=authorization.wallet,
            market=authorization.market,
            asset=authorization.asset,
            max_count=1,
            max_notional_lamports=100_000,
            max_tip_lamports=2_000,
            max_daily_loss_lamports=10_000,
            max_total_loss_lamports=20_000,
            not_before_unix_ns=100,
            not_after_unix_ns=1_000,
            evidence_bundle_hash=authorization.evidence_bundle_hash,
        ),
        usage=CanaryUsage(
            count=1,
            notional_lamports=50_000,
            tip_lamports=1_000,
            daily_loss_lamports=0,
            total_loss_lamports=0,
        ),
        trusted_now_unix_ns=500,
        second_reviewer_present=True,
        evidence_bundle_hash=authorization.evidence_bundle_hash,
    )
    submission_blockers = validate_submission_identity(
        permit=permit,
        authorization=authorization,
        signed_wire=signed,
        tip_evidence=tip,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "permit_state": validation.state.value,
        "permit_blockers": [asdict(item) for item in validation.blockers],
        "submission_blockers": [asdict(item) for item in submission_blockers],
        "reconciliation_state": reconciliation.state.value,
        "reconciliation_blockers": [asdict(item) for item in reconciliation.blockers],
        "canary_state": latch.state.value,
        "canary_blockers": [asdict(item) for item in latch.blockers],
        "unrestricted_live_allowed": False,
        "finalized_settlement": reconciliation.finalized_settlement,
        "manual_review_required": reconciliation.manual_review_required,
        "realized_pnl_lamports": reconciliation.realized_pnl_lamports,
    }


def _assert_blockheight_valid(
    *,
    current_block_height: int,
    last_valid_block_height: int,
    safety_margin_blocks: int,
) -> None:
    _strict_positive_int(current_block_height, "current_block_height")
    _strict_positive_int(last_valid_block_height, "last_valid_block_height")
    _strict_non_negative_int(safety_margin_blocks, "safety_margin_blocks")
    if current_block_height + safety_margin_blocks >= last_valid_block_height:
        raise ValueError("PR05_BLOCKHASH_EXPIRED_OR_TOO_CLOSE")


def _strict_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")


def _strict_positive_int(value: int, field_name: str) -> None:
    _strict_int(value, field_name)
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


def _strict_non_negative_int(value: int, field_name: str) -> None:
    _strict_int(value, field_name)
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")


def _sha(value: str, field_name: str) -> None:
    if not isinstance(value, str) or len(value) != _SHA256_HEX_LENGTH:
        raise ValueError(f"{field_name} must be sha256 hex")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be sha256 hex") from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _normalize(value: object) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _normalize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple | list):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    return value


def _add(blockers: list[Blocker], code: str, message: str) -> None:
    blockers.append(Blocker(code=code, message=message))


def _dedupe(blockers: Sequence[Blocker]) -> tuple[Blocker, ...]:
    seen: set[tuple[str, str]] = set()
    unique: list[Blocker] = []
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            unique.append(blocker)
    return tuple(unique)
