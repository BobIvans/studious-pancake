"""AGG-07 sender-free liquidation orchestration.

This module extends the existing PR-020/MPR-2619 liquidation domain without
creating a sender, signer, ledger, or second liquidation engine. It binds fresh
eligibility, exact financing evidence, collateral unwind evidence, and
conflict-aware batching. Every result is paper/simulation-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .adapters import LiquidationAdapter
from .models import (
    LendingProtocol,
    LiquidationEligibility,
    LiquidationReason,
    LiquidationSizingResult,
    LiquidationStatus,
    LiquidationTargetSnapshot,
    canonical_hash,
)


class Agg07LiquidationError(ValueError):
    """Raised when AGG-07 evidence is malformed or internally inconsistent."""


def _positive_int(value: int, field: str, *, allow_zero: bool = False) -> int:
    if type(value) is not int:
        raise Agg07LiquidationError(f"{field} must be an integer")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise Agg07LiquidationError(f"{field} must be >= {minimum}")
    return value


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Agg07LiquidationError(f"{field} must be non-empty text")
    return value.strip()


def _hash64(value: str, field: str) -> str:
    checked = _text(value, field)
    if len(checked) != 64 or any(c not in "0123456789abcdef" for c in checked):
        raise Agg07LiquidationError(f"{field} must be a lowercase sha256 digest")
    return checked


@dataclass(frozen=True, slots=True)
class LiquidationWatchEntry:
    target_account: str
    protocol: LendingProtocol
    slot: int
    eligibility: LiquidationEligibility
    health_deficit: int
    trigger_price_numerator: int | None = None
    trigger_price_denominator: int | None = None
    trigger_rule_hash: str | None = None

    @property
    def eligible_now(self) -> bool:
        return self.eligibility.status is LiquidationStatus.POTENTIALLY_LIQUIDATABLE

    @property
    def forecast_only(self) -> bool:
        return not self.eligible_now


@dataclass(frozen=True, slots=True)
class LiquidationTriggerEvidence:
    """Protocol-specific trigger output produced by a pinned rule implementation.

    AGG-07 intentionally does not invent a generic trigger-price formula. A
    caller may attach an exact trigger only when it is bound to the same target
    state and a pinned protocol rule.
    """

    target_account: str
    protocol: LendingProtocol
    snapshot_hash: str
    price_numerator: int
    price_denominator: int
    rule_hash: str
    oracle_fresh: bool
    protocol_paused: bool = False

    def __post_init__(self) -> None:
        _text(self.target_account, "target_account")
        _hash64(self.snapshot_hash, "snapshot_hash")
        _positive_int(self.price_numerator, "price_numerator")
        _positive_int(self.price_denominator, "price_denominator")
        _hash64(self.rule_hash, "rule_hash")


@dataclass(frozen=True, slots=True)
class LiquidationWatchlist:
    entries: tuple[LiquidationWatchEntry, ...]
    evidence_hash: str


def build_liquidation_watchlist(
    snapshots: Sequence[LiquidationTargetSnapshot],
    adapters: Mapping[LendingProtocol, LiquidationAdapter],
    *,
    trigger_evidence: Mapping[str, LiquidationTriggerEvidence] | None = None,
    max_slot_skew: int = 0,
) -> LiquidationWatchlist:
    """Evaluate fresh protocol-specific eligibility and build a watchlist.

    A forecast can prioritize a target but never upgrades an ineligible target.
    Missing adapters fail closed as protocol-unsupported.
    """

    evidence_by_target = trigger_evidence or {}
    entries: list[LiquidationWatchEntry] = []
    for snapshot in snapshots:
        adapter = adapters.get(snapshot.protocol)
        if adapter is None:
            eligibility = LiquidationEligibility(
                LiquidationStatus.PRE_SIMULATION_REJECTED,
                LiquidationReason.LIQUIDATION_PROTOCOL_UNSUPPORTED,
            )
        else:
            eligibility = adapter.evaluate(snapshot, max_slot_skew=max_slot_skew)

        deficit = max(
            0,
            snapshot.risk.health_liabilities_value
            - snapshot.risk.health_assets_value,
        )
        trigger = evidence_by_target.get(snapshot.target_account)
        trigger_num: int | None = None
        trigger_den: int | None = None
        trigger_hash: str | None = None
        if trigger is not None:
            same_state = (
                trigger.protocol is snapshot.protocol
                and trigger.snapshot_hash == snapshot.raw_hash
                and trigger.target_account == snapshot.target_account
            )
            if same_state and trigger.oracle_fresh and not trigger.protocol_paused:
                trigger_num = trigger.price_numerator
                trigger_den = trigger.price_denominator
                trigger_hash = trigger.rule_hash

        entries.append(
            LiquidationWatchEntry(
                target_account=snapshot.target_account,
                protocol=snapshot.protocol,
                slot=snapshot.slot,
                eligibility=eligibility,
                health_deficit=deficit,
                trigger_price_numerator=trigger_num,
                trigger_price_denominator=trigger_den,
                trigger_rule_hash=trigger_hash,
            )
        )

    entries.sort(
        key=lambda item: (
            0 if item.eligible_now else 1,
            -item.health_deficit,
            -item.eligibility.max_repay,
            item.target_account,
        )
    )
    return LiquidationWatchlist(
        entries=tuple(entries),
        evidence_hash=canonical_hash(
            tuple(
                (
                    item.target_account,
                    item.protocol.value,
                    item.slot,
                    item.eligibility.status.value,
                    item.eligibility.reason.value if item.eligibility.reason else None,
                    item.eligibility.max_repay,
                    item.trigger_price_numerator,
                    item.trigger_price_denominator,
                    item.trigger_rule_hash,
                )
                for item in entries
            )
        ),
    )


@dataclass(frozen=True, slots=True)
class FinancingEvidence:
    lender_id: str
    combination_id: str
    principal_atomic: int
    repayment_atomic: int
    message_sha256: str
    simulation_message_sha256: str
    borrow_instruction_index: int
    expected_borrow_instruction_index: int
    qualified: bool
    shared_resource_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.lender_id, "lender_id")
        _text(self.combination_id, "combination_id")
        _positive_int(self.principal_atomic, "principal_atomic")
        _positive_int(self.repayment_atomic, "repayment_atomic")
        if self.repayment_atomic < self.principal_atomic:
            raise Agg07LiquidationError("repayment cannot be below principal")
        _hash64(self.message_sha256, "message_sha256")
        _hash64(self.simulation_message_sha256, "simulation_message_sha256")
        _positive_int(
            self.borrow_instruction_index,
            "borrow_instruction_index",
            allow_zero=True,
        )
        _positive_int(
            self.expected_borrow_instruction_index,
            "expected_borrow_instruction_index",
            allow_zero=True,
        )
        if len(set(self.shared_resource_ids)) != len(self.shared_resource_ids):
            raise Agg07LiquidationError("shared_resource_ids must be unique")

    @property
    def exact_message_bound(self) -> bool:
        return self.message_sha256 == self.simulation_message_sha256

    @property
    def borrow_index_bound(self) -> bool:
        return (
            self.borrow_instruction_index
            == self.expected_borrow_instruction_index
        )


@dataclass(frozen=True, slots=True)
class CollateralUnwindQuote:
    collateral_asset: str
    repay_asset: str
    input_atomic: int
    minimum_output_atomic: int
    route_capacity_atomic: int
    state_sha256: str
    executable: bool
    shared_resource_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.collateral_asset, "collateral_asset")
        _text(self.repay_asset, "repay_asset")
        _positive_int(self.input_atomic, "input_atomic")
        _positive_int(
            self.minimum_output_atomic,
            "minimum_output_atomic",
            allow_zero=True,
        )
        _positive_int(
            self.route_capacity_atomic,
            "route_capacity_atomic",
            allow_zero=True,
        )
        _hash64(self.state_sha256, "state_sha256")
        if len(set(self.shared_resource_ids)) != len(self.shared_resource_ids):
            raise Agg07LiquidationError("shared_resource_ids must be unique")


@dataclass(frozen=True, slots=True)
class Agg07LiquidationCandidate:
    candidate_id: str
    target_account: str
    accepted: bool
    reason: str | None
    repay_atomic: int
    collateral_atomic: int
    minimum_exit_atomic: int
    exact_financing_repayment_atomic: int
    conservative_net_atomic: int
    message_sha256: str | None
    resource_ids: tuple[str, ...]
    evidence_hash: str


def build_flash_funded_liquidation_candidate(
    snapshot: LiquidationTargetSnapshot,
    eligibility: LiquidationEligibility,
    sizing: LiquidationSizingResult,
    financing: FinancingEvidence,
    unwind: CollateralUnwindQuote,
) -> Agg07LiquidationCandidate:
    """Bind debt financing, partial liquidation and immediate collateral unwind.

    The existing sizer supplies protocol/route bounds. Financing fees come from
    qualified lender evidence, so principal/fee is never subtracted twice.
    """

    reasons: list[str] = []
    if eligibility.status is not LiquidationStatus.POTENTIALLY_LIQUIDATABLE:
        reasons.append("ELIGIBILITY_NOT_FRESHLY_PROVEN")
    if sizing.status is not LiquidationStatus.POTENTIALLY_LIQUIDATABLE:
        reasons.append("SIZING_NOT_FEASIBLE")
    if not financing.qualified:
        reasons.append("FINANCING_UNQUALIFIED")
    if not financing.exact_message_bound:
        reasons.append("SIMULATION_MESSAGE_MISMATCH")
    if not financing.borrow_index_bound:
        reasons.append("BORROW_INSTRUCTION_INDEX_MISMATCH")
    if financing.principal_atomic != sizing.repay_amount:
        reasons.append("FINANCING_PRINCIPAL_MISMATCH")
    if not unwind.executable:
        reasons.append("UNWIND_NOT_EXECUTABLE")

    debt = eligibility.debt
    collateral = eligibility.collateral
    if debt is None or collateral is None:
        reasons.append("DEBT_OR_COLLATERAL_MISSING")
    else:
        if unwind.collateral_asset != collateral.mint:
            reasons.append("UNWIND_COLLATERAL_ASSET_MISMATCH")
        if unwind.repay_asset != debt.mint:
            reasons.append("UNWIND_REPAY_ASSET_MISMATCH")
    if unwind.input_atomic < sizing.min_collateral_seized:
        reasons.append("COLLATERAL_SHORTAGE")
    if unwind.route_capacity_atomic < unwind.input_atomic:
        reasons.append("UNWIND_CAPACITY_SHORTAGE")
    if unwind.minimum_output_atomic < financing.repayment_atomic:
        reasons.append("INSUFFICIENT_EXIT_FOR_REPAYMENT")

    resources = tuple(
        dict.fromkeys(financing.shared_resource_ids + unwind.shared_resource_ids)
    )
    net = unwind.minimum_output_atomic - financing.repayment_atomic
    if net <= 0:
        reasons.append("NON_POSITIVE_CONSERVATIVE_NET")

    candidate_id = canonical_hash(
        {
            "target": snapshot.target_account,
            "slot": snapshot.slot,
            "raw": snapshot.raw_hash,
            "risk": snapshot.risk.risk_hash,
            "lender": financing.lender_id,
            "combination": financing.combination_id,
            "message": financing.message_sha256,
            "unwind_state": unwind.state_sha256,
            "repay": sizing.repay_amount,
        }
    )
    unique_reasons = tuple(dict.fromkeys(reasons))
    return Agg07LiquidationCandidate(
        candidate_id=candidate_id,
        target_account=snapshot.target_account,
        accepted=not unique_reasons,
        reason=";".join(unique_reasons) if unique_reasons else None,
        repay_atomic=sizing.repay_amount,
        collateral_atomic=sizing.min_collateral_seized,
        minimum_exit_atomic=unwind.minimum_output_atomic,
        exact_financing_repayment_atomic=financing.repayment_atomic,
        conservative_net_atomic=net,
        message_sha256=financing.message_sha256 if not unique_reasons else None,
        resource_ids=resources,
        evidence_hash=canonical_hash(
            {
                "candidate": candidate_id,
                "reasons": unique_reasons,
                "resources": resources,
                "net": net,
            }
        ),
    )


@dataclass(frozen=True, slots=True)
class LiquidationBatchPlan:
    selected: tuple[Agg07LiquidationCandidate, ...]
    rejected: tuple[tuple[str, str], ...]
    evidence_hash: str


def select_non_conflicting_liquidations(
    candidates: Sequence[Agg07LiquidationCandidate],
) -> LiquidationBatchPlan:
    """Select deterministic non-conflicting paper candidates.

    A target or shared resource can be consumed by at most one candidate in the
    batch. Dependent residual/cascade work must be re-evaluated after the first
    observed outcome rather than pre-authorized here.
    """

    selected: list[Agg07LiquidationCandidate] = []
    rejected: list[tuple[str, str]] = []
    targets: set[str] = set()
    resources: set[str] = set()

    for candidate in sorted(
        candidates,
        key=lambda item: (-item.conservative_net_atomic, item.candidate_id),
    ):
        if not candidate.accepted:
            rejected.append((candidate.candidate_id, candidate.reason or "REJECTED"))
            continue
        if candidate.target_account in targets:
            rejected.append((candidate.candidate_id, "TARGET_CONFLICT"))
            continue
        conflicts = resources.intersection(candidate.resource_ids)
        if conflicts:
            rejected.append(
                (
                    candidate.candidate_id,
                    "SHARED_RESOURCE_CONFLICT:" + ",".join(sorted(conflicts)),
                )
            )
            continue
        selected.append(candidate)
        targets.add(candidate.target_account)
        resources.update(candidate.resource_ids)

    return LiquidationBatchPlan(
        selected=tuple(selected),
        rejected=tuple(rejected),
        evidence_hash=canonical_hash(
            {
                "selected": [item.candidate_id for item in selected],
                "rejected": rejected,
            }
        ),
    )


__all__ = [
    "Agg07LiquidationCandidate",
    "Agg07LiquidationError",
    "CollateralUnwindQuote",
    "FinancingEvidence",
    "LiquidationBatchPlan",
    "LiquidationTriggerEvidence",
    "LiquidationWatchEntry",
    "LiquidationWatchlist",
    "build_flash_funded_liquidation_candidate",
    "build_liquidation_watchlist",
    "select_non_conflicting_liquidations",
]
