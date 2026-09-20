"""AGG-13 research and qualification gates for non-atomic market families.

These helpers make feasibility claims narrower, not broader. They never place
orders and never convert statistical association, public data, bridge latency or
redemption assumptions into atomic execution rights.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,191}$")


class ResearchError(ValueError):
    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code if message is None else f"{reason_code}: {message}")


class StrategyFamily(StrEnum):
    FUNDING_BASIS = "funding_basis"
    CALENDAR = "calendar"
    CROSS_VENUE = "cross_venue"
    CROSS_CHAIN = "cross_chain"
    MARKET_MAKING = "market_making"
    LP_HEDGE = "lp_hedge"
    OPTIONS_PARITY = "options_parity"
    OPTIONS_VOL = "options_volatility"
    COMPLETE_SET = "complete_set"
    STAT_BASKET = "statistical_basket"
    RWA_RIGHTS = "rwa_rights"
    TOKENIZED_METAL_FX = "tokenized_metal_fx"
    EQUITY_BASKET = "equity_basket"
    COMMODITY = "commodity_spread"
    PREIPO = "preipo"
    FIAT_P2P = "fiat_p2p"


class Disposition(StrEnum):
    BLOCKED = "blocked"
    RESEARCH_ONLY = "research_only"
    QUALIFIABLE = "qualifiable"


_RESEARCH_ONLY = frozenset(
    {
        StrategyFamily.COMMODITY,
        StrategyFamily.PREIPO,
        StrategyFamily.FIAT_P2P,
    }
)


@dataclass(frozen=True, slots=True)
class MarketRights:
    venue: str
    instrument: str
    market_data_allowed: bool
    trading_access_verified: bool
    settlement_verified: bool
    session_open: bool
    redemption_right_verified: bool = False
    compliance_access_verified: bool = False
    rights_evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.venue, "venue")
        _require_id(self.instrument, "instrument")
        if self.rights_evidence_sha256 is not None:
            _require_sha256(
                self.rights_evidence_sha256,
                "rights_evidence_sha256",
            )


@dataclass(frozen=True, slots=True)
class NonAtomicHypothesis:
    family: StrategyFamily
    hypothesis_id: str
    leg_ids: tuple[str, ...]
    atomic_claim: bool
    prefunded_inventory: bool
    hedge_plan_verified: bool
    funding_schedule_verified: bool
    margin_stress_passed: bool
    statistical_controls_verified: bool
    transfer_required_for_same_cycle: bool
    max_unhedged_loss_quote_units: int
    tail_loss_budget_quote_units: int
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.hypothesis_id, "hypothesis_id")
        if len(self.leg_ids) < 2:
            raise ResearchError("AGG13_AT_LEAST_TWO_LEGS_REQUIRED")
        for leg_id in self.leg_ids:
            _require_id(leg_id, "leg_id")
        if len(set(self.leg_ids)) != len(self.leg_ids):
            raise ResearchError("AGG13_DUPLICATE_LEG_ID")
        _require_nonnegative_int(
            self.max_unhedged_loss_quote_units,
            "max_unhedged_loss_quote_units",
        )
        _require_nonnegative_int(
            self.tail_loss_budget_quote_units,
            "tail_loss_budget_quote_units",
        )
        _require_sha256(self.evidence_sha256, "evidence_sha256")


@dataclass(frozen=True, slots=True)
class HypothesisVerdict:
    hypothesis_id: str
    disposition: Disposition
    blockers: tuple[str, ...]
    atomic_execution_allowed: bool


@dataclass(frozen=True, slots=True)
class AllocationCandidate:
    candidate_id: str
    requested_quote_units: int
    capacity_quote_units: int
    worst_loss_for_requested_quote_units: int
    priority: int
    model_scale_bps: int = 10_000

    def __post_init__(self) -> None:
        _require_id(self.candidate_id, "candidate_id")
        _require_positive_int(
            self.requested_quote_units,
            "requested_quote_units",
        )
        _require_nonnegative_int(
            self.capacity_quote_units,
            "capacity_quote_units",
        )
        _require_nonnegative_int(
            self.worst_loss_for_requested_quote_units,
            "worst_loss_for_requested_quote_units",
        )
        _require_nonnegative_int(self.priority, "priority")
        _require_positive_int(self.model_scale_bps, "model_scale_bps")
        if self.model_scale_bps > 10_000:
            raise ResearchError(
                "AGG13_MODEL_CANNOT_INCREASE_REVIEWED_EXPOSURE"
            )


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    allocations: tuple[tuple[str, int], ...]
    unallocated_quote_units: int
    remaining_tail_loss_budget_quote_units: int


@dataclass(frozen=True, slots=True)
class InventoryQualificationEvidence:
    restart_replay_passed: bool
    partial_fill_model_passed: bool
    actual_reconciliation_passed: bool
    disconnect_recovery_passed: bool
    funding_flip_stress_passed: bool
    margin_shock_passed: bool
    instrument_access_verified: bool
    scope_sha256: str

    def __post_init__(self) -> None:
        _require_sha256(self.scope_sha256, "scope_sha256")


@dataclass(frozen=True, slots=True)
class InventoryQualificationVerdict:
    qualified: bool
    scope_sha256: str
    blockers: tuple[str, ...]
    live_authorized: bool = False


def evaluate_hypothesis(
    hypothesis: NonAtomicHypothesis,
    *,
    rights: tuple[MarketRights, ...],
) -> HypothesisVerdict:
    blockers: list[str] = []
    if hypothesis.atomic_claim:
        blockers.append(
            "AGG13_NON_ATOMIC_STRATEGY_CANNOT_CLAIM_ATOMIC_EXECUTION"
        )
    if (
        hypothesis.max_unhedged_loss_quote_units
        > hypothesis.tail_loss_budget_quote_units
    ):
        blockers.append("AGG13_UNHEDGED_LOSS_EXCEEDS_TAIL_BUDGET")
    if len(rights) != len(hypothesis.leg_ids):
        blockers.append("AGG13_RIGHTS_CLOSURE_INCOMPLETE")
    for right in rights:
        if not right.market_data_allowed:
            blockers.append("AGG13_MARKET_DATA_RIGHT_MISSING")
        if not right.trading_access_verified:
            blockers.append("AGG13_TRADING_ACCESS_UNVERIFIED")
        if not right.settlement_verified:
            blockers.append("AGG13_SETTLEMENT_UNVERIFIED")
        if not right.session_open:
            blockers.append("AGG13_MARKET_SESSION_CLOSED")
        if right.rights_evidence_sha256 is None:
            blockers.append("AGG13_RIGHTS_EVIDENCE_MISSING")

    if hypothesis.family in {
        StrategyFamily.FUNDING_BASIS,
        StrategyFamily.CALENDAR,
        StrategyFamily.LP_HEDGE,
    }:
        if not hypothesis.funding_schedule_verified:
            blockers.append("AGG13_FUNDING_OR_CARRY_SCHEDULE_UNVERIFIED")
        if not hypothesis.margin_stress_passed:
            blockers.append("AGG13_MARGIN_STRESS_NOT_PASSED")

    if hypothesis.family in {
        StrategyFamily.CROSS_VENUE,
        StrategyFamily.CROSS_CHAIN,
        StrategyFamily.MARKET_MAKING,
        StrategyFamily.LP_HEDGE,
    }:
        if not hypothesis.prefunded_inventory:
            blockers.append("AGG13_PREFUNDED_INVENTORY_REQUIRED")
        if not hypothesis.hedge_plan_verified:
            blockers.append("AGG13_HEDGE_OR_RECOVERY_PLAN_UNVERIFIED")

    if (
        hypothesis.family is StrategyFamily.CROSS_CHAIN
        and not hypothesis.transfer_required_for_same_cycle
    ):
        blockers.append("AGG13_CROSS_CHAIN_ROUTE_MUST_MODEL_TRANSFER_FINALITY")

    if hypothesis.family in {
        StrategyFamily.STAT_BASKET,
        StrategyFamily.OPTIONS_VOL,
        StrategyFamily.EQUITY_BASKET,
        StrategyFamily.COMMODITY,
    } and not hypothesis.statistical_controls_verified:
        blockers.append("AGG13_STATISTICAL_CONTROLS_UNVERIFIED")

    if hypothesis.family in {
        StrategyFamily.RWA_RIGHTS,
        StrategyFamily.TOKENIZED_METAL_FX,
        StrategyFamily.EQUITY_BASKET,
    }:
        if not rights or not all(
            item.redemption_right_verified for item in rights
        ):
            blockers.append(
                "AGG13_REDEMPTION_OR_CONVERSION_RIGHT_UNVERIFIED"
            )

    if hypothesis.family in {
        StrategyFamily.PREIPO,
        StrategyFamily.FIAT_P2P,
    }:
        if not rights or not all(
            item.compliance_access_verified for item in rights
        ):
            blockers.append(
                "AGG13_COMPLIANCE_OR_TRANSFER_ACCESS_UNVERIFIED"
            )

    unique_blockers = tuple(dict.fromkeys(blockers))
    if hypothesis.family in _RESEARCH_ONLY:
        disposition = Disposition.RESEARCH_ONLY
    elif unique_blockers:
        disposition = Disposition.BLOCKED
    else:
        disposition = Disposition.QUALIFIABLE
    return HypothesisVerdict(
        hypothesis_id=hypothesis.hypothesis_id,
        disposition=disposition,
        blockers=unique_blockers,
        atomic_execution_allowed=False,
    )


def allocate_inventory_budget(
    *,
    candidates: tuple[AllocationCandidate, ...],
    free_capital_quote_units: int,
    reserved_gas_quote_units: int,
    tail_loss_budget_quote_units: int,
) -> AllocationDecision:
    """Conservative deterministic allocator that never spends the gas reserve."""

    _require_nonnegative_int(
        free_capital_quote_units,
        "free_capital_quote_units",
    )
    _require_nonnegative_int(
        reserved_gas_quote_units,
        "reserved_gas_quote_units",
    )
    _require_nonnegative_int(
        tail_loss_budget_quote_units,
        "tail_loss_budget_quote_units",
    )
    if reserved_gas_quote_units > free_capital_quote_units:
        raise ResearchError("AGG13_RESERVED_GAS_EXCEEDS_FREE_CAPITAL")
    available = free_capital_quote_units - reserved_gas_quote_units
    tail_remaining = tail_loss_budget_quote_units
    allocations: list[tuple[str, int]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item.priority, item.candidate_id),
    ):
        reviewed = min(
            candidate.requested_quote_units,
            candidate.capacity_quote_units,
        )
        reviewed = reviewed * candidate.model_scale_bps // 10_000
        amount = min(reviewed, available)
        if amount <= 0:
            allocations.append((candidate.candidate_id, 0))
            continue
        worst_loss = _scaled_loss_ceiling(
            full_loss=candidate.worst_loss_for_requested_quote_units,
            allocated=amount,
            requested=candidate.requested_quote_units,
        )
        if worst_loss > tail_remaining and worst_loss > 0:
            amount = _max_amount_for_tail_budget(
                requested=candidate.requested_quote_units,
                full_loss=candidate.worst_loss_for_requested_quote_units,
                tail_budget=tail_remaining,
                upper=amount,
            )
            worst_loss = _scaled_loss_ceiling(
                full_loss=candidate.worst_loss_for_requested_quote_units,
                allocated=amount,
                requested=candidate.requested_quote_units,
            )
        allocations.append((candidate.candidate_id, amount))
        available -= amount
        tail_remaining -= worst_loss
    return AllocationDecision(
        allocations=tuple(allocations),
        unallocated_quote_units=available,
        remaining_tail_loss_budget_quote_units=tail_remaining,
    )


def qualify_inventory_platform(
    evidence: InventoryQualificationEvidence,
) -> InventoryQualificationVerdict:
    blockers: list[str] = []
    checks = {
        "AGG13_RESTART_REPLAY_MISSING": evidence.restart_replay_passed,
        "AGG13_PARTIAL_FILL_MODEL_MISSING": (
            evidence.partial_fill_model_passed
        ),
        "AGG13_ACTUAL_RECONCILIATION_MISSING": (
            evidence.actual_reconciliation_passed
        ),
        "AGG13_DISCONNECT_RECOVERY_MISSING": (
            evidence.disconnect_recovery_passed
        ),
        "AGG13_FUNDING_FLIP_STRESS_MISSING": (
            evidence.funding_flip_stress_passed
        ),
        "AGG13_MARGIN_SHOCK_MISSING": evidence.margin_shock_passed,
        "AGG13_INSTRUMENT_ACCESS_UNVERIFIED": (
            evidence.instrument_access_verified
        ),
    }
    for code, passed in checks.items():
        if not passed:
            blockers.append(code)
    return InventoryQualificationVerdict(
        qualified=not blockers,
        scope_sha256=evidence.scope_sha256,
        blockers=tuple(blockers),
        live_authorized=False,
    )


def _scaled_loss_ceiling(
    *,
    full_loss: int,
    allocated: int,
    requested: int,
) -> int:
    if full_loss == 0 or allocated == 0:
        return 0
    return (full_loss * allocated + requested - 1) // requested


def _max_amount_for_tail_budget(
    *,
    requested: int,
    full_loss: int,
    tail_budget: int,
    upper: int,
) -> int:
    if full_loss == 0:
        return upper
    lo = 0
    hi = upper
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if (
            _scaled_loss_ceiling(
                full_loss=full_loss,
                allocated=mid,
                requested=requested,
            )
            <= tail_budget
        ):
            lo = mid
        else:
            hi = mid - 1
    return lo


def _require_id(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ResearchError("AGG13_INVALID_IDENTIFIER", field)


def _require_sha256(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ResearchError("AGG13_INVALID_SHA256", field)


def _require_positive_int(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResearchError("AGG13_POSITIVE_INTEGER_REQUIRED", field)


def _require_nonnegative_int(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResearchError("AGG13_NONNEGATIVE_INTEGER_REQUIRED", field)
