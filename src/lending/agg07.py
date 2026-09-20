"""AGG-07 lender allocation and rate-market qualification contracts.

The module is deliberately sender-free. It extends MPR-2615's qualified-lender
selection and adds research-safe contracts for Kamino/Save and rate/PT-YT
markets. Unsupported or unpinned protocols remain explicit blockers rather
than stub-success adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from typing import Sequence

from .controlled_expansion import QualifiedLenderCandidate


class Agg07LendingError(ValueError):
    """Raised when financing or rate-market evidence is not safe to evaluate."""


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Agg07LendingError(f"{field} must be non-empty text")
    return value.strip()


def _int(value: int, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise Agg07LendingError(f"{field} must be an integer >= {minimum}")
    return value


def _hash64(value: str, field: str) -> str:
    checked = _text(value, field)
    if len(checked) != 64 or any(c not in "0123456789abcdef" for c in checked):
        raise Agg07LendingError(f"{field} must be a lowercase sha256 digest")
    return checked


def _digest(payload: object) -> str:
    return sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class ResearchDisposition(StrEnum):
    RESEARCH_ONLY = "research_only"
    BLOCKED_PROTOCOL = "blocked_protocol"
    OFFLINE_ADMISSIBLE = "offline_admissible"


@dataclass(frozen=True, slots=True)
class ProtocolResearchEvidence:
    protocol: str
    official_source: str | None
    immutable_source_ref: str | None
    license_id: str | None
    deployment_id: str | None
    abi_or_idl_sha256: str | None
    executable_abi_verified: bool
    current_liquidity_verified: bool
    production_reuse_allowed: bool

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.official_source:
            blockers.append("OFFICIAL_SOURCE_MISSING")
        if not self.immutable_source_ref:
            blockers.append("IMMUTABLE_SOURCE_PIN_MISSING")
        if not self.license_id:
            blockers.append("LICENSE_DECISION_MISSING")
        if not self.deployment_id:
            blockers.append("DEPLOYMENT_IDENTITY_MISSING")
        if not self.abi_or_idl_sha256:
            blockers.append("ABI_OR_IDL_PIN_MISSING")
        elif len(self.abi_or_idl_sha256) != 64:
            blockers.append("ABI_OR_IDL_HASH_INVALID")
        if not self.executable_abi_verified:
            blockers.append("EXECUTABLE_ABI_UNVERIFIED")
        if not self.current_liquidity_verified:
            blockers.append("CURRENT_LIQUIDITY_UNVERIFIED")
        if not self.production_reuse_allowed:
            blockers.append("PRODUCTION_SOURCE_REUSE_NOT_ALLOWED")
        return tuple(blockers)

    @property
    def disposition(self) -> ResearchDisposition:
        if self.blockers:
            return ResearchDisposition.BLOCKED_PROTOCOL
        return ResearchDisposition.OFFLINE_ADMISSIBLE


@dataclass(frozen=True, slots=True)
class KaminoFlashLoanEvidence:
    """Exact output of a separately pinned/reviewed Kamino SDK/deployment read.

    This is not an SDK reimplementation. It binds exact instruction bytes/state
    evidence and rejects guessed fees, indices, disabled reserves and stale
    message reuse.
    """

    combination_id: str
    reserve_id: str
    reserve_enabled: bool
    capacity_atomic: int
    principal_atomic: int
    repayment_atomic: int
    borrow_instruction_sha256: str
    repay_instruction_sha256: str
    reserve_state_sha256: str
    fee_config_sha256: str
    final_message_sha256: str
    simulation_message_sha256: str
    prefix_instruction_count: int
    borrow_instruction_index: int
    conformance_qualified: bool
    observed_slot: int
    expires_at_slot: int

    def __post_init__(self) -> None:
        _text(self.combination_id, "combination_id")
        _text(self.reserve_id, "reserve_id")
        _int(self.capacity_atomic, "capacity_atomic")
        _int(self.principal_atomic, "principal_atomic", minimum=1)
        _int(
            self.repayment_atomic,
            "repayment_atomic",
            minimum=self.principal_atomic,
        )
        for name, value in (
            ("borrow_instruction_sha256", self.borrow_instruction_sha256),
            ("repay_instruction_sha256", self.repay_instruction_sha256),
            ("reserve_state_sha256", self.reserve_state_sha256),
            ("fee_config_sha256", self.fee_config_sha256),
            ("final_message_sha256", self.final_message_sha256),
            ("simulation_message_sha256", self.simulation_message_sha256),
        ):
            _hash64(value, name)
        _int(self.prefix_instruction_count, "prefix_instruction_count")
        _int(self.borrow_instruction_index, "borrow_instruction_index")
        _int(self.observed_slot, "observed_slot", minimum=1)
        _int(self.expires_at_slot, "expires_at_slot", minimum=1)
        if self.expires_at_slot <= self.observed_slot:
            raise Agg07LendingError("expires_at_slot must be after observed_slot")

    def blockers(self, *, current_slot: int) -> tuple[str, ...]:
        _int(current_slot, "current_slot", minimum=1)
        blockers: list[str] = []
        if not self.conformance_qualified:
            blockers.append("KAMINO_CONFORMANCE_UNQUALIFIED")
        if not self.reserve_enabled:
            blockers.append("KAMINO_RESERVE_DISABLED")
        if self.capacity_atomic < self.principal_atomic:
            blockers.append("KAMINO_RESERVE_CAPACITY_INSUFFICIENT")
        if self.borrow_instruction_index != self.prefix_instruction_count:
            blockers.append("BORROW_INSTRUCTION_INDEX_MISMATCH")
        if self.final_message_sha256 != self.simulation_message_sha256:
            blockers.append("FINAL_MESSAGE_NOT_SIMULATED")
        if not (self.observed_slot <= current_slot < self.expires_at_slot):
            blockers.append("KAMINO_EVIDENCE_STALE")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class KaminoLoanPlan:
    combination_id: str
    reserve_id: str
    principal_atomic: int
    repayment_atomic: int
    protocol_fee_atomic: int
    borrow_instruction_index: int
    final_message_sha256: str
    evidence_hash: str


def build_kamino_loan_plan(
    evidence: KaminoFlashLoanEvidence,
    *,
    current_slot: int,
) -> KaminoLoanPlan:
    blockers = evidence.blockers(current_slot=current_slot)
    if blockers:
        raise Agg07LendingError("kamino plan blocked: " + ",".join(blockers))
    return KaminoLoanPlan(
        combination_id=evidence.combination_id,
        reserve_id=evidence.reserve_id,
        principal_atomic=evidence.principal_atomic,
        repayment_atomic=evidence.repayment_atomic,
        protocol_fee_atomic=evidence.repayment_atomic - evidence.principal_atomic,
        borrow_instruction_index=evidence.borrow_instruction_index,
        final_message_sha256=evidence.final_message_sha256,
        evidence_hash=_digest(
            {
                "combination_id": evidence.combination_id,
                "reserve_id": evidence.reserve_id,
                "principal": evidence.principal_atomic,
                "repayment": evidence.repayment_atomic,
                "borrow_ix": evidence.borrow_instruction_sha256,
                "repay_ix": evidence.repay_instruction_sha256,
                "reserve_state": evidence.reserve_state_sha256,
                "fee_config": evidence.fee_config_sha256,
                "message": evidence.final_message_sha256,
                "slot": evidence.observed_slot,
            }
        ),
    )


@dataclass(frozen=True, slots=True)
class CapitalVariant:
    candidate: QualifiedLenderCandidate
    amount_atomic: int
    reserve_capacity_atomic: int
    rent_peak_atomic: int
    compute_units: int
    message_bytes: int
    borrow_instruction_index: int
    expected_borrow_instruction_index: int
    observed_slot: int
    expires_at_slot: int
    prefix_solvent: bool
    lender_resource_ids: tuple[str, ...] = ()
    exit_resource_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _int(self.amount_atomic, "amount_atomic", minimum=1)
        _int(self.reserve_capacity_atomic, "reserve_capacity_atomic")
        _int(self.rent_peak_atomic, "rent_peak_atomic")
        _int(self.compute_units, "compute_units")
        _int(self.message_bytes, "message_bytes")
        _int(self.borrow_instruction_index, "borrow_instruction_index")
        _int(
            self.expected_borrow_instruction_index,
            "expected_borrow_instruction_index",
        )
        _int(self.observed_slot, "observed_slot", minimum=1)
        _int(self.expires_at_slot, "expires_at_slot", minimum=1)
        if self.expires_at_slot <= self.observed_slot:
            raise Agg07LendingError("expires_at_slot must be after observed_slot")
        if len(set(self.lender_resource_ids)) != len(self.lender_resource_ids):
            raise Agg07LendingError("duplicate lender_resource_ids")
        if len(set(self.exit_resource_ids)) != len(self.exit_resource_ids):
            raise Agg07LendingError("duplicate exit_resource_ids")

    def rejection_reasons(
        self,
        *,
        current_slot: int,
        max_compute_units: int,
        max_message_bytes: int,
        reserved_resource_ids: frozenset[str] = frozenset(),
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.candidate.selectable:
            reasons.append("LENDER_CANDIDATE_NOT_QUALIFIED")
        if self.reserve_capacity_atomic < self.amount_atomic:
            reasons.append("RESERVE_CAPACITY_INSUFFICIENT")
        if not self.prefix_solvent:
            reasons.append("PREFIX_INSOLVENT")
        if self.borrow_instruction_index != self.expected_borrow_instruction_index:
            reasons.append("BORROW_INSTRUCTION_INDEX_MISMATCH")
        if self.compute_units > max_compute_units:
            reasons.append("COMPUTE_LIMIT_EXCEEDED")
        if self.message_bytes > max_message_bytes:
            reasons.append("MESSAGE_SIZE_EXCEEDED")
        if not (self.observed_slot <= current_slot < self.expires_at_slot):
            reasons.append("LENDER_STATE_STALE")
        shared = set(self.lender_resource_ids)
        if shared.intersection(self.exit_resource_ids):
            reasons.append("SHARED_RESERVE_DOUBLE_COUNT")
        if shared.intersection(reserved_resource_ids):
            reasons.append("LENDER_RESOURCE_ALREADY_RESERVED")
        return tuple(reasons)


@dataclass(frozen=True, slots=True)
class CapitalSelection:
    selected: CapitalVariant
    rejected: tuple[tuple[str, tuple[str, ...]], ...]
    evidence_hash: str


def select_capital_variant(
    variants: Sequence[CapitalVariant],
    *,
    current_slot: int,
    max_compute_units: int,
    max_message_bytes: int,
    reserved_resource_ids: frozenset[str] = frozenset(),
) -> CapitalSelection:
    """Choose the best exact feasible lender/size variant in the tested domain."""

    rejected: list[tuple[str, tuple[str, ...]]] = []
    feasible: list[CapitalVariant] = []
    for variant in variants:
        reasons = variant.rejection_reasons(
            current_slot=current_slot,
            max_compute_units=max_compute_units,
            max_message_bytes=max_message_bytes,
            reserved_resource_ids=reserved_resource_ids,
        )
        if reasons:
            rejected.append((variant.candidate.identity.semantic_digest, reasons))
        else:
            feasible.append(variant)

    if not feasible:
        raise Agg07LendingError("no feasible lender/size variant in tested domain")

    selected = sorted(
        feasible,
        key=lambda item: (
            -item.candidate.net_edge_atomic,
            item.rent_peak_atomic,
            item.compute_units,
            item.message_bytes,
            item.candidate.identity.semantic_digest,
        ),
    )[0]
    return CapitalSelection(
        selected=selected,
        rejected=tuple(rejected),
        evidence_hash=_digest(
            {
                "selected": selected.candidate.identity.semantic_digest,
                "rejected": rejected,
                "current_slot": current_slot,
                "max_compute_units": max_compute_units,
                "max_message_bytes": max_message_bytes,
            }
        ),
    )


class RateMarketKind(StrEnum):
    LENDING_AMM = "lending_amm"
    CAPACITY_RELEASE = "capacity_release"
    EXPONENT_PT_YT = "exponent_pt_yt"
    EXPONENT_RATE_BOOK = "exponent_rate_book"
    EXPONENT_RATE_CLMM = "exponent_rate_clmm"


@dataclass(frozen=True, slots=True)
class RateMarketFrame:
    market_id: str
    kind: RateMarketKind
    underlying_asset: str
    maturity_unix: int
    observed_unix: int
    capacity_atomic: int
    shared_resource_id: str
    state_sha256: str
    pt_asset: str | None = None
    yt_asset: str | None = None
    fresh: bool = True

    def __post_init__(self) -> None:
        _text(self.market_id, "market_id")
        _text(self.underlying_asset, "underlying_asset")
        _int(self.maturity_unix, "maturity_unix", minimum=1)
        _int(self.observed_unix, "observed_unix", minimum=1)
        _int(self.capacity_atomic, "capacity_atomic")
        _text(self.shared_resource_id, "shared_resource_id")
        _hash64(self.state_sha256, "state_sha256")
        if self.maturity_unix <= self.observed_unix:
            raise Agg07LendingError("rate market maturity must be in the future")
        if (self.pt_asset is None) != (self.yt_asset is None):
            raise Agg07LendingError("PT and YT identities must be supplied together")


@dataclass(frozen=True, slots=True)
class CapacityReleaseEvent:
    market_id: str
    shared_resource_id: str
    before_capacity_atomic: int
    after_capacity_atomic: int
    event_sha256: str
    permission_generation_changed: bool = False

    def __post_init__(self) -> None:
        _text(self.market_id, "market_id")
        _text(self.shared_resource_id, "shared_resource_id")
        _int(self.before_capacity_atomic, "before_capacity_atomic")
        _int(self.after_capacity_atomic, "after_capacity_atomic")
        _hash64(self.event_sha256, "event_sha256")


@dataclass(frozen=True, slots=True)
class CapacityReleaseCandidate:
    accepted: bool
    reason: str | None
    released_capacity_atomic: int
    conservative_net_atomic: int
    evidence_hash: str


def evaluate_capacity_release(
    frame: RateMarketFrame,
    event: CapacityReleaseEvent,
    *,
    route_input_atomic: int,
    route_min_output_atomic: int,
    route_cost_atomic: int,
    exit_resource_ids: tuple[str, ...] = (),
) -> CapacityReleaseCandidate:
    _int(route_input_atomic, "route_input_atomic", minimum=1)
    _int(route_min_output_atomic, "route_min_output_atomic")
    _int(route_cost_atomic, "route_cost_atomic")
    reasons: list[str] = []
    released = event.after_capacity_atomic - event.before_capacity_atomic
    if event.market_id != frame.market_id:
        reasons.append("MARKET_ID_MISMATCH")
    if event.shared_resource_id != frame.shared_resource_id:
        reasons.append("RESOURCE_ID_MISMATCH")
    if released <= 0:
        reasons.append("NO_OBSERVED_CAPACITY_RELEASE")
    if not frame.fresh:
        reasons.append("RATE_MARKET_FRAME_STALE")
    if route_input_atomic > event.after_capacity_atomic:
        reasons.append("CAPACITY_INSUFFICIENT")
    if frame.shared_resource_id in exit_resource_ids:
        reasons.append("SHARED_RESERVE_DOUBLE_COUNT")
    if event.permission_generation_changed:
        reasons.append("PERMISSION_GENERATION_REQUIRES_REQUALIFICATION")
    net = route_min_output_atomic - route_input_atomic - route_cost_atomic
    if net <= 0:
        reasons.append("NO_CLOSED_ROUTE_NET_EDGE")
    return CapacityReleaseCandidate(
        accepted=not reasons,
        reason=";".join(dict.fromkeys(reasons)) if reasons else None,
        released_capacity_atomic=max(released, 0),
        conservative_net_atomic=net,
        evidence_hash=_digest(
            {
                "frame": frame.state_sha256,
                "event": event.event_sha256,
                "route_input": route_input_atomic,
                "route_min_output": route_min_output_atomic,
                "route_cost": route_cost_atomic,
                "reasons": reasons,
            }
        ),
    )


@dataclass(frozen=True, slots=True)
class StripMergeQuote:
    market_id: str
    maturity_unix: int
    direction: str
    input_underlying_atomic: int
    input_pt_atomic: int
    input_yt_atomic: int
    immediate_output_underlying_atomic: int
    transaction_cost_atomic: int
    depth_atomic: int
    quote_sha256: str

    def __post_init__(self) -> None:
        _text(self.market_id, "market_id")
        if self.direction not in {"strip", "merge"}:
            raise Agg07LendingError("direction must be strip or merge")
        _int(self.maturity_unix, "maturity_unix", minimum=1)
        for name, value in (
            ("input_underlying_atomic", self.input_underlying_atomic),
            ("input_pt_atomic", self.input_pt_atomic),
            ("input_yt_atomic", self.input_yt_atomic),
            (
                "immediate_output_underlying_atomic",
                self.immediate_output_underlying_atomic,
            ),
            ("transaction_cost_atomic", self.transaction_cost_atomic),
            ("depth_atomic", self.depth_atomic),
        ):
            _int(value, name)
        _hash64(self.quote_sha256, "quote_sha256")


@dataclass(frozen=True, slots=True)
class ImmediateParityCandidate:
    accepted: bool
    reason: str | None
    conservative_net_underlying_atomic: int
    evidence_hash: str


def evaluate_strip_merge(
    frame: RateMarketFrame,
    quote: StripMergeQuote,
    *,
    research: ProtocolResearchEvidence,
) -> ImmediateParityCandidate:
    reasons: list[str] = list(research.blockers)
    if frame.kind is not RateMarketKind.EXPONENT_PT_YT:
        reasons.append("NOT_PT_YT_MARKET")
    if frame.market_id != quote.market_id:
        reasons.append("MARKET_ID_MISMATCH")
    if frame.maturity_unix != quote.maturity_unix:
        reasons.append("MATURITY_MISMATCH")
    if frame.pt_asset is None or frame.yt_asset is None:
        reasons.append("PT_YT_IDENTITY_MISSING")
    if not frame.fresh:
        reasons.append("RATE_MARKET_FRAME_STALE")

    if quote.direction == "strip":
        required_depth = quote.input_underlying_atomic
        immediate_cost = quote.input_underlying_atomic + quote.transaction_cost_atomic
    else:
        if quote.input_pt_atomic <= 0 or quote.input_yt_atomic <= 0:
            reasons.append("MATCHED_PT_YT_REQUIRED")
        required_depth = max(quote.input_pt_atomic, quote.input_yt_atomic)
        immediate_cost = quote.transaction_cost_atomic

    if required_depth > quote.depth_atomic or required_depth > frame.capacity_atomic:
        reasons.append("EXECUTABLE_DEPTH_INSUFFICIENT")
    net = quote.immediate_output_underlying_atomic - immediate_cost
    if quote.direction == "strip":
        # Future maturity value is deliberately excluded from immediate profit.
        net = -quote.transaction_cost_atomic
    if net <= 0:
        reasons.append("NO_IMMEDIATE_PARITY_EDGE")

    unique = tuple(dict.fromkeys(reasons))
    return ImmediateParityCandidate(
        accepted=not unique,
        reason=";".join(unique) if unique else None,
        conservative_net_underlying_atomic=net,
        evidence_hash=_digest(
            {
                "frame": frame.state_sha256,
                "quote": quote.quote_sha256,
                "research_blockers": research.blockers,
                "net": net,
                "reasons": unique,
            }
        ),
    )


@dataclass(frozen=True, slots=True)
class RateVenueQuote:
    market_id: str
    maturity_unix: int
    immediate_input_atomic: int
    immediate_output_atomic: int
    future_cashflow_atomic: int
    executable_depth_atomic: int
    transaction_cost_atomic: int
    quote_convention: str
    quote_sha256: str
    fresh: bool

    def __post_init__(self) -> None:
        _text(self.market_id, "market_id")
        _int(self.maturity_unix, "maturity_unix", minimum=1)
        for name, value in (
            ("immediate_input_atomic", self.immediate_input_atomic),
            ("immediate_output_atomic", self.immediate_output_atomic),
            ("future_cashflow_atomic", self.future_cashflow_atomic),
            ("executable_depth_atomic", self.executable_depth_atomic),
            ("transaction_cost_atomic", self.transaction_cost_atomic),
        ):
            _int(value, name)
        _text(self.quote_convention, "quote_convention")
        _hash64(self.quote_sha256, "quote_sha256")


@dataclass(frozen=True, slots=True)
class RateVenueCandidate:
    accepted: bool
    reason: str | None
    conservative_immediate_net_atomic: int
    evidence_hash: str


def compare_rate_venues(
    left: RateVenueQuote,
    right: RateVenueQuote,
    *,
    research: ProtocolResearchEvidence,
) -> RateVenueCandidate:
    """Compare same-maturity executable immediate cashflows.

    future_cashflow_atomic is retained for analytics but never finances an
    immediate repayment.
    """

    reasons: list[str] = list(research.blockers)
    if left.market_id == right.market_id:
        reasons.append("SAME_VENUE_NOT_EXTERNAL_PARITY")
    if left.maturity_unix != right.maturity_unix:
        reasons.append("MATURITY_MISMATCH")
    if not left.fresh or not right.fresh:
        reasons.append("RATE_QUOTE_STALE")
    size = min(left.executable_depth_atomic, right.executable_depth_atomic)
    if size <= 0:
        reasons.append("EXECUTABLE_DEPTH_INSUFFICIENT")

    left_to_right = (
        left.immediate_output_atomic
        - right.immediate_input_atomic
        - left.transaction_cost_atomic
        - right.transaction_cost_atomic
    )
    right_to_left = (
        right.immediate_output_atomic
        - left.immediate_input_atomic
        - left.transaction_cost_atomic
        - right.transaction_cost_atomic
    )
    net = max(left_to_right, right_to_left)
    if net <= 0:
        reasons.append("NO_IMMEDIATE_RATE_PARITY_EDGE")

    unique = tuple(dict.fromkeys(reasons))
    return RateVenueCandidate(
        accepted=not unique,
        reason=";".join(unique) if unique else None,
        conservative_immediate_net_atomic=net,
        evidence_hash=_digest(
            {
                "left": left.quote_sha256,
                "right": right.quote_sha256,
                "research_blockers": research.blockers,
                "net": net,
                "reasons": unique,
            }
        ),
    )


__all__ = [
    "Agg07LendingError",
    "CapitalSelection",
    "CapitalVariant",
    "CapacityReleaseCandidate",
    "CapacityReleaseEvent",
    "ImmediateParityCandidate",
    "KaminoFlashLoanEvidence",
    "KaminoLoanPlan",
    "ProtocolResearchEvidence",
    "RateMarketFrame",
    "RateMarketKind",
    "RateVenueCandidate",
    "RateVenueQuote",
    "ResearchDisposition",
    "StripMergeQuote",
    "build_kamino_loan_plan",
    "compare_rate_venues",
    "evaluate_capacity_release",
    "evaluate_strip_merge",
    "select_capital_variant",
]
