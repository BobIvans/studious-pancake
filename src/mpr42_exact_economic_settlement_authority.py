"""MPR-42 exact economic, transaction and finalized-settlement authority.

This module is intentionally offline, deterministic and fail-closed. It does not
sign, submit, poll RPC/Jito, load keys, or enable live trading. It defines the
artifact contract that must link one immutable message digest through planning,
fee proof, capital reservation, exact final simulation, paper/live PnL layers and
future finalized settlement.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any

SCHEMA_VERSION = "mpr42.exact-economic-settlement-authority.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MPR42State(str, Enum):
    READY_FOR_FOUNDATION = "ready_for_mpr42_foundation"
    BLOCKED = "blocked"


class EconomicLayer(str, Enum):
    EXPECTED = "expected"
    SIMULATED = "simulated"
    PAPER_REALIZED = "paper_realized"
    LIVE_REALIZED = "live_realized"


class SettlementStatus(str, Enum):
    NONE = "none"
    RPC_ACK = "rpc_ack"
    JITO_ACK = "jito_ack"
    SUBMITTED = "submitted"
    LANDED = "landed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    UNRESOLVED = "unresolved"


class QuarantineReason(str, Enum):
    UNKNOWN_SIGNATURE_STATUS = "unknown_signature_status"
    FORK_DISAGREEMENT = "fork_disagreement"
    PARTIAL_ACCOUNT_LOOKUP = "partial_account_lookup"
    MISSING_FINALIZED_DATA = "missing_finalized_data"
    MESSAGE_DRIFT = "message_drift"


@dataclass(frozen=True)
class AssetAmount:
    asset_id: str
    atomic_value: int
    decimals: int
    metadata_digest: str
    allow_negative: bool = False

    def __post_init__(self) -> None:
        _text(self.asset_id, "asset_id")
        _strict_int(self.atomic_value, "atomic_value")
        _strict_int(self.decimals, "decimals")
        if self.decimals < 0 or self.decimals > 18:
            raise ValueError("MPR42_DECIMALS_OUT_OF_RANGE")
        if self.atomic_value < 0 and not self.allow_negative:
            raise ValueError("MPR42_NEGATIVE_AMOUNT")
        _sha(self.metadata_digest, "metadata_digest")


@dataclass(frozen=True)
class CostBreakdown:
    transaction_fee_lamports: int
    priority_fee_lamports: int
    jito_tip_lamports: int
    ata_rent_lamports: int
    wsol_rent_lamports: int
    cleanup_refund_lamports: int
    flashloan_fee_lamports: int
    flashloan_repayment_lamports: int
    retry_budget_lamports: int
    total_cost_lamports: int
    bound_message_hash: str
    fee_quote_digest: str

    def __post_init__(self) -> None:
        values = (
            self.transaction_fee_lamports,
            self.priority_fee_lamports,
            self.jito_tip_lamports,
            self.ata_rent_lamports,
            self.wsol_rent_lamports,
            self.cleanup_refund_lamports,
            self.flashloan_fee_lamports,
            self.flashloan_repayment_lamports,
            self.retry_budget_lamports,
            self.total_cost_lamports,
        )
        for name, value in zip(
            (
                "transaction_fee_lamports",
                "priority_fee_lamports",
                "jito_tip_lamports",
                "ata_rent_lamports",
                "wsol_rent_lamports",
                "cleanup_refund_lamports",
                "flashloan_fee_lamports",
                "flashloan_repayment_lamports",
                "retry_budget_lamports",
                "total_cost_lamports",
            ),
            values,
            strict=True,
        ):
            _strict_int(value, name)
            if value < 0:
                raise ValueError("MPR42_NEGATIVE_COST")
        expected_total = (
            self.transaction_fee_lamports
            + self.priority_fee_lamports
            + self.jito_tip_lamports
            + self.ata_rent_lamports
            + self.wsol_rent_lamports
            - self.cleanup_refund_lamports
            + self.flashloan_fee_lamports
            + self.flashloan_repayment_lamports
            + self.retry_budget_lamports
        )
        if self.total_cost_lamports != expected_total:
            raise ValueError("MPR42_COST_TOTAL_MISMATCH")
        _sha(self.bound_message_hash, "bound_message_hash")
        _sha(self.fee_quote_digest, "fee_quote_digest")


@dataclass(frozen=True)
class TransactionPlanProof:
    attempt_id: str
    attempt_generation: int
    plan_digest: str
    immutable_message_hash: str
    compiled_message_hash: str
    final_simulation_message_hash: str
    recent_blockhash_hash: str
    observed_block_height: int
    last_valid_block_height: int
    min_remaining_block_height_margin: int
    lookup_tables_digest: str
    program_account_policy_digest: str
    exact_fee_message_hash: str
    compute_budget_digest: str
    ata_wsol_lifecycle_digest: str
    flashloan_repayment_digest: str

    def __post_init__(self) -> None:
        _text(self.attempt_id, "attempt_id")
        _strict_int(self.attempt_generation, "attempt_generation")
        if self.attempt_generation < 1:
            raise ValueError("MPR42_ATTEMPT_GENERATION_MIN_ONE")
        for name in (
            "plan_digest",
            "immutable_message_hash",
            "compiled_message_hash",
            "final_simulation_message_hash",
            "recent_blockhash_hash",
            "lookup_tables_digest",
            "program_account_policy_digest",
            "exact_fee_message_hash",
            "compute_budget_digest",
            "ata_wsol_lifecycle_digest",
            "flashloan_repayment_digest",
        ):
            _sha(getattr(self, name), name)
        for name in (
            "observed_block_height",
            "last_valid_block_height",
            "min_remaining_block_height_margin",
        ):
            value = getattr(self, name)
            _strict_int(value, name)
            if value < 0:
                raise ValueError("MPR42_NEGATIVE_BLOCK_HEIGHT")
        if self.compiled_message_hash != self.immutable_message_hash:
            raise ValueError("MPR42_COMPILED_MESSAGE_DRIFT")
        if self.final_simulation_message_hash != self.immutable_message_hash:
            raise ValueError("MPR42_FINAL_SIM_MESSAGE_DRIFT")
        if self.exact_fee_message_hash != self.immutable_message_hash:
            raise ValueError("MPR42_FEE_MESSAGE_DRIFT")
        remaining = self.last_valid_block_height - self.observed_block_height
        if remaining < self.min_remaining_block_height_margin:
            raise ValueError("MPR42_BLOCKHASH_MARGIN_EXPIRED")


@dataclass(frozen=True)
class FinalSimulationProof:
    simulated_message_hash: str
    simulation_success: bool
    context_slot: int
    min_context_slot: int
    raw_pre_account_hash: str
    raw_post_account_hash: str
    decoded_from_raw_state: bool
    monitored_accounts_digest: str
    simulation_trace_digest: str

    def __post_init__(self) -> None:
        for name in (
            "simulated_message_hash",
            "raw_pre_account_hash",
            "raw_post_account_hash",
            "monitored_accounts_digest",
            "simulation_trace_digest",
        ):
            _sha(getattr(self, name), name)
        _strict_bool(self.simulation_success, "simulation_success")
        _strict_bool(self.decoded_from_raw_state, "decoded_from_raw_state")
        _strict_int(self.context_slot, "context_slot")
        _strict_int(self.min_context_slot, "min_context_slot")
        if self.context_slot < 0 or self.min_context_slot < 1:
            raise ValueError("MPR42_INVALID_CONTEXT_SLOT")
        if self.context_slot < self.min_context_slot:
            raise ValueError("MPR42_CONTEXT_SLOT_REGRESSION")


@dataclass(frozen=True)
class CapitalReservationProof:
    reservation_id: str
    reservation_digest: str
    attempt_id: str
    attempt_generation: int
    message_hash: str
    reserved_lamports: int
    required_lamports: int
    active_until_height: int
    unresolved_capital_reuse_blocked: bool

    def __post_init__(self) -> None:
        _text(self.reservation_id, "reservation_id")
        _text(self.attempt_id, "attempt_id")
        _sha(self.reservation_digest, "reservation_digest")
        _sha(self.message_hash, "message_hash")
        for name in (
            "attempt_generation",
            "reserved_lamports",
            "required_lamports",
            "active_until_height",
        ):
            value = getattr(self, name)
            _strict_int(value, name)
            if value < 0:
                raise ValueError("MPR42_NEGATIVE_RESERVATION_FIELD")
        if self.attempt_generation < 1:
            raise ValueError("MPR42_RESERVATION_GENERATION_MIN_ONE")
        _strict_bool(
            self.unresolved_capital_reuse_blocked,
            "unresolved_capital_reuse_blocked",
        )
        if self.reserved_lamports < self.required_lamports:
            raise ValueError("MPR42_UNDER_RESERVED_CAPITAL")


@dataclass(frozen=True)
class PnLLayerEvidence:
    layer: EconomicLayer
    message_hash: str
    gross: AssetAmount
    costs: CostBreakdown
    net: AssetAmount
    provenance_digest: str
    strict_positive_threshold_atomic: int

    def __post_init__(self) -> None:
        _sha(self.message_hash, "message_hash")
        _sha(self.provenance_digest, "provenance_digest")
        _strict_int(
            self.strict_positive_threshold_atomic,
            "strict_positive_threshold_atomic",
        )
        if self.strict_positive_threshold_atomic < 0:
            raise ValueError("MPR42_NEGATIVE_PROFIT_THRESHOLD")
        if self.gross.asset_id != self.net.asset_id:
            raise ValueError("MPR42_PNL_ASSET_MISMATCH")
        if self.costs.bound_message_hash != self.message_hash:
            raise ValueError("MPR42_PNL_COST_MESSAGE_MISMATCH")
        expected_net = self.gross.atomic_value - self.costs.total_cost_lamports
        if self.net.atomic_value != expected_net:
            raise ValueError("MPR42_NET_PNL_MISMATCH")
        if self.layer is EconomicLayer.LIVE_REALIZED and self.net.atomic_value <= self.strict_positive_threshold_atomic:
            raise ValueError("MPR42_LIVE_REALIZED_NOT_STRICTLY_POSITIVE")


@dataclass(frozen=True)
class FinalizedSettlementProof:
    status: SettlementStatus
    message_hash: str
    signature_hash: str | None
    finalized_slot: int | None
    payer_delta_hash: str | None
    token_delta_hash: str | None
    economic_ledger_hash: str | None
    ack_or_bundle_id_used_as_profit: bool = False

    def __post_init__(self) -> None:
        _sha(self.message_hash, "message_hash")
        for name in (
            "signature_hash",
            "payer_delta_hash",
            "token_delta_hash",
            "economic_ledger_hash",
        ):
            _optional_sha(getattr(self, name), name)
        if self.finalized_slot is not None:
            _strict_int(self.finalized_slot, "finalized_slot")
            if self.finalized_slot < 0:
                raise ValueError("MPR42_NEGATIVE_FINALIZED_SLOT")
        _strict_bool(
            self.ack_or_bundle_id_used_as_profit,
            "ack_or_bundle_id_used_as_profit",
        )


@dataclass(frozen=True)
class AmbiguityQuarantine:
    unresolved: bool
    reasons: tuple[QuarantineReason, ...]
    capital_reuse_blocked: bool
    manual_review_required: bool
    quarantine_digest: str

    def __post_init__(self) -> None:
        _strict_bool(self.unresolved, "unresolved")
        _strict_bool(self.capital_reuse_blocked, "capital_reuse_blocked")
        _strict_bool(self.manual_review_required, "manual_review_required")
        if not isinstance(self.reasons, tuple):
            raise ValueError("MPR42_QUARANTINE_REASONS_TUPLE_REQUIRED")
        _sha(self.quarantine_digest, "quarantine_digest")


@dataclass(frozen=True)
class MPR42Evidence:
    plan: TransactionPlanProof
    simulation: FinalSimulationProof
    reservation: CapitalReservationProof
    pnl_layers: tuple[PnLLayerEvidence, ...]
    settlement: FinalizedSettlementProof
    quarantine: AmbiguityQuarantine
    duplicate_submission_guard_digest: str
    unrestricted_live_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.pnl_layers, tuple) or not self.pnl_layers:
            raise ValueError("MPR42_PNL_LAYERS_REQUIRED")
        _sha(
            self.duplicate_submission_guard_digest,
            "duplicate_submission_guard_digest",
        )
        _strict_bool(self.unrestricted_live_enabled, "unrestricted_live_enabled")


@dataclass(frozen=True)
class MPR42Blocker:
    code: str
    message: str


@dataclass(frozen=True)
class MPR42Report:
    schema_version: str
    state: MPR42State
    blockers: tuple[MPR42Blocker, ...]
    evidence_hash: str
    layers_present: tuple[str, ...]
    message_hash: str
    live_execution_allowed: bool
    realized_settlement_allowed: bool
    capital_reuse_allowed: bool


def evaluate_mpr42_evidence(evidence: MPR42Evidence) -> MPR42Report:
    """Evaluate the fail-closed MPR-42 evidence contract."""
    blockers: list[MPR42Blocker] = []
    message_hash = evidence.plan.immutable_message_hash

    _require_same_message(evidence, blockers, message_hash)
    _validate_simulation(evidence, blockers, message_hash)
    _validate_reservation(evidence, blockers, message_hash)
    _validate_pnl_layers(evidence, blockers, message_hash)
    _validate_settlement(evidence, blockers, message_hash)
    _validate_quarantine(evidence, blockers)
    if evidence.unrestricted_live_enabled:
        _add(blockers, "MPR42_UNRESTRICTED_LIVE_FORBIDDEN", "MPR-42 must not enable unrestricted live")

    unique = tuple(_dedupe(blockers))
    layers = tuple(sorted({item.layer.value for item in evidence.pnl_layers}))
    realized_allowed = not any(item.layer is EconomicLayer.LIVE_REALIZED for item in evidence.pnl_layers) or (
        evidence.settlement.status is SettlementStatus.FINALIZED and not unique
    )
    capital_reuse_allowed = not evidence.quarantine.unresolved and not unique
    return MPR42Report(
        schema_version=SCHEMA_VERSION,
        state=MPR42State.BLOCKED if unique else MPR42State.READY_FOR_FOUNDATION,
        blockers=unique,
        evidence_hash=_hash_dataclass(evidence),
        layers_present=layers,
        message_hash=message_hash,
        live_execution_allowed=False,
        realized_settlement_allowed=realized_allowed and not unique,
        capital_reuse_allowed=capital_reuse_allowed,
    )


def sample_ready_evidence() -> MPR42Evidence:
    message_hash = _repeat_hash("message")
    metadata_hash = _repeat_hash("metadata")
    cost = CostBreakdown(
        transaction_fee_lamports=5_000,
        priority_fee_lamports=2_000,
        jito_tip_lamports=1_000,
        ata_rent_lamports=2_039_280,
        wsol_rent_lamports=2_039_280,
        cleanup_refund_lamports=2_039_280,
        flashloan_fee_lamports=8_000,
        flashloan_repayment_lamports=100_000,
        retry_budget_lamports=10_000,
        total_cost_lamports=2_165_280,
        bound_message_hash=message_hash,
        fee_quote_digest=_repeat_hash("fee"),
    )
    layers = (
        PnLLayerEvidence(
            layer=EconomicLayer.EXPECTED,
            message_hash=message_hash,
            gross=AssetAmount("SOL", 3_000_000, 9, metadata_hash),
            costs=cost,
            net=AssetAmount("SOL", 834_720, 9, metadata_hash, allow_negative=True),
            provenance_digest=_repeat_hash("expected"),
            strict_positive_threshold_atomic=1,
        ),
        PnLLayerEvidence(
            layer=EconomicLayer.SIMULATED,
            message_hash=message_hash,
            gross=AssetAmount("SOL", 2_900_000, 9, metadata_hash),
            costs=cost,
            net=AssetAmount("SOL", 734_720, 9, metadata_hash, allow_negative=True),
            provenance_digest=_repeat_hash("simulated"),
            strict_positive_threshold_atomic=1,
        ),
        PnLLayerEvidence(
            layer=EconomicLayer.PAPER_REALIZED,
            message_hash=message_hash,
            gross=AssetAmount("SOL", 2_700_000, 9, metadata_hash),
            costs=cost,
            net=AssetAmount("SOL", 534_720, 9, metadata_hash, allow_negative=True),
            provenance_digest=_repeat_hash("paper"),
            strict_positive_threshold_atomic=1,
        ),
    )
    return MPR42Evidence(
        plan=TransactionPlanProof(
            attempt_id="attempt-42",
            attempt_generation=1,
            plan_digest=_repeat_hash("plan"),
            immutable_message_hash=message_hash,
            compiled_message_hash=message_hash,
            final_simulation_message_hash=message_hash,
            recent_blockhash_hash=_repeat_hash("blockhash"),
            observed_block_height=100,
            last_valid_block_height=180,
            min_remaining_block_height_margin=20,
            lookup_tables_digest=_repeat_hash("alts"),
            program_account_policy_digest=_repeat_hash("policy"),
            exact_fee_message_hash=message_hash,
            compute_budget_digest=_repeat_hash("compute"),
            ata_wsol_lifecycle_digest=_repeat_hash("atawsol"),
            flashloan_repayment_digest=_repeat_hash("flashloan"),
        ),
        simulation=FinalSimulationProof(
            simulated_message_hash=message_hash,
            simulation_success=True,
            context_slot=10_000,
            min_context_slot=9_999,
            raw_pre_account_hash=_repeat_hash("pre"),
            raw_post_account_hash=_repeat_hash("post"),
            decoded_from_raw_state=True,
            monitored_accounts_digest=_repeat_hash("accounts"),
            simulation_trace_digest=_repeat_hash("trace"),
        ),
        reservation=CapitalReservationProof(
            reservation_id="reservation-42",
            reservation_digest=_repeat_hash("reservation"),
            attempt_id="attempt-42",
            attempt_generation=1,
            message_hash=message_hash,
            reserved_lamports=3_000_000,
            required_lamports=2_165_280,
            active_until_height=180,
            unresolved_capital_reuse_blocked=True,
        ),
        pnl_layers=layers,
        settlement=FinalizedSettlementProof(
            status=SettlementStatus.NONE,
            message_hash=message_hash,
            signature_hash=None,
            finalized_slot=None,
            payer_delta_hash=None,
            token_delta_hash=None,
            economic_ledger_hash=None,
        ),
        quarantine=AmbiguityQuarantine(
            unresolved=False,
            reasons=(),
            capital_reuse_blocked=False,
            manual_review_required=False,
            quarantine_digest=_repeat_hash("quarantine"),
        ),
        duplicate_submission_guard_digest=_repeat_hash("duplicate"),
    )


def _require_same_message(evidence: MPR42Evidence, blockers: list[MPR42Blocker], message_hash: str) -> None:
    checks = {
        "simulation": evidence.simulation.simulated_message_hash,
        "reservation": evidence.reservation.message_hash,
        "settlement": evidence.settlement.message_hash,
    }
    for label, observed in checks.items():
        if observed != message_hash:
            _add(blockers, "MPR42_MESSAGE_HASH_DRIFT", f"{label} message hash differs")


def _validate_simulation(evidence: MPR42Evidence, blockers: list[MPR42Blocker], message_hash: str) -> None:
    simulation = evidence.simulation
    if simulation.simulated_message_hash != message_hash:
        _add(blockers, "MPR42_EXACT_SIMULATION_NOT_BOUND", "final simulation is not bound to immutable message")
    if not simulation.simulation_success:
        _add(blockers, "MPR42_FINAL_SIMULATION_FAILED", "admission requires successful exact final simulation")
    if not simulation.decoded_from_raw_state:
        _add(blockers, "MPR42_CALLER_DECODED_ECONOMICS", "economics must decode from preserved raw account state")


def _validate_reservation(evidence: MPR42Evidence, blockers: list[MPR42Blocker], message_hash: str) -> None:
    reservation = evidence.reservation
    if reservation.message_hash != message_hash:
        _add(blockers, "MPR42_RESERVATION_MESSAGE_MISMATCH", "capital reservation must bind exact message")
    if reservation.attempt_id != evidence.plan.attempt_id:
        _add(blockers, "MPR42_RESERVATION_ATTEMPT_MISMATCH", "reservation attempt differs from plan")
    if reservation.attempt_generation != evidence.plan.attempt_generation:
        _add(blockers, "MPR42_RESERVATION_GENERATION_MISMATCH", "reservation generation differs from plan")
    if reservation.reserved_lamports < reservation.required_lamports:
        _add(blockers, "MPR42_UNDER_RESERVED_CAPITAL", "reservation does not cover required capital")


def _validate_pnl_layers(evidence: MPR42Evidence, blockers: list[MPR42Blocker], message_hash: str) -> None:
    seen_layers: set[EconomicLayer] = set()
    for layer in evidence.pnl_layers:
        seen_layers.add(layer.layer)
        if layer.message_hash != message_hash:
            _add(blockers, "MPR42_PNL_MESSAGE_MISMATCH", f"{layer.layer.value} PnL is not message-bound")
        if layer.costs.bound_message_hash != message_hash:
            _add(blockers, "MPR42_COST_MESSAGE_MISMATCH", f"{layer.layer.value} costs are not message-bound")
        if not isinstance(layer.net.atomic_value, int) or isinstance(layer.net.atomic_value, bool):
            _add(blockers, "MPR42_NON_INTEGER_PNL", "PnL must be integer atomic units")
    required = {EconomicLayer.EXPECTED, EconomicLayer.SIMULATED, EconomicLayer.PAPER_REALIZED}
    if not required.issubset(seen_layers):
        missing = ", ".join(sorted(item.value for item in required - seen_layers))
        _add(blockers, "MPR42_REQUIRED_PNL_LAYER_MISSING", "missing: " + missing)


def _validate_settlement(evidence: MPR42Evidence, blockers: list[MPR42Blocker], message_hash: str) -> None:
    settlement = evidence.settlement
    if settlement.ack_or_bundle_id_used_as_profit:
        _add(blockers, "MPR42_ACK_USED_AS_PROFIT", "RPC/Jito ACK or bundle id is not settlement")
    has_live_realized = any(layer.layer is EconomicLayer.LIVE_REALIZED for layer in evidence.pnl_layers)
    if has_live_realized:
        if settlement.status is not SettlementStatus.FINALIZED:
            _add(blockers, "MPR42_LIVE_REALIZED_WITHOUT_FINALITY", "live-realized PnL requires finalized settlement")
        missing = [
            name
            for name in (
                "signature_hash",
                "payer_delta_hash",
                "token_delta_hash",
                "economic_ledger_hash",
                "finalized_slot",
            )
            if getattr(settlement, name) is None
        ]
        if missing:
            _add(blockers, "MPR42_FINALIZED_SETTLEMENT_INCOMPLETE", "missing: " + ", ".join(missing))
    if settlement.status in {SettlementStatus.RPC_ACK, SettlementStatus.JITO_ACK, SettlementStatus.SUBMITTED, SettlementStatus.LANDED}:
        if has_live_realized:
            _add(blockers, "MPR42_TRANSPORT_STATUS_NOT_FINAL", "transport/landing status cannot support realized economics")
    if settlement.message_hash != message_hash:
        _add(blockers, "MPR42_SETTLEMENT_MESSAGE_MISMATCH", "settlement must bind exact message")


def _validate_quarantine(evidence: MPR42Evidence, blockers: list[MPR42Blocker]) -> None:
    quarantine = evidence.quarantine
    if quarantine.unresolved:
        if not quarantine.reasons:
            _add(blockers, "MPR42_QUARANTINE_REASON_REQUIRED", "unresolved state needs a reason")
        if not quarantine.capital_reuse_blocked:
            _add(blockers, "MPR42_UNRESOLVED_CAPITAL_REUSE", "unresolved state must block capital reuse")
        if not quarantine.manual_review_required:
            _add(blockers, "MPR42_UNRESOLVED_WITHOUT_MANUAL_REVIEW", "unresolved state requires manual review")
    if evidence.settlement.status is SettlementStatus.UNRESOLVED and not quarantine.unresolved:
        _add(blockers, "MPR42_UNRESOLVED_NOT_QUARANTINED", "unresolved settlement must enter quarantine")


def _add(blockers: list[MPR42Blocker], code: str, message: str) -> None:
    blockers.append(MPR42Blocker(code=code, message=message))


def _dedupe(blockers: Iterable[MPR42Blocker]) -> list[MPR42Blocker]:
    seen: set[str] = set()
    output: list[MPR42Blocker] = []
    for blocker in blockers:
        if blocker.code in seen:
            continue
        seen.add(blocker.code)
        output.append(blocker)
    return output


def _hash_dataclass(value: object) -> str:
    encoded = json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def _repeat_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _sha(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 hex digest")


def _optional_sha(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _sha(value, field_name)


def _text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")


def _strict_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be a strict integer")


def _strict_bool(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be bool")


def reject_non_finite_number(value: object, field_name: str) -> None:
    """Public helper for boundary tests that reject float/NaN/Infinity ingress."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must not be bool")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must be finite")
        raise ValueError(f"{field_name} must not be float")
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be integer")
