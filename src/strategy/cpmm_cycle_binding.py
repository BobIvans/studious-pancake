"""R10-1 pre-API market -> route -> paper qualification binding.

This module closes the existing integration vertical between canonical owners:

    CircularArbitrageDetector (two-leg, PR-033/PR-113)
    + enumerate_exact_cpmm_routes / evaluate_exact_cpmm_route (PR559 exact CPMM)
    + search_bounded_cycles (AGG-05 marginal topology shortlist, 2-5 hops)
    + PoolIdentityDeduplicator (R13-K physical-pool / aggregator-lineage dedup)
    + CapacityEconomics / evaluate_pr118_non_monotonic_sizing (PR118 sizing)
    + the existing sender-free paper/evidence seam (R02/R03/R05/R06 owners)

It owns no new graph, solver, quote kernel, registry, journal, capital graph,
scheduler or authority gate.  Every stage is deterministic and offline: inputs
are already-decoded fixture/replay ``QualifiedCpmmState`` objects, never live
captures.  Unknown identity, lineage, state, cost, capacity, builder or
simulation evidence blocks the candidate with a typed reason; nothing defaults
to zero and no quote is ever scaled.  No signer, sender, wallet, borrowing,
submission, provider activation or live mode is introduced here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
import hashlib
import json
import math
from collections.abc import Collection
from typing import Any, Mapping, Sequence

from src.economics.capital import CapitalEngineError
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)
from src.economics.non_monotonic_sizing import (
    PR118SizingCandidateEvidence,
    PR118SizingPointRejected,
    PR118TypedCostLedger,
    build_pr118_amount_grid,
    evaluate_pr118_non_monotonic_sizing,
)
from src.execution.quote_build_kernel import (
    IndependenceVerdict,
    NormalizedProviderQuote,
    PoolIdentity,
    PoolIdentityDeduplicator,
    ProviderCorrelation,
    QuoteDirection,
    QuoteFreshness,
)
from src.market.observations import ObservationBatch

from .arbitrage_graph import VenueIdentity
from .detectors import CircularArbitrageDetector, DetectorPair
from .exact_cpmm_capacity import (
    CapacityEconomics,
    CpmmEvaluationError,
    CpmmEvaluationRejection,
    ExactCpmmEdgeEvaluation,
    ExactCpmmRoutePlan,
    QualifiedCpmmState,
    QualifiedRaydiumCpmmAdapter,
    SolanaAssetIdentity,
    enumerate_exact_cpmm_routes,
    evaluate_exact_cpmm_route,
)
from .multihop_solver import SearchEdge, search_bounded_cycles

CPMM_BINDING_SCHEMA_VERSION = "r10-1.cpmm-cycle-binding.v1"
REPLAY_EVIDENCE_SCOPE = "fixture-replay"


def _hash(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _integer(value: int, field_name: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field_name} must be an integer >= {minimum}")


class CpmmBindingRejection(StrEnum):
    """Typed rejection vocabulary for the R10-1 binding pipeline."""

    UNSUPPORTED_VENUE_KIND = "cpmm-binding-unsupported-venue-kind"
    MISSING_VENUE_STATE = "cpmm-binding-missing-venue-state"
    IDENTITY_UNQUALIFIED = "cpmm-binding-identity-unqualified"
    STALE_OR_FUTURE_STATE = "cpmm-binding-stale-or-future-state"
    MIXED_GENERATION = "cpmm-binding-mixed-generation"
    SLOT_SKEW_EXCEEDED = "cpmm-binding-slot-skew-exceeded"
    NON_CLOSED_PATH = "cpmm-binding-non-closed-path"
    NON_UNIQUE_PHYSICAL_POOL = "cpmm-binding-non-unique-physical-pool"
    POOL_ALIAS_CORRELATED = "cpmm-binding-pool-alias-correlated"
    POOL_LINEAGE_UNKNOWN = "cpmm-binding-pool-lineage-unknown"
    EXACT_UNSUPPORTED_HOP_COUNT = "cpmm-binding-exact-unsupported-hop-count"
    NO_EXACT_EVALUATION = "cpmm-binding-no-exact-evaluation"
    NEGATIVE_GROSS_OUTPUT = "cpmm-binding-negative-gross-output"
    UNKNOWN_COST_DENOMINATION = "cpmm-binding-unknown-cost-denomination"
    NET_NEGATIVE = "cpmm-binding-net-negative"
    NO_QUALIFIED_LENDER_EDGE = "NO_QUALIFIED_LENDER_EDGE"
    BUILDER_UNQUALIFIED = "BUILDER_UNQUALIFIED"
    SIMULATION_SOURCE_BLOCKED = "SIMULATION_SOURCE_BLOCKED"
    QPR_NOT_READY = "QPR_NOT_READY"
    PAPER_COMPLETE_UNAVAILABLE_OFFLINE = "paper-complete-unavailable-offline-replay"


class CpmmBindingError(ValueError):
    """Fail-closed binding error carrying a typed rejection reason."""

    def __init__(self, reason: CpmmBindingRejection, detail: str) -> None:
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


class VenueKind(StrEnum):
    """Typed venue family; only RAYDIUM_CPMM has an exact evaluator here."""

    RAYDIUM_CPMM = "raydium-cpmm"
    RAYDIUM_CLMM = "raydium-clmm"
    METEORA_DLMM = "meteora-dlmm"
    ORDERBOOK = "orderbook"
    UNKNOWN = "unknown"


class RouteSupport(StrEnum):
    """Supported / shortlist-only / blocked route matrix verdict."""

    EXACT_SUPPORTED = "exact-supported"
    SHORTLIST_ONLY = "shortlist-only"
    BLOCKED = "blocked"


class RouteQualificationStatus(StrEnum):
    """Terminal per-route status in the deterministic replay."""

    EXACT_QUALIFIED = "exact-qualified"
    NET_POSITIVE = "net-positive"
    PAPER_BLOCKED = "paper-blocked"
    REJECTED = "rejected"
    SHORTLIST_ONLY = "shortlist-only"


@dataclass(frozen=True, slots=True)
class PoolLineage:
    """Declared physical-pool lineage for one venue (R13-K dedup input).

    ``pool_ids`` empty means lineage is UNKNOWN; unknown never counts as
    independent and blocks exact promotion of routes that depend on it.
    """

    correlation_group: str
    aggregator_lineage: tuple[str, ...] = ()
    pool_ids: tuple[PoolIdentity, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.correlation_group, str)
            or not self.correlation_group.strip()
        ):
            raise ValueError("correlation_group is required")
        object.__setattr__(
            self,
            "aggregator_lineage",
            tuple(sorted(set(self.aggregator_lineage))),
        )
        pools = tuple(sorted(set(self.pool_ids), key=lambda pool: pool.key))
        object.__setattr__(self, "pool_ids", pools)


@dataclass(frozen=True, slots=True)
class BlockedVenueCandidate:
    """A discovered market whose venue family has no exact evaluator yet.

    CLMM/DLMM candidates carry the exact missing state proof (tick arrays,
    bin arrays); orderbook families are unsupported outright until fill
    semantics are proven."""

    label: str
    venue_kind: VenueKind
    missing_evidence: str
    pool_ids: tuple[PoolIdentity, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.venue_kind, VenueKind):
            raise ValueError("venue_kind must be a VenueKind")
        if self.venue_kind is VenueKind.RAYDIUM_CPMM:
            raise ValueError("CPMM candidates are not blocked candidates")
        if not self.missing_evidence.strip():
            raise ValueError("missing_evidence is required")


@dataclass(frozen=True, slots=True)
class PaperGateInputs:
    """Caller-declared R02/R03/R05/R06 seam state; replay defaults are the
    honest current-main state (zero qualified lender edges, no builder
    conformance, blocked simulation, QPR not ready).  Actual qualification
    stays owned by the existing R02/R03/R05/R06 owners; this gate only
    reports the seam and can never mark a replay candidate complete."""

    qualified_lender_edge_count: int = 0
    builder_conformance_passed: bool = False
    simulation_available: bool = False
    qpr_ready: bool = False


def evaluate_paper_gate(gate: PaperGateInputs) -> CpmmBindingRejection:
    """Return the typed paper-seam blocker.  Even when every declared input
    claims readiness the offline replay refuses with a typed fail-closed
    reason, because no R05 simulation evidence owner exists in this PR (no
    fake paper fills, ever)."""

    _integer(gate.qualified_lender_edge_count, "qualified_lender_edge_count")
    if gate.qualified_lender_edge_count == 0:
        return CpmmBindingRejection.NO_QUALIFIED_LENDER_EDGE
    if not gate.builder_conformance_passed:
        # The R03 contract defines no execution-ready build status yet, so a
        # replay candidate can never pass this stage honestly.
        return CpmmBindingRejection.BUILDER_UNQUALIFIED
    if not gate.simulation_available:
        return CpmmBindingRejection.SIMULATION_SOURCE_BLOCKED
    if not gate.qpr_ready:
        return CpmmBindingRejection.QPR_NOT_READY
    return CpmmBindingRejection.PAPER_COMPLETE_UNAVAILABLE_OFFLINE


def classify_route_support(
    *,
    venue_kind: VenueKind,
    hop_count: int,
    exact_venues: Collection[VenueKind] = (),
) -> RouteSupport:
    """Supported-vs-blocked route matrix: venue families with a registered
    exact evaluator (CPMM always; CLMM/DLMM once their qualified adapters are
    supplied via ``exact_venues``) support 2/3/4 hops exactly; 5 hops stays
    shortlist-only and every other family stays blocked."""

    _integer(hop_count, "hop_count", minimum=1)
    if venue_kind is VenueKind.RAYDIUM_CPMM:
        exact = True
    elif venue_kind in (VenueKind.RAYDIUM_CLMM, VenueKind.METEORA_DLMM):
        exact = venue_kind in exact_venues
    else:
        return RouteSupport.BLOCKED
    if not exact:
        return RouteSupport.BLOCKED
    if hop_count in (2, 3, 4):
        return RouteSupport.EXACT_SUPPORTED
    return RouteSupport.SHORTLIST_ONLY


@dataclass(frozen=True, slots=True)
class TwoLegExactEvaluation:
    """Exact sequential two-leg A -> B -> A evaluation at one amount."""

    semantic_route_id: str
    legs: tuple[ExactCpmmEdgeEvaluation, ...]

    @property
    def input_amount(self) -> int:
        return self.legs[0].requested_input

    @property
    def conservative_output(self) -> int:
        return self.legs[-1].conservative_output

    @property
    def gross_profit(self) -> int:
        return self.conservative_output - self.input_amount

    @property
    def evaluation_id(self) -> str:
        return _hash(
            {
                "schema": "r10-1.exact-two-leg-route.v1",
                "semantic_route_id": self.semantic_route_id,
                "ordered_leg_evaluations": [leg.evaluation_id for leg in self.legs],
            }
        )


def mixed_route_semantic_route_id(legs: Sequence[object]) -> str:
    """Ordered mixed-venue semantic route id over any exact-leg states."""
    return _hash(
        {
            "schema": "r10-1.mixed-route-semantic-id.v1",
            "ordered_venues": [
                {
                    "program_id": leg.venue.program_id,
                    "market_id": leg.venue.market_id,
                    "venue_kind": getattr(
                        leg, "venue_kind", VenueKind.RAYDIUM_CPMM
                    ).value,
                }
                for leg in legs
            ],
            "assets": [legs[0].asset_a.identity, legs[0].asset_b.identity],
        }
    )


def two_leg_semantic_route_id(
    first: QualifiedCpmmState, second: QualifiedCpmmState
) -> str:
    return _hash(
        {
            "schema": "r10-1.two-leg-semantic-route.v1",
            "ordered_venues": [
                {
                    "program_id": first.venue.program_id,
                    "market_id": first.venue.market_id,
                },
                {
                    "program_id": second.venue.program_id,
                    "market_id": second.venue.market_id,
                },
            ],
            "assets": [first.asset_a.identity, first.asset_b.identity],
        }
    )


def _resolve_venue_evaluator(
    pool: object,
    *,
    adapter: QualifiedRaydiumCpmmAdapter | None,
    adapters: Mapping[VenueKind, object] | None,
):
    """Resolve the exact evaluator for one leg by its declared venue kind."""
    kind = getattr(pool, "venue_kind", VenueKind.RAYDIUM_CPMM)
    if not isinstance(kind, VenueKind):
        raise CpmmBindingError(
            CpmmBindingRejection.UNSUPPORTED_VENUE_KIND,
            "leg state must declare a VenueKind",
        )
    if kind is VenueKind.RAYDIUM_CPMM:
        return adapter or QualifiedRaydiumCpmmAdapter()
    resolved = (adapters or {}).get(kind)
    if resolved is None:
        raise CpmmBindingError(
            CpmmBindingRejection.UNSUPPORTED_VENUE_KIND,
            f"no qualified exact evaluator registered for {kind.value}",
        )
    return resolved


def evaluate_exact_two_leg_route(
    first: QualifiedCpmmState,
    second: QualifiedCpmmState,
    *,
    settlement_asset: SolanaAssetIdentity,
    input_amount: int,
    now: float,
    max_snapshot_age_seconds: float = 5.0,
    max_slot_skew: int = 0,
    adapter: QualifiedRaydiumCpmmAdapter | None = None,
    adapters: Mapping[VenueKind, object] | None = None,
) -> TwoLegExactEvaluation:
    """Sequential exact two-leg evaluation: leg 2 input is leg 1's
    conservative guaranteed output in raw base units.  No quote scaling.

    ``adapters`` extends the exact evaluator registry per venue family
    (CLMM/DLMM qualified adapters); the CPMM default adapter is unchanged.
    Every leg state must declare its ``venue_kind``; a family without a
    registered adapter is a typed UNSUPPORTED_VENUE_KIND rejection."""

    _integer(input_amount, "input_amount", minimum=1)
    if first.venue == second.venue:
        raise CpmmBindingError(
            CpmmBindingRejection.NON_UNIQUE_PHYSICAL_POOL,
            "two-leg route cannot repeat a venue",
        )
    if first.generation.identity != second.generation.identity:
        raise CpmmBindingError(
            CpmmBindingRejection.MIXED_GENERATION,
            "two-leg route cannot mix state generations",
        )
    if max(first.slot, second.slot) - min(first.slot, second.slot) > max_slot_skew:
        raise CpmmBindingError(
            CpmmBindingRejection.SLOT_SKEW_EXCEEDED, "bounded slot skew violated"
        )
    for pool in (first, second):
        if (
            pool.observed_at > now
            or now >= pool.expires_at
            or now - pool.observed_at > max_snapshot_age_seconds
        ):
            raise CpmmBindingError(
                CpmmBindingRejection.STALE_OR_FUTURE_STATE,
                f"stale or future state for venue {pool.venue.market_id}",
            )
    leg_evaluators: list[object] = []
    for pool in (first, second):
        leg_evaluators.append(
            _resolve_venue_evaluator(pool, adapter=adapter, adapters=adapters)
        )
    leg_evaluators[0].qualify_state(first)
    leg_evaluators[1].qualify_state(second)
    leg_one = leg_evaluators[0].evaluate(
        first, input_asset=settlement_asset, requested_input=input_amount
    )
    leg_two = leg_evaluators[1].evaluate(
        second,
        input_asset=leg_one.output_asset,
        requested_input=leg_one.conservative_output,
    )
    if leg_two.output_asset != settlement_asset:
        raise CpmmBindingError(
            CpmmBindingRejection.NON_CLOSED_PATH,
            "two-leg route does not close back to the settlement asset",
        )
    return TwoLegExactEvaluation(
        two_leg_semantic_route_id(first, second), (leg_one, leg_two)
    )


def conservative_net_for_ledger(ledger: PR118TypedCostLedger) -> int:
    """Conservative net with fail-closed denominations: a cost recorded in a
    non-settlement asset without a verified conversion contract blocks the
    route; unknown is never zero."""

    try:
        return ledger.conservative_net_amount()
    except CapitalEngineError as exc:
        raise CpmmBindingError(
            CpmmBindingRejection.UNKNOWN_COST_DENOMINATION,
            str(exc),
        ) from exc


@dataclass(frozen=True, slots=True)
class RouteQualificationMetrics:
    """Stage counters and typed rejection reasons for one replay.

    Counts describe fixture/replay evidence only; they are never mixed with
    live-source records and never claim market profitability."""

    discovered_market_count: int = 0
    identity_verified_market_count: int = 0
    rooted_state_count: int = 0
    topology_route_count: int = 0
    shortlist_route_count: int = 0
    unique_semantic_route_count: int = 0
    aliased_or_correlated_route_count: int = 0
    exact_quote_route_count: int = 0
    exact_qualified_route_count: int = 0
    net_positive_route_count: int = 0
    size_grid_evaluated_count: int = 0
    market_candidate_count: int = 0
    flashloan_eligible_count: int = 0
    capital_eligible_count: int = 0
    builder_eligible_count: int = 0
    simulation_pass_count: int = 0
    paper_attempt_count: int = 0
    paper_complete_count: int = 0
    paper_rejected_count: int = 0
    provider_overlap_cluster_count: int = 0
    rejections: tuple[tuple[str, int], ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "discovered_market_count": self.discovered_market_count,
            "identity_verified_market_count": self.identity_verified_market_count,
            "rooted_state_count": self.rooted_state_count,
            "topology_route_count": self.topology_route_count,
            "shortlist_route_count": self.shortlist_route_count,
            "unique_semantic_route_count": self.unique_semantic_route_count,
            "aliased_or_correlated_route_count": self.aliased_or_correlated_route_count,
            "exact_quote_route_count": self.exact_quote_route_count,
            "exact_qualified_route_count": self.exact_qualified_route_count,
            "net_positive_route_count": self.net_positive_route_count,
            "size_grid_evaluated_count": self.size_grid_evaluated_count,
            "market_candidate_count": self.market_candidate_count,
            "flashloan_eligible_count": self.flashloan_eligible_count,
            "capital_eligible_count": self.capital_eligible_count,
            "builder_eligible_count": self.builder_eligible_count,
            "simulation_pass_count": self.simulation_pass_count,
            "paper_attempt_count": self.paper_attempt_count,
            "paper_complete_count": self.paper_complete_count,
            "paper_rejected_count": self.paper_rejected_count,
            "provider_overlap_cluster_count": self.provider_overlap_cluster_count,
            "rejections": [
                {"reason": reason, "count": count} for reason, count in self.rejections
            ],
            "ratios": _ratios(self),
            "evidence_scope": REPLAY_EVIDENCE_SCOPE,
            "contains_live_evidence": False,
        }


def _ratio(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return f"{numerator / denominator:.6f}"


def _ratios(metrics: RouteQualificationMetrics) -> dict[str, str | None]:
    """Separate named ratios; there is deliberately no single success rate."""

    return {
        "exact_qualification": _ratio(
            metrics.exact_qualified_route_count, metrics.topology_route_count
        ),
        "economic_survival": _ratio(
            metrics.net_positive_route_count, metrics.exact_qualified_route_count
        ),
        "capital_eligibility": _ratio(
            metrics.capital_eligible_count, metrics.net_positive_route_count
        ),
        "simulation_pass": _ratio(
            metrics.simulation_pass_count, metrics.paper_attempt_count
        ),
        "paper_completion": _ratio(
            metrics.paper_complete_count, metrics.paper_attempt_count
        ),
    }


@dataclass(frozen=True, slots=True)
class RouteQualificationRecord:
    """One route's terminal evidence record (typed, fixture/replay only)."""

    route_kind: str
    semantic_route_id: str
    support: RouteSupport
    status: RouteQualificationStatus
    hop_count: int
    venue_kind: VenueKind = VenueKind.RAYDIUM_CPMM
    rejection: CpmmBindingRejection | None = None
    detail: str | None = None
    selected_amount: int | None = None
    conservative_net_atoms: int | None = None
    gross_profit_atoms: int | None = None
    ordered_venues: tuple[str, ...] = ()
    provenance: str = REPLAY_EVIDENCE_SCOPE

    def to_json(self) -> dict[str, object]:
        return {
            "route_kind": self.route_kind,
            "semantic_route_id": self.semantic_route_id,
            "support": self.support.value,
            "status": self.status.value,
            "hop_count": self.hop_count,
            "venue_kind": self.venue_kind.value,
            "rejection": None if self.rejection is None else self.rejection.value,
            "detail": self.detail,
            "selected_amount": (
                None if self.selected_amount is None else str(self.selected_amount)
            ),
            "conservative_net_atoms": (
                None
                if self.conservative_net_atoms is None
                else str(self.conservative_net_atoms)
            ),
            "gross_profit_atoms": (
                None
                if self.gross_profit_atoms is None
                else str(self.gross_profit_atoms)
            ),
            "ordered_venues": list(self.ordered_venues),
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class PreApiRouteQualificationReport:
    """Deterministic end-to-end replay report; digest is canonical JSON."""

    metrics: RouteQualificationMetrics
    records: tuple[RouteQualificationRecord, ...]
    route_support_matrix: tuple[tuple[str, str, str, int], ...]
    blocked_venue_kinds: tuple[str, ...]
    replay_digest: str = ""
    schema_version: str = CPMM_BINDING_SCHEMA_VERSION
    sign_enabled: bool = False
    send_enabled: bool = False
    live_mode: bool = False

    def to_json(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "metrics": self.metrics.to_json(),
            "records": [record.to_json() for record in self.records],
            "route_support_matrix": [
                {
                    "route_kind": route_kind,
                    "support": support,
                    "venue_kind": venue_kind,
                    "count": count,
                }
                for route_kind, support, venue_kind, count in self.route_support_matrix
            ],
            "blocked_venue_kinds": list(self.blocked_venue_kinds),
            "sign_enabled": self.sign_enabled,
            "send_enabled": self.send_enabled,
            "live_mode": self.live_mode,
        }
        if include_digest:
            payload["replay_digest"] = self.replay_digest
        return payload

    @property
    def digest_payload(self) -> str:
        return _hash(self.to_json(include_digest=False))


@dataclass
class _PipelineState:
    rejections: dict[str, int] = field(default_factory=dict)
    records: list[RouteQualificationRecord] = field(default_factory=list)
    provider_overlap_cluster_count: int = 0

    def reject(self, reason: CpmmBindingRejection | str, *, count: int = 1) -> None:
        key = reason.value if isinstance(reason, CpmmBindingRejection) else str(reason)
        self.rejections[key] = self.rejections.get(key, 0) + count

    def record(self, record: RouteQualificationRecord) -> None:
        self.records.append(record)
        if record.rejection is not None:
            self.reject(record.rejection)

    def metrics(self) -> RouteQualificationMetrics:
        return RouteQualificationMetrics(
            rejections=tuple(sorted(self.rejections.items())),
            provider_overlap_cluster_count=self.provider_overlap_cluster_count,
        )


def _reject_pool(
    state: _PipelineState,
    pool: QualifiedCpmmState,
    reason: CpmmBindingRejection,
    detail: str,
) -> None:
    state.record(
        RouteQualificationRecord(
            route_kind="pool",
            semantic_route_id=pool.identity,
            support=RouteSupport.BLOCKED,
            status=RouteQualificationStatus.REJECTED,
            hop_count=1,
            rejection=reason,
            detail=detail,
            ordered_venues=(pool.venue.market_id,),
        )
    )


def _identity_verified_pools(
    pools: Sequence[QualifiedCpmmState], state: _PipelineState
) -> list[QualifiedCpmmState]:
    verified: list[QualifiedCpmmState] = []
    for pool in sorted(pools, key=lambda item: item.venue):
        try:
            QualifiedRaydiumCpmmAdapter.qualify_state(pool)
        except CpmmEvaluationError as exc:
            _reject_pool(
                state,
                pool,
                CpmmBindingRejection.IDENTITY_UNQUALIFIED,
                f"{exc.reason.value}: venue={pool.venue.market_id}",
            )
            continue
        verified.append(pool)
    return verified


def _rooted_pools(
    verified: Sequence[QualifiedCpmmState],
    *,
    now: float,
    max_snapshot_age_seconds: float,
    state: _PipelineState,
) -> list[QualifiedCpmmState]:
    rooted: list[QualifiedCpmmState] = []
    for pool in verified:
        if (
            pool.observed_at > now
            or now >= pool.expires_at
            or now - pool.observed_at > max_snapshot_age_seconds
        ):
            _reject_pool(
                state,
                pool,
                CpmmBindingRejection.STALE_OR_FUTURE_STATE,
                f"venue={pool.venue.market_id}",
            )
            continue
        rooted.append(pool)
    return rooted


def _venue_label(venue: VenueIdentity) -> str:
    return f"{venue.program_id}:{venue.market_id}"


def _lineage_quote(
    label: str,
    lineage: PoolLineage,
    *,
    input_representation: str,
    output_representation: str,
    slot: int,
) -> NormalizedProviderQuote:
    """Project one venue's declared lineage into an R13-K quote shell purely
    for deduplication.  The quote is dedup evidence only and never an
    executable recommendation."""

    return NormalizedProviderQuote(
        provider_id=label,
        provider_generation=REPLAY_EVIDENCE_SCOPE,
        chain="solana",
        direction=QuoteDirection.EXACT_IN,
        input_representation_id=input_representation,
        output_representation_id=output_representation,
        input_amount_raw=1,
        output_amount_raw=1,
        input_amount_normalized=1,
        output_amount_normalized=1,
        correlation=ProviderCorrelation(
            correlation_group=lineage.correlation_group,
            aggregator_lineage=lineage.aggregator_lineage,
            pool_ids=lineage.pool_ids,
        ),
        freshness=QuoteFreshness(received_at_ns=0, slot=slot),
        raw_response_hash=_hash({"dedup": label}),
        request_fingerprint=_hash({"dedup-request": label}),
    )


def _deduplicate_pools(
    rooted: Sequence[QualifiedCpmmState],
    lineage_by_venue: Mapping[VenueIdentity, PoolLineage],
    state: _PipelineState,
) -> list[QualifiedCpmmState]:
    """R13-K pool-identity/lineage dedup before any candidate promotion.

    Missing lineage is UNKNOWN and blocks; correlated venues (same physical
    pool across aggregators) are all rejected, never counted as independent.
    """

    quotes: list[NormalizedProviderQuote] = []
    usable: list[QualifiedCpmmState] = []
    for pool in rooted:
        lineage = lineage_by_venue.get(pool.venue)
        if lineage is None or not lineage.pool_ids:
            _reject_pool(
                state,
                pool,
                CpmmBindingRejection.POOL_LINEAGE_UNKNOWN,
                "lineage absent; independence is UNKNOWN, never assumed",
            )
            continue
        quotes.append(
            _lineage_quote(
                _venue_label(pool.venue),
                lineage,
                input_representation=pool.asset_a.identity,
                output_representation=pool.asset_b.identity,
                slot=pool.slot,
            )
        )
        usable.append(pool)
    clusters = PoolIdentityDeduplicator.group_quotes(quotes)
    state.provider_overlap_cluster_count += len(clusters)
    # A physical pool id owned by more than one venue label means the same
    # underlying liquidity is exposed twice (e.g. two aggregators over one
    # pool).  Every aliased view is rejected; none counts as independent.
    owners_by_pool: dict[tuple[str, str], set[str]] = {}
    for pool in usable:
        label = _venue_label(pool.venue)
        lineage = lineage_by_venue[pool.venue]
        for identity in lineage.pool_ids:
            owners_by_pool.setdefault(identity.key, set()).add(label)
    aliased_labels: set[str] = set()
    for labels in owners_by_pool.values():
        if len(labels) > 1:
            aliased_labels |= labels
    deduplicated: list[QualifiedCpmmState] = []
    for pool in usable:
        if _venue_label(pool.venue) in aliased_labels:
            _reject_pool(
                state,
                pool,
                CpmmBindingRejection.POOL_ALIAS_CORRELATED,
                "same physical pool exposed through overlapping lineage",
            )
            continue
        deduplicated.append(pool)
    return deduplicated


def _route_legs_are_physically_independent(
    leg_venues: Sequence[VenueIdentity],
    lineage_by_venue: Mapping[VenueIdentity, PoolLineage],
) -> CpmmBindingRejection | None:
    """Pairwise R13-K verdict across the route legs.  Route promotion requires
    positive INDEPENDENT evidence between every pair; UNKNOWN blocks."""

    lineages: list[PoolLineage] = []
    for venue in leg_venues:
        lineage = lineage_by_venue.get(venue)
        if lineage is None or not lineage.pool_ids:
            return CpmmBindingRejection.POOL_LINEAGE_UNKNOWN
        lineages.append(lineage)
    quotes = [
        _lineage_quote(
            _venue_label(venue),
            lineage,
            input_representation="dedup",
            output_representation="dedup-pair",
            slot=0,
        )
        for venue, lineage in zip(leg_venues, lineages)
    ]
    for left in range(len(quotes)):
        for right in range(left + 1, len(quotes)):
            verdict = PoolIdentityDeduplicator.correlation_verdict(
                quotes[left], quotes[right]
            )
            if verdict is IndependenceVerdict.CORRELATED:
                return CpmmBindingRejection.POOL_ALIAS_CORRELATED
            if verdict is IndependenceVerdict.UNKNOWN:
                return CpmmBindingRejection.POOL_LINEAGE_UNKNOWN
    return None


def _search_edges(pools: Sequence[QualifiedCpmmState]) -> tuple[SearchEdge, ...]:
    """Marginal-rate edges for the AGG-05 shortlist.  These encode spot
    topology only and never exact output or profit."""

    edges: list[SearchEdge] = []
    for pool in pools:
        generation = pool.generation.identity
        edges.append(
            SearchEdge(
                edge_id=f"{pool.venue.market_id}:a->b",
                input_asset=pool.asset_a.mint,
                output_asset=pool.asset_b.mint,
                pool_key=pool.venue.market_id,
                marginal_rate_numerator=pool.reserve_b,
                marginal_rate_denominator=pool.reserve_a,
                state_generation=generation,
            )
        )
        edges.append(
            SearchEdge(
                edge_id=f"{pool.venue.market_id}:b->a",
                input_asset=pool.asset_b.mint,
                output_asset=pool.asset_a.mint,
                pool_key=pool.venue.market_id,
                marginal_rate_numerator=pool.reserve_a,
                marginal_rate_denominator=pool.reserve_b,
                state_generation=generation,
            )
        )
    return tuple(edges)


def _two_leg_candidates(
    pools: Sequence[QualifiedCpmmState],
    settlement_asset: SolanaAssetIdentity,
    *,
    now: float,
    probe_amount: int,
    max_snapshot_age_seconds: float,
    max_slot_skew: int,
    adapter: QualifiedRaydiumCpmmAdapter,
    state: _PipelineState,
) -> list[tuple[QualifiedCpmmState, QualifiedCpmmState]]:
    """Existing two-leg detector contract: discover A -> B -> A candidates via
    ``CircularArbitrageDetector`` over exact amount-coupled observations."""

    candidates: list[tuple[QualifiedCpmmState, QualifiedCpmmState]] = []
    ordered = sorted(pools, key=lambda item: item.venue)
    for first in ordered:
        if settlement_asset not in (first.asset_a, first.asset_b):
            continue
        other = first.asset_b if first.asset_a == settlement_asset else first.asset_a
        for second in ordered:
            if second.venue == first.venue:
                continue
            if settlement_asset not in (second.asset_a, second.asset_b):
                continue
            second_other = (
                second.asset_b if second.asset_a == settlement_asset else second.asset_a
            )
            if other != second_other:
                continue
            try:
                leg_one = adapter.evaluate(
                    first,
                    input_asset=settlement_asset,
                    requested_input=probe_amount,
                )
                leg_two = adapter.evaluate(
                    second,
                    input_asset=leg_one.output_asset,
                    requested_input=leg_one.conservative_output,
                )
            except CpmmEvaluationError:
                continue
            batch = ObservationBatch(
                (leg_one.to_observation(), leg_two.to_observation()),
                published_at=now,
            )
            pair = DetectorPair(
                pair_id=(
                    f"binding:{_venue_label(first.venue)}>"
                    f"{_venue_label(second.venue)}"
                ),
                base_mint=settlement_asset.mint,
                intermediate_mint=other.mint,
                probe_amount_base_units=probe_amount,
                min_gross_profit_base_units=1,
                max_snapshot_age_seconds=max_snapshot_age_seconds,
                max_slot_skew=max_slot_skew,
            )
            detector = CircularArbitrageDetector((pair,))
            opportunities = detector.detect(batch, now=now)
            if opportunities:
                candidates.append((first, second))
            else:
                for rejection in sorted(
                    detector.last_rejections.values(), key=lambda item: item.pair_id
                ):
                    state.reject(rejection.reason_code)
    return candidates


@dataclass(frozen=True, slots=True)
class _ExactCandidate:
    kind: str
    semantic_route_id: str
    hop_count: int
    ordered_venues: tuple[VenueIdentity, ...]
    two_leg: tuple[QualifiedCpmmState, QualifiedCpmmState] | None
    plan: ExactCpmmRoutePlan | None


def run_pre_api_route_qualification_replay(
    *,
    pools: Sequence[QualifiedCpmmState],
    settlement_asset: SolanaAssetIdentity,
    now: float,
    probe_amount: int,
    economics: CapacityEconomics,
    coordinator: DurableCapitalCoordinator,
    wallet_snapshot: WalletBalanceSnapshot,
    lineage_by_venue: Mapping[VenueIdentity, PoolLineage] | None = None,
    blocked_candidates: Sequence[BlockedVenueCandidate] = (),
    paper_gate: PaperGateInputs | None = None,
    amount_grid: Sequence[int] | None = None,
    max_amount_points: int = 8,
    max_snapshot_age_seconds: float = 5.0,
    max_slot_skew: int = 0,
    max_topology_plans: int = 32,
    max_shortlist_routes: int = 64,
) -> PreApiRouteQualificationReport:
    """One deterministic offline end-to-end replay:

    discovery fixture -> identity -> rooted state -> topology -> unique route
    -> exact sequential evaluation -> PR118 size grid -> all-in economics
    -> paper seam (fail-closed).  All inputs and outputs are fixture/replay
    evidence; no live API call, signing, sending or borrowing occurs.
    """

    if not math.isfinite(now) or now <= 0:
        raise ValueError("now must be a finite positive timestamp")
    _integer(probe_amount, "probe_amount", minimum=1)
    if not 1 <= len(pools) <= 8:
        raise ValueError("replay requires 1..8 pools")
    venues = [pool.venue for pool in pools]
    if len(set(venues)) != len(venues):
        raise ValueError("replay pools must have unique venues")
    if not any(settlement_asset in (pool.asset_a, pool.asset_b) for pool in pools):
        raise ValueError("settlement asset must exist in at least one pool")
    if amount_grid is None:
        grid: tuple[int, ...] = (probe_amount,)
    else:
        grid = tuple(sorted({int(amount) for amount in amount_grid}))
        if not grid or grid[0] <= 0:
            raise ValueError("amount_grid must contain positive integers")
    lineage_map: Mapping[VenueIdentity, PoolLineage] = (
        lineage_by_venue if lineage_by_venue is not None else {}
    )
    gate = paper_gate if paper_gate is not None else PaperGateInputs()
    state = _PipelineState()
    adapter = QualifiedRaydiumCpmmAdapter()

    discovered = len(pools) + len(tuple(blocked_candidates))

    # -- blocked venue families (CLMM/DLMM/orderbook stay typed-blocked) -----
    blocked_kinds: set[str] = set()
    for blocked in blocked_candidates:
        blocked_kinds.add(blocked.venue_kind.value)
        if blocked.venue_kind in (VenueKind.ORDERBOOK, VenueKind.UNKNOWN):
            reason = CpmmBindingRejection.UNSUPPORTED_VENUE_KIND
        else:
            reason = CpmmBindingRejection.MISSING_VENUE_STATE
        state.record(
            RouteQualificationRecord(
                route_kind="blocked-venue",
                semantic_route_id=_hash({"blocked": blocked.label}),
                support=RouteSupport.BLOCKED,
                status=RouteQualificationStatus.REJECTED,
                hop_count=0,
                venue_kind=blocked.venue_kind,
                rejection=reason,
                detail=blocked.missing_evidence,
            )
        )

    # -- identity -> rooted state -> R13-K dedup -----------------------------
    verified = _identity_verified_pools(pools, state)
    identity_verified = len(verified)
    rooted = _rooted_pools(
        verified,
        now=now,
        max_snapshot_age_seconds=max_snapshot_age_seconds,
        state=state,
    )
    rooted_count = len(rooted)
    usable = _deduplicate_pools(rooted, lineage_map, state)

    # Mixed observation generations can never share one local atomic route;
    # partition pools by generation so each group stays internally coherent.
    generation_groups: dict[str, list[QualifiedCpmmState]] = {}
    for pool in usable:
        generation_groups.setdefault(pool.generation.identity, []).append(pool)
    ordered_groups = [generation_groups[key] for key in sorted(generation_groups)]
    if len(ordered_groups) > 1:
        state.record(
            RouteQualificationRecord(
                route_kind="state",
                semantic_route_id=_hash({"generations": sorted(generation_groups)}),
                support=RouteSupport.BLOCKED,
                status=RouteQualificationStatus.REJECTED,
                hop_count=0,
                rejection=CpmmBindingRejection.MIXED_GENERATION,
                detail=(
                    "pools span "
                    f"{len(generation_groups)} observation generations; "
                    "no local atomic route may mix them"
                ),
            )
        )

    # -- topology ------------------------------------------------------------
    exact_candidates: dict[str, _ExactCandidate] = {}
    shortlisted = 0

    for group in ordered_groups:
        for first, second in _two_leg_candidates(
            group,
            settlement_asset,
            now=now,
            probe_amount=probe_amount,
            max_snapshot_age_seconds=max_snapshot_age_seconds,
            max_slot_skew=max_slot_skew,
            adapter=adapter,
            state=state,
        ):
            two_leg_candidate = _ExactCandidate(
                kind="two-leg",
                semantic_route_id=two_leg_semantic_route_id(first, second),
                hop_count=2,
                ordered_venues=(first.venue, second.venue),
                two_leg=(first, second),
                plan=None,
            )
            exact_candidates[two_leg_candidate.semantic_route_id] = two_leg_candidate

        scan = enumerate_exact_cpmm_routes(
            tuple(sorted(group, key=lambda item: item.venue)),
            settlement_asset,
            max_plans=max_topology_plans,
        )
        for plan in scan.plans:
            plan_candidate = _ExactCandidate(
                kind=f"{len(plan.pools)}-pool-cycle",
                semantic_route_id=plan.semantic_route_id,
                hop_count=len(plan.pools),
                ordered_venues=tuple(pool.venue for pool in plan.pools),
                two_leg=None,
                plan=plan,
            )
            exact_candidates.setdefault(
                plan_candidate.semantic_route_id, plan_candidate
            )

        shortlist = search_bounded_cycles(
            _search_edges(group),
            start_asset=settlement_asset.mint,
            min_hops=2,
            max_hops=5,
            max_routes=max_shortlist_routes,
        )
        pool_by_market = {pool.venue.market_id: pool for pool in group}
        for route in shortlist.routes:
            shortlisted += 1
            if route.hop_count not in (2, 3, 4):
                state.record(
                    RouteQualificationRecord(
                        route_kind="multihop-shortlist",
                        semantic_route_id=route.route_id,
                        support=RouteSupport.SHORTLIST_ONLY,
                        status=RouteQualificationStatus.SHORTLIST_ONLY,
                        hop_count=route.hop_count,
                        rejection=CpmmBindingRejection.EXACT_UNSUPPORTED_HOP_COUNT,
                        detail=(
                            f"{route.hop_count}-hop shortlist topology is not "
                            "exact-promoted"
                        ),
                    )
                )
                continue
            try:
                leg_pools: list[QualifiedCpmmState] = []
                for edge in route.edges:
                    leg_pool: QualifiedCpmmState | None = pool_by_market.get(
                        edge.pool_key
                    )
                    if leg_pool is None:
                        raise CpmmBindingError(
                            CpmmBindingRejection.NO_EXACT_EVALUATION,
                            f"shortlist edge {edge.edge_id} has no supported "
                            "exact pool",
                        )
                    if edge.input_asset not in (
                        leg_pool.asset_a.mint,
                        leg_pool.asset_b.mint,
                    ):
                        raise CpmmBindingError(
                            CpmmBindingRejection.NON_CLOSED_PATH,
                            f"shortlist edge {edge.edge_id} does not couple "
                            "to its pool",
                        )
                    leg_pools.append(leg_pool)
                if route.edges[-1].output_asset != settlement_asset.mint:
                    raise CpmmBindingError(
                        CpmmBindingRejection.NON_CLOSED_PATH,
                        "shortlist route does not close to the settlement asset",
                    )
                if route.hop_count == 2:
                    shortlist_candidate = _ExactCandidate(
                        kind="two-leg",
                        semantic_route_id=two_leg_semantic_route_id(
                            leg_pools[0], leg_pools[1]
                        ),
                        hop_count=2,
                        ordered_venues=(leg_pools[0].venue, leg_pools[1].venue),
                        two_leg=(leg_pools[0], leg_pools[1]),
                        plan=None,
                    )
                else:
                    plan = ExactCpmmRoutePlan(settlement_asset, tuple(leg_pools))
                    shortlist_candidate = _ExactCandidate(
                        kind=f"{len(leg_pools)}-pool-cycle",
                        semantic_route_id=plan.semantic_route_id,
                        hop_count=len(leg_pools),
                        ordered_venues=tuple(item.venue for item in leg_pools),
                        two_leg=None,
                        plan=plan,
                    )
                exact_candidates.setdefault(
                    shortlist_candidate.semantic_route_id, shortlist_candidate
                )
            except (CpmmBindingError, ValueError) as exc:
                state.record(
                    RouteQualificationRecord(
                        route_kind="multihop-shortlist",
                        semantic_route_id=route.route_id,
                        support=RouteSupport.SHORTLIST_ONLY,
                        status=RouteQualificationStatus.SHORTLIST_ONLY,
                        hop_count=route.hop_count,
                        rejection=(
                            CpmmBindingRejection.NON_CLOSED_PATH
                            if not isinstance(exc, CpmmBindingError)
                            else exc.reason
                        ),
                        detail=str(exc),
                    )
                )

    topology_route_count = len(exact_candidates)
    unique_semantic_route_count = 0
    aliased_or_correlated = 0
    exact_quote_route_count = 0
    exact_qualified_route_count = 0
    net_positive_route_count = 0
    size_grid_evaluated_count = 0
    capital_eligible_count = 0
    paper_attempt_count = 0
    paper_rejected_count = 0
    builder_eligible_count = 0
    simulation_pass_count = 0
    market_candidate_count = 0
    flashloan_eligible_count = 0

    # -- per-route uniqueness, exact evaluation, sizing, paper seam ----------
    for semantic_route_id in sorted(exact_candidates):
        candidate = exact_candidates[semantic_route_id]
        leg_venues = candidate.ordered_venues
        independence = _route_legs_are_physically_independent(leg_venues, lineage_map)
        support = classify_route_support(
            venue_kind=VenueKind.RAYDIUM_CPMM, hop_count=candidate.hop_count
        )
        venue_labels = tuple(_venue_label(venue) for venue in leg_venues)
        if independence is not None:
            aliased_or_correlated += 1
            state.record(
                RouteQualificationRecord(
                    route_kind=candidate.kind,
                    semantic_route_id=semantic_route_id,
                    support=support,
                    status=RouteQualificationStatus.REJECTED,
                    hop_count=candidate.hop_count,
                    rejection=independence,
                    detail="route legs are not proven physically independent",
                    ordered_venues=venue_labels,
                )
            )
            continue
        unique_semantic_route_count += 1

        # Structural pre-check at the first grid point.  Amount-local failures
        # (zero output, capacity, negative gross) pass through to the full
        # PR118 grid; only structural failures reject the route outright.
        gross_profit: int | None = None
        try:
            if candidate.two_leg is not None:
                first, second = candidate.two_leg
                evaluation = evaluate_exact_two_leg_route(
                    first,
                    second,
                    settlement_asset=settlement_asset,
                    input_amount=grid[0],
                    now=now,
                    max_snapshot_age_seconds=max_snapshot_age_seconds,
                    max_slot_skew=max_slot_skew,
                    adapter=adapter,
                )
                gross_profit = evaluation.gross_profit
            else:
                assert candidate.plan is not None
                route_evaluation = evaluate_exact_cpmm_route(
                    candidate.plan,
                    input_amount=grid[0],
                    now=now,
                    max_snapshot_age_seconds=max_snapshot_age_seconds,
                    max_slot_skew=max_slot_skew,
                    adapter=adapter,
                )
                gross_profit = route_evaluation.conservative_output - grid[0]
        except CpmmBindingError as exc:
            state.record(
                RouteQualificationRecord(
                    route_kind=candidate.kind,
                    semantic_route_id=semantic_route_id,
                    support=support,
                    status=RouteQualificationStatus.REJECTED,
                    hop_count=candidate.hop_count,
                    rejection=exc.reason,
                    detail=str(exc),
                    ordered_venues=venue_labels,
                )
            )
            continue
        except CpmmEvaluationError as exc:
            if exc.reason in (
                CpmmEvaluationRejection.ZERO_OUTPUT,
                CpmmEvaluationRejection.INPUT_CAPACITY_EXCEEDED,
            ):
                pass  # amount-local at this point; the full grid decides
            else:
                if exc.reason is CpmmEvaluationRejection.NO_EXACT_GRAPH_CANDIDATE:
                    mapped = CpmmBindingRejection.STALE_OR_FUTURE_STATE
                elif exc.reason is CpmmEvaluationRejection.INCOHERENT_ROUTE_STATE:
                    mapped = CpmmBindingRejection.SLOT_SKEW_EXCEEDED
                else:
                    mapped = CpmmBindingRejection.NO_EXACT_EVALUATION
                state.record(
                    RouteQualificationRecord(
                        route_kind=candidate.kind,
                        semantic_route_id=semantic_route_id,
                        support=support,
                        status=RouteQualificationStatus.REJECTED,
                        hop_count=candidate.hop_count,
                        rejection=mapped,
                        detail=str(exc),
                        ordered_venues=venue_labels,
                    )
                )
                continue
        except PR118SizingPointRejected:
            pass  # negative gross at this point; the full grid decides

        exact_quote_route_count += 1
        if support is not RouteSupport.EXACT_SUPPORTED:
            state.record(
                RouteQualificationRecord(
                    route_kind=candidate.kind,
                    semantic_route_id=semantic_route_id,
                    support=support,
                    status=RouteQualificationStatus.SHORTLIST_ONLY,
                    hop_count=candidate.hop_count,
                    rejection=CpmmBindingRejection.EXACT_UNSUPPORTED_HOP_COUNT,
                    detail="exact evaluation exists but hop count is not promotable",
                    ordered_venues=venue_labels,
                )
            )
            continue

        # -- PR118 per-size fresh exact re-evaluation -------------------------
        def candidate_factory(amount: int) -> PR118SizingCandidateEvidence:
            if candidate.two_leg is not None:
                leg_first, leg_second = candidate.two_leg
                exact = evaluate_exact_two_leg_route(
                    leg_first,
                    leg_second,
                    settlement_asset=settlement_asset,
                    input_amount=amount,
                    now=now,
                    max_snapshot_age_seconds=max_snapshot_age_seconds,
                    max_slot_skew=max_slot_skew,
                    adapter=adapter,
                )
                route_legs = exact.legs
                provenance = exact.evaluation_id
                route_input = exact.input_amount
                route_output = exact.conservative_output
            else:
                assert candidate.plan is not None
                exact_route = evaluate_exact_cpmm_route(
                    candidate.plan,
                    input_amount=amount,
                    now=now,
                    max_snapshot_age_seconds=max_snapshot_age_seconds,
                    max_slot_skew=max_slot_skew,
                    adapter=adapter,
                )
                route_legs = exact_route.legs
                provenance = exact_route.evaluation_id
                route_input = exact_route.input_amount
                route_output = exact_route.conservative_output
            ledger = economics.ledger_for_legs(
                route_legs,
                input_amount=route_input,
                conservative_output=route_output,
                provenance_hash=provenance,
            )
            conservative_net_for_ledger(ledger)
            capital_candidate = ledger.to_capital_candidate(
                candidate_id=provenance,
                native_costs=economics.native_costs,
            )
            return PR118SizingCandidateEvidence(
                amount_lamports=amount,
                candidate=capital_candidate,
                quote_hashes=tuple(leg.evaluation_id for leg in route_legs),
                route_id=semantic_route_id,
            )

        def sizing_point(amount: int) -> PR118SizingCandidateEvidence:
            try:
                return candidate_factory(amount)
            except CpmmEvaluationError as exc:
                if exc.reason not in (
                    CpmmEvaluationRejection.ZERO_OUTPUT,
                    CpmmEvaluationRejection.INPUT_CAPACITY_EXCEEDED,
                ):
                    raise
                raise PR118SizingPointRejected(exc.reason.value) from exc

        try:
            sizing = evaluate_pr118_non_monotonic_sizing(
                coordinator=coordinator,
                wallet_snapshot=wallet_snapshot,
                amounts_lamports=grid,
                candidate_factory=sizing_point,
                max_evaluations=len(grid),
            )
        except CpmmBindingError as exc:
            state.record(
                RouteQualificationRecord(
                    route_kind=candidate.kind,
                    semantic_route_id=semantic_route_id,
                    support=support,
                    status=RouteQualificationStatus.REJECTED,
                    hop_count=candidate.hop_count,
                    rejection=exc.reason,
                    detail=str(exc),
                    ordered_venues=venue_labels,
                )
            )
            continue
        size_grid_evaluated_count += len(sizing.evaluations) + len(
            sizing.rejected_points
        )
        exact_qualified_route_count += 1
        market_candidate_count += 1
        selected_net = (
            None
            if sizing.selected is None
            else sizing.selected.decision.conservative_net_profit_lamports
        )
        if sizing.selected is None or not sizing.allowed:
            state.record(
                RouteQualificationRecord(
                    route_kind=candidate.kind,
                    semantic_route_id=semantic_route_id,
                    support=support,
                    status=RouteQualificationStatus.REJECTED,
                    hop_count=candidate.hop_count,
                    rejection=CpmmBindingRejection.NET_NEGATIVE,
                    detail=(
                        "no admissible sizing point"
                        if sizing.selected is None
                        else sizing.selected.decision.reason.value
                    ),
                    gross_profit_atoms=gross_profit,
                    ordered_venues=venue_labels,
                )
            )
            continue
        net_positive_route_count += 1
        if sizing.selected.decision.allowed:
            capital_eligible_count += 1
            flashloan_eligible_count += 1

        # -- sender-free paper seam (fail-closed; no fake fills) --------------
        paper_attempt_count += 1
        gate_rejection = evaluate_paper_gate(gate)
        paper_rejected_count += 1
        if gate_rejection not in (
            CpmmBindingRejection.NO_QUALIFIED_LENDER_EDGE,
            CpmmBindingRejection.BUILDER_UNQUALIFIED,
        ):
            builder_eligible_count += 1
        if gate_rejection not in (
            CpmmBindingRejection.NO_QUALIFIED_LENDER_EDGE,
            CpmmBindingRejection.BUILDER_UNQUALIFIED,
            CpmmBindingRejection.SIMULATION_SOURCE_BLOCKED,
        ):
            simulation_pass_count += 1
        state.record(
            RouteQualificationRecord(
                route_kind=candidate.kind,
                semantic_route_id=semantic_route_id,
                support=support,
                status=RouteQualificationStatus.PAPER_BLOCKED,
                hop_count=candidate.hop_count,
                rejection=gate_rejection,
                detail="paper seam blocked; candidate preserved with typed reason",
                selected_amount=sizing.selected_amount_lamports,
                conservative_net_atoms=selected_net,
                gross_profit_atoms=gross_profit,
                ordered_venues=venue_labels,
            )
        )

    metrics = replace(
        state.metrics(),
        discovered_market_count=discovered,
        identity_verified_market_count=identity_verified,
        rooted_state_count=rooted_count,
        topology_route_count=topology_route_count,
        shortlist_route_count=shortlisted,
        unique_semantic_route_count=unique_semantic_route_count,
        aliased_or_correlated_route_count=aliased_or_correlated,
        exact_quote_route_count=exact_quote_route_count,
        exact_qualified_route_count=exact_qualified_route_count,
        net_positive_route_count=net_positive_route_count,
        size_grid_evaluated_count=size_grid_evaluated_count,
        market_candidate_count=market_candidate_count,
        flashloan_eligible_count=flashloan_eligible_count,
        capital_eligible_count=capital_eligible_count,
        builder_eligible_count=builder_eligible_count,
        simulation_pass_count=simulation_pass_count,
        paper_attempt_count=paper_attempt_count,
        paper_rejected_count=paper_rejected_count,
        paper_complete_count=0,
    )

    matrix_counter: dict[tuple[str, str, str], int] = {}
    for record in state.records:
        key = (record.route_kind, record.support.value, record.venue_kind.value)
        matrix_counter[key] = matrix_counter.get(key, 0) + 1
    matrix = tuple(
        (kind, support_value, venue_kind, count)
        for (kind, support_value, venue_kind), count in sorted(matrix_counter.items())
    )
    report = PreApiRouteQualificationReport(
        metrics=metrics,
        records=tuple(state.records),
        route_support_matrix=matrix,
        blocked_venue_kinds=tuple(sorted(blocked_kinds)),
    )
    return replace(report, replay_digest=report.digest_payload)


__all__ = [
    "CPMM_BINDING_SCHEMA_VERSION",
    "BlockedVenueCandidate",
    "CpmmBindingError",
    "CpmmBindingRejection",
    "PaperGateInputs",
    "PoolLineage",
    "PreApiRouteQualificationReport",
    "RouteQualificationMetrics",
    "RouteQualificationRecord",
    "RouteQualificationStatus",
    "RouteSupport",
    "TwoLegExactEvaluation",
    "VenueKind",
    "classify_route_support",
    "conservative_net_for_ledger",
    "evaluate_exact_two_leg_route",
    "evaluate_paper_gate",
    "run_pre_api_route_qualification_replay",
    "two_leg_semantic_route_id",
]
