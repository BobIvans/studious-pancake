"""SUPER-04 / W2-11 treasury replenishment contracts.

The legacy gas refiller signs and sends directly from src.ingest. This module
deliberately does not: it turns finalized balance evidence into a bounded
treasury intent, binds an already-reviewed quote, and records the operation in
the existing durable lifecycle store. Signing/submission remain owned by
AGG-08 and accounting remains owned by MPR-15.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re

from src.durability import AttemptKey, DurableAttempt, DurableLifecycleStore
from src.execution.models import ExecutionState

SUPER04_TREASURY_SCHEMA = "super04.treasury-replenishment.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class TreasuryReplenishmentError(ValueError):
    """Stable fail-closed planner/binding error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ReplenishmentDisposition(StrEnum):
    NOOP = "noop"
    BLOCKED = "blocked"
    INTENT = "intent"


class ReconciliationStatus(StrEnum):
    FINALIZED = "finalized"
    FAILED = "failed"
    UNKNOWN = "unknown"


def _int(value: int, label: str, *, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise TreasuryReplenishmentError(f"SUPER04_INVALID_{label.upper()}")


def _sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise TreasuryReplenishmentError(f"SUPER04_INVALID_{label.upper()}")


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TreasuryReplenishmentError(f"SUPER04_INVALID_{label.upper()}")


def _hash_json(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class TreasuryBalanceEvidence:
    wallet_pubkey: str
    native_lamports: int
    source_asset_id: str
    source_balance_base_units: int
    source_reserved_base_units: int
    observed_slot: int
    observed_at_ns: int
    evidence_hash: str

    def __post_init__(self) -> None:
        _text(self.wallet_pubkey, "wallet_pubkey")
        _text(self.source_asset_id, "source_asset_id")
        for label in (
            "native_lamports",
            "source_balance_base_units",
            "source_reserved_base_units",
            "observed_slot",
            "observed_at_ns",
        ):
            _int(getattr(self, label), label)
        if self.source_reserved_base_units > self.source_balance_base_units:
            raise TreasuryReplenishmentError(
                "SUPER04_SOURCE_RESERVATION_EXCEEDS_BALANCE"
            )
        _sha(self.evidence_hash, "evidence_hash")

    @property
    def free_source_base_units(self) -> int:
        return self.source_balance_base_units - self.source_reserved_base_units


@dataclass(frozen=True, slots=True)
class ReplenishmentPolicy:
    policy_hash: str
    protected_native_reserve_lamports: int
    target_native_lamports: int
    minimum_bootstrap_fee_lamports: int
    maximum_source_spend_base_units: int
    maximum_balance_age_ns: int
    allowed_source_asset_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _sha(self.policy_hash, "policy_hash")
        for label in (
            "protected_native_reserve_lamports",
            "target_native_lamports",
            "minimum_bootstrap_fee_lamports",
            "maximum_source_spend_base_units",
            "maximum_balance_age_ns",
        ):
            _int(getattr(self, label), label)
        if self.target_native_lamports <= self.protected_native_reserve_lamports:
            raise TreasuryReplenishmentError(
                "SUPER04_TARGET_NOT_ABOVE_PROTECTED_RESERVE"
            )
        if not self.allowed_source_asset_ids or len(
            set(self.allowed_source_asset_ids)
        ) != len(self.allowed_source_asset_ids):
            raise TreasuryReplenishmentError("SUPER04_INVALID_ALLOWED_SOURCE_SET")
        for asset in self.allowed_source_asset_ids:
            _text(asset, "allowed_source_asset")


@dataclass(frozen=True, slots=True)
class TreasuryReplenishmentIntent:
    operation_id: str
    wallet_pubkey: str
    source_asset_id: str
    maximum_source_input_base_units: int
    native_deficit_lamports: int
    balance_evidence_hash: str
    policy_hash: str
    observed_slot: int

    def __post_init__(self) -> None:
        _sha(self.operation_id, "operation_id")
        _text(self.wallet_pubkey, "wallet_pubkey")
        _text(self.source_asset_id, "source_asset_id")
        _int(
            self.maximum_source_input_base_units,
            "maximum_source_input_base_units",
            minimum=1,
        )
        _int(self.native_deficit_lamports, "native_deficit_lamports", minimum=1)
        _sha(self.balance_evidence_hash, "balance_evidence_hash")
        _sha(self.policy_hash, "policy_hash")
        _int(self.observed_slot, "observed_slot")


@dataclass(frozen=True, slots=True)
class ReplenishmentPlanDecision:
    disposition: ReplenishmentDisposition
    reason_code: str
    intent: TreasuryReplenishmentIntent | None


def plan_fee_reserve_replenishment(
    *,
    evidence: TreasuryBalanceEvidence,
    policy: ReplenishmentPolicy,
    trusted_now_ns: int,
) -> ReplenishmentPlanDecision:
    """NF-329: produce a bounded intent without quoting, signing or sending."""

    _int(trusted_now_ns, "trusted_now_ns")
    age = trusted_now_ns - evidence.observed_at_ns
    if age < 0 or age > policy.maximum_balance_age_ns:
        return ReplenishmentPlanDecision(
            ReplenishmentDisposition.BLOCKED,
            "STALE_BALANCE",
            None,
        )
    if evidence.native_lamports >= policy.target_native_lamports:
        return ReplenishmentPlanDecision(
            ReplenishmentDisposition.NOOP,
            "NATIVE_RESERVE_AT_TARGET",
            None,
        )
    if evidence.source_asset_id not in set(policy.allowed_source_asset_ids):
        return ReplenishmentPlanDecision(
            ReplenishmentDisposition.BLOCKED,
            "SOURCE_NOT_ALLOWED",
            None,
        )
    spendable_native = max(
        0,
        evidence.native_lamports - policy.protected_native_reserve_lamports,
    )
    if spendable_native < policy.minimum_bootstrap_fee_lamports:
        return ReplenishmentPlanDecision(
            ReplenishmentDisposition.BLOCKED,
            "NO_BOOTSTRAP_FEE",
            None,
        )
    maximum_source = min(
        evidence.free_source_base_units,
        policy.maximum_source_spend_base_units,
    )
    if maximum_source <= 0:
        return ReplenishmentPlanDecision(
            ReplenishmentDisposition.BLOCKED,
            "SOURCE_RESERVED",
            None,
        )
    deficit = policy.target_native_lamports - evidence.native_lamports
    identity = {
        "schema": SUPER04_TREASURY_SCHEMA,
        "wallet_pubkey": evidence.wallet_pubkey,
        "source_asset_id": evidence.source_asset_id,
        "maximum_source_input_base_units": maximum_source,
        "native_deficit_lamports": deficit,
        "balance_evidence_hash": evidence.evidence_hash,
        "policy_hash": policy.policy_hash,
        "observed_slot": evidence.observed_slot,
    }
    intent = TreasuryReplenishmentIntent(
        operation_id=_hash_json(identity),
        wallet_pubkey=evidence.wallet_pubkey,
        source_asset_id=evidence.source_asset_id,
        maximum_source_input_base_units=maximum_source,
        native_deficit_lamports=deficit,
        balance_evidence_hash=evidence.evidence_hash,
        policy_hash=policy.policy_hash,
        observed_slot=evidence.observed_slot,
    )
    return ReplenishmentPlanDecision(
        ReplenishmentDisposition.INTENT,
        "REPLENISHMENT_INTENT_READY",
        intent,
    )


@dataclass(frozen=True, slots=True)
class ReplenishmentQuoteEvidence:
    quote_id: str
    source_asset_id: str
    source_input_base_units: int
    minimum_native_output_lamports: int
    estimated_network_fee_lamports: int
    estimated_rent_loss_lamports: int
    state_frame_hash: str
    route_hash: str
    expires_at_ns: int

    def __post_init__(self) -> None:
        _text(self.quote_id, "quote_id")
        _text(self.source_asset_id, "source_asset_id")
        for label in (
            "source_input_base_units",
            "minimum_native_output_lamports",
            "estimated_network_fee_lamports",
            "estimated_rent_loss_lamports",
            "expires_at_ns",
        ):
            _int(getattr(self, label), label)
        if (
            self.source_input_base_units <= 0
            or self.minimum_native_output_lamports <= 0
        ):
            raise TreasuryReplenishmentError("SUPER04_EMPTY_REPLENISHMENT_QUOTE")
        _sha(self.state_frame_hash, "state_frame_hash")
        _sha(self.route_hash, "route_hash")

    @property
    def native_execution_budget_lamports(self) -> int:
        return (
            self.estimated_network_fee_lamports
            + self.estimated_rent_loss_lamports
        )


@dataclass(frozen=True, slots=True)
class BoundTreasuryReplenishment:
    intent: TreasuryReplenishmentIntent
    quote: ReplenishmentQuoteEvidence
    current_native_lamports: int
    target_native_lamports: int
    plan_hash: str

    @property
    def native_execution_budget_lamports(self) -> int:
        return self.quote.native_execution_budget_lamports


def bind_replenishment_quote(
    *,
    intent: TreasuryReplenishmentIntent,
    quote: ReplenishmentQuoteEvidence,
    current_native_lamports: int,
    target_native_lamports: int,
    trusted_now_ns: int,
) -> BoundTreasuryReplenishment:
    """NF-330: bind amount/state/route and prove the reserve improves."""

    for label, value in (
        ("current_native_lamports", current_native_lamports),
        ("target_native_lamports", target_native_lamports),
        ("trusted_now_ns", trusted_now_ns),
    ):
        _int(value, label)
    if trusted_now_ns >= quote.expires_at_ns:
        raise TreasuryReplenishmentError("QUOTE_EXPIRED")
    if quote.source_asset_id != intent.source_asset_id:
        raise TreasuryReplenishmentError("SOURCE_ASSET_MISMATCH")
    if quote.source_input_base_units > intent.maximum_source_input_base_units:
        raise TreasuryReplenishmentError("SLIPPAGE_BOUND")
    native_after = (
        current_native_lamports
        + quote.minimum_native_output_lamports
        - quote.native_execution_budget_lamports
    )
    if (
        native_after <= current_native_lamports
        or native_after < target_native_lamports
    ):
        raise TreasuryReplenishmentError("NET_RESERVE_NOT_IMPROVED")
    payload = {
        "schema": SUPER04_TREASURY_SCHEMA,
        "intent": asdict(intent),
        "quote": asdict(quote),
        "current_native_lamports": current_native_lamports,
        "target_native_lamports": target_native_lamports,
    }
    return BoundTreasuryReplenishment(
        intent=intent,
        quote=quote,
        current_native_lamports=current_native_lamports,
        target_native_lamports=target_native_lamports,
        plan_hash=_hash_json(payload),
    )


@dataclass(frozen=True, slots=True)
class SourceReservationEvidence:
    reservation_hash: str
    asset_id: str
    reserved_base_units: int
    generation: int
    expires_at_ns: int

    def __post_init__(self) -> None:
        _sha(self.reservation_hash, "reservation_hash")
        _text(self.asset_id, "asset_id")
        _int(self.reserved_base_units, "reserved_base_units", minimum=1)
        _int(self.generation, "generation", minimum=1)
        _int(self.expires_at_ns, "expires_at_ns", minimum=1)


@dataclass(frozen=True, slots=True)
class ReplenishmentReservationReceipt:
    attempt: DurableAttempt
    source_reservation_hash: str
    plan_hash: str


def reserve_replenishment_operation(
    *,
    bound: BoundTreasuryReplenishment,
    source_reservation: SourceReservationEvidence,
    store: DurableLifecycleStore,
    generation: int,
    trusted_now_ns: int,
) -> ReplenishmentReservationReceipt:
    """NF-331: reuse the canonical lifecycle reservation owner."""

    _int(generation, "generation", minimum=1)
    _int(trusted_now_ns, "trusted_now_ns")
    if trusted_now_ns >= source_reservation.expires_at_ns:
        raise TreasuryReplenishmentError("SOURCE_RESERVATION_EXPIRED")
    if source_reservation.asset_id != bound.intent.source_asset_id:
        raise TreasuryReplenishmentError("SOURCE_RESERVATION_ASSET_MISMATCH")
    if (
        source_reservation.reserved_base_units
        < bound.quote.source_input_base_units
    ):
        raise TreasuryReplenishmentError("SOURCE_RESERVATION_TOO_SMALL")
    key = AttemptKey(
        logical_opportunity_id=f"treasury:{bound.intent.operation_id}",
        plan_hash=bound.plan_hash,
        generation=generation,
    )
    reservation_id = "treasury-native-" + bound.plan_hash
    attempt = store.create_attempt(
        key,
        idempotency_key="treasury-create:" + bound.plan_hash,
        state=ExecutionState.PLANNED,
        reservation_id=reservation_id,
        candidate_id=bound.intent.operation_id,
        reserved_lamports=bound.native_execution_budget_lamports,
        payload={
            "schema": SUPER04_TREASURY_SCHEMA,
            "operation_id": bound.intent.operation_id,
            "plan_hash": bound.plan_hash,
            "source_reservation_hash": source_reservation.reservation_hash,
            "source_asset_id": source_reservation.asset_id,
            "source_reserved_base_units": str(
                source_reservation.reserved_base_units
            ),
            "native_execution_budget_lamports": str(
                bound.native_execution_budget_lamports
            ),
            "live_enabled": False,
        },
    )
    return ReplenishmentReservationReceipt(
        attempt=attempt,
        source_reservation_hash=source_reservation.reservation_hash,
        plan_hash=bound.plan_hash,
    )


@dataclass(frozen=True, slots=True)
class TreasuryReplenishmentPosting:
    operation_id: str
    plan_hash: str
    status: ReconciliationStatus
    source_asset_id: str
    source_spent_base_units: int | None
    native_received_lamports: int | None
    actual_network_fee_lamports: int | None
    actual_rent_loss_lamports: int | None
    native_reserve_after_lamports: int | None
    evidence_hash: str
    release_reservation: bool
    strategy_pnl_lamports: int = 0


def reconcile_replenishment_operation(
    *,
    bound: BoundTreasuryReplenishment,
    status: ReconciliationStatus,
    evidence_hash: str,
    source_spent_base_units: int | None = None,
    native_received_lamports: int | None = None,
    actual_network_fee_lamports: int | None = None,
    actual_rent_loss_lamports: int | None = None,
    native_reserve_after_lamports: int | None = None,
) -> TreasuryReplenishmentPosting:
    """NF-332: classify finalized/failed/unknown without inventing trading PnL."""

    _sha(evidence_hash, "evidence_hash")
    values = (
        source_spent_base_units,
        native_received_lamports,
        actual_network_fee_lamports,
        actual_rent_loss_lamports,
        native_reserve_after_lamports,
    )
    if status is ReconciliationStatus.UNKNOWN:
        if any(value is not None for value in values):
            raise TreasuryReplenishmentError(
                "UNKNOWN_OUTCOME_MUST_NOT_INVENT_DELTAS"
            )
        return TreasuryReplenishmentPosting(
            operation_id=bound.intent.operation_id,
            plan_hash=bound.plan_hash,
            status=status,
            source_asset_id=bound.intent.source_asset_id,
            source_spent_base_units=None,
            native_received_lamports=None,
            actual_network_fee_lamports=None,
            actual_rent_loss_lamports=None,
            native_reserve_after_lamports=None,
            evidence_hash=evidence_hash,
            release_reservation=False,
        )
    if any(value is None for value in values):
        raise TreasuryReplenishmentError(
            "FINALIZED_OUTCOME_REQUIRES_COMPLETE_DELTAS"
        )
    assert source_spent_base_units is not None
    assert native_received_lamports is not None
    assert actual_network_fee_lamports is not None
    assert actual_rent_loss_lamports is not None
    assert native_reserve_after_lamports is not None
    for label, value in (
        ("source_spent_base_units", source_spent_base_units),
        ("native_received_lamports", native_received_lamports),
        ("actual_network_fee_lamports", actual_network_fee_lamports),
        ("actual_rent_loss_lamports", actual_rent_loss_lamports),
        ("native_reserve_after_lamports", native_reserve_after_lamports),
    ):
        _int(value, label)
    if source_spent_base_units > bound.quote.source_input_base_units:
        raise TreasuryReplenishmentError("SOURCE_SPEND_EXCEEDS_BOUND_QUOTE")
    if status is ReconciliationStatus.FINALIZED:
        if (
            native_received_lamports
            < bound.quote.minimum_native_output_lamports
        ):
            raise TreasuryReplenishmentError("FINALIZED_MIN_OUTPUT_BREACHED")
        expected_after = (
            bound.current_native_lamports
            + native_received_lamports
            - actual_network_fee_lamports
            - actual_rent_loss_lamports
        )
        if native_reserve_after_lamports != expected_after:
            raise TreasuryReplenishmentError(
                "FINALIZED_BALANCE_DELTA_MISMATCH"
            )
    return TreasuryReplenishmentPosting(
        operation_id=bound.intent.operation_id,
        plan_hash=bound.plan_hash,
        status=status,
        source_asset_id=bound.intent.source_asset_id,
        source_spent_base_units=source_spent_base_units,
        native_received_lamports=native_received_lamports,
        actual_network_fee_lamports=actual_network_fee_lamports,
        actual_rent_loss_lamports=actual_rent_loss_lamports,
        native_reserve_after_lamports=native_reserve_after_lamports,
        evidence_hash=evidence_hash,
        release_reservation=True,
        strategy_pnl_lamports=0,
    )


__all__ = [
    "BoundTreasuryReplenishment",
    "ReconciliationStatus",
    "ReplenishmentDisposition",
    "ReplenishmentPlanDecision",
    "ReplenishmentPolicy",
    "ReplenishmentQuoteEvidence",
    "ReplenishmentReservationReceipt",
    "SourceReservationEvidence",
    "SUPER04_TREASURY_SCHEMA",
    "TreasuryBalanceEvidence",
    "TreasuryReplenishmentError",
    "TreasuryReplenishmentIntent",
    "TreasuryReplenishmentPosting",
    "bind_replenishment_quote",
    "plan_fee_reserve_replenishment",
    "reconcile_replenishment_operation",
    "reserve_replenishment_operation",
]
