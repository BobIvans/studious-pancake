"""CLMM/DLMM exact-venue binding into the post-#659 route qualification path.

This module extends the existing R10-1 owner (``src/strategy/cpmm_cycle_binding.py``)
with qualified Raydium CLMM and Meteora DLMM exact evaluators; it adds no
graph, solver, quote kernel, catalog, transport, capital graph or signer. The
decoders/math owners are ``src/providers/raydium_clmm_native.py`` and
``src/providers/meteora_dlmm_native.py`` (pinned source closures, blob-verified).

Evidence discipline:
- every qualified state is immutable decoded evidence with account-set
  hashes, slot, generation and expiry; staleness/skew/mixed-generation
  checks reuse the #659 owner's rejection vocabulary;
- the R13-K physical-pool deduplication (``PoolIdentityDeduplicator``) gates
  route independence via declared ``PoolLineage``;
- sizing is PR118 per-size fresh exact re-evaluation; no quote extrapolation;
- Jupiter Lend connects only as the R02 capacity + R03 unsigned-plan evidence
  seam: the CAP-A reader's admission/gate outputs and the R03 builder's
  unsigned borrow->route->repay assembly are consumed verbatim, with no
  signer, no send, no borrowing, and fail-closed typed blockers;
- paper stays blocked by ``evaluate_paper_gate`` exactly as in #659.

Fixture/replay evidence only: nothing here is live, rooted or profitable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from typing import Any, Mapping, Protocol, Sequence

from src.market.observations import ObservationGeneration
from src.providers.raydium_cpmm_native import NativeCaptureError
from src.providers.meteora_dlmm_native import (
    DlmmBinArray,
    DlmmBinArrayBitmapExtension,
    DlmmSwapQuote,
    LbPairState,
    dlmm_swap_exact_in_quote,
)
from src.providers.raydium_clmm_native import (
    ClmmAmmConfig,
    ClmmPoolState,
    ClmmQuote,
    ClmmTickArray,
    ClmmTickArrayBitmapExtension,
    clmm_exact_in_quote,
)

from src.execution.quote_build_kernel import (
    IndependenceVerdict,
    PoolIdentityDeduplicator,
)

from .cpmm_cycle_binding import _lineage_quote
from .arbitrage_graph import VenueIdentity
from .cpmm_cycle_binding import (
    BlockedVenueCandidate,
    CapacityEconomics,
    CpmmBindingError,
    CpmmBindingRejection,
    PaperGateInputs,
    PoolLineage,
    RouteQualificationRecord,
    RouteQualificationStatus,
    RouteSupport,
    VenueKind,
    classify_route_support,
    evaluate_paper_gate,
    mixed_route_semantic_route_id,
)
from .exact_cpmm_capacity import ExactCpmmEdgeEvaluation, SolanaAssetIdentity
from .exact_cpmm_capacity import _hash
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)
from src.economics.non_monotonic_sizing import (
    build_pr118_amount_grid,
    evaluate_pr118_non_monotonic_sizing,
    PR118SizingCandidateEvidence,
    PR118SizingPointRejected,
)


def _net_for_ledger(ledger) -> int:
    """Conservative net with fail-closed denominations (owner: #659)."""
    from src.economics.capital import CapitalEngineError

    try:
        return ledger.conservative_net_amount()
    except CapitalEngineError as exc:
        raise CpmmBindingError(
            CpmmBindingRejection.UNKNOWN_COST_DENOMINATION,
            str(exc),
        ) from exc


REPLAY_EVIDENCE_SCOPE = "clmm-dlmm-mixed-replay:fixture-only"


class QualifiedVenueState(Protocol):
    """Structural contract for one immutable decoded venue state."""

    venue: VenueIdentity
    asset_a: SolanaAssetIdentity
    asset_b: SolanaAssetIdentity
    slot: int
    observed_at: float
    expires_at: float
    generation: ObservationGeneration

    @property
    def venue_kind(self) -> VenueKind: ...

    @property
    def identity(self) -> str: ...


CLMM_DECODER_REVISION = "raydium-clmm-state.v1"
DLMM_DECODER_REVISION = "meteora-dlmm-state.v1"


def _integer(value: int, field_name: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field_name} must be an integer >= {minimum}")


@dataclass(frozen=True, slots=True)
class QualifiedClmmState:
    """One immutable decoded Raydium CLMM pool + complete dependency set."""

    venue: VenueIdentity
    asset_a: SolanaAssetIdentity
    asset_b: SolanaAssetIdentity
    pool: ClmmPoolState
    config: ClmmAmmConfig
    tick_arrays: tuple[ClmmTickArray, ...]
    bitmap_extension: ClmmTickArrayBitmapExtension | None
    block_timestamp: int | None
    slot: int
    observed_at: float
    expires_at: float
    generation: ObservationGeneration
    account_hashes: tuple[str, ...]
    decoder_revision: str = CLMM_DECODER_REVISION

    @property
    def venue_kind(self) -> VenueKind:
        return VenueKind.RAYDIUM_CLMM

    def __post_init__(self) -> None:
        if not isinstance(self.venue, VenueIdentity):
            raise ValueError("venue must be VenueIdentity")
        if self.asset_a == self.asset_b:
            raise ValueError("pool assets must be distinct")
        if self.pool.token_mint_0 != self.asset_a.mint:
            raise ValueError("asset_a must be pool token mint 0")
        if self.pool.token_mint_1 != self.asset_b.mint:
            raise ValueError("asset_b must be pool token mint 1")
        _integer(self.slot, "slot")
        for digest in self.account_hashes:
            if not digest.strip():
                raise ValueError("account hashes must be non-empty")
        if self.venue.program_id != "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK":
            raise ValueError("venue program must be the pinned Raydium CLMM program")

    @property
    def identity(self) -> str:
        return _hash(
            {
                "venue": {
                    "program_id": self.venue.program_id,
                    "market_id": self.venue.market_id,
                },
                "assets": [self.asset_a.identity, self.asset_b.identity],
                "pool": self.pool.address,
                "slot": self.slot,
                "observed_at": self.observed_at,
                "expires_at": self.expires_at,
                "generation": self.generation.identity,
                "account_hashes": list(self.account_hashes),
                "decoder_revision": self.decoder_revision,
            }
        )


@dataclass(frozen=True, slots=True)
class QualifiedDlmmState:
    """One immutable decoded Meteora DLMM LbPair + complete dependency set."""

    venue: VenueIdentity
    asset_a: SolanaAssetIdentity
    asset_b: SolanaAssetIdentity
    lb_pair: LbPairState
    bin_arrays: tuple[DlmmBinArray, ...]
    bitmap_extension: DlmmBinArrayBitmapExtension | None
    clock_epoch: int
    current_timestamp: int
    slot: int
    observed_at: float
    expires_at: float
    generation: ObservationGeneration
    account_hashes: tuple[str, ...]
    decoder_revision: str = DLMM_DECODER_REVISION

    @property
    def venue_kind(self) -> VenueKind:
        return VenueKind.METEORA_DLMM

    def __post_init__(self) -> None:
        if not isinstance(self.venue, VenueIdentity):
            raise ValueError("venue must be VenueIdentity")
        if self.asset_a == self.asset_b:
            raise ValueError("pool assets must be distinct")
        if self.lb_pair.token_x_mint != self.asset_a.mint:
            raise ValueError("asset_a must be LbPair token X mint")
        if self.lb_pair.token_y_mint != self.asset_b.mint:
            raise ValueError("asset_b must be LbPair token Y mint")
        _integer(self.slot, "slot")
        _integer(self.clock_epoch, "clock_epoch")
        _integer(self.current_timestamp, "current_timestamp")
        for digest in self.account_hashes:
            if not digest.strip():
                raise ValueError("account hashes must be non-empty")
        if self.venue.program_id != "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo":
            raise ValueError("venue program must be the pinned Meteora DLMM program")

    @property
    def identity(self) -> str:
        return _hash(
            {
                "venue": {
                    "program_id": self.venue.program_id,
                    "market_id": self.venue.market_id,
                },
                "assets": [self.asset_a.identity, self.asset_b.identity],
                "lb_pair": self.lb_pair.address,
                "slot": self.slot,
                "observed_at": self.observed_at,
                "expires_at": self.expires_at,
                "generation": self.generation.identity,
                "account_hashes": list(self.account_hashes),
                "decoder_revision": self.decoder_revision,
            }
        )


class QualifiedClmmAdapter:
    """Fail-closed exact evaluator over the pinned CLMM decoder/quote owner."""

    def evaluate(
        self,
        state: QualifiedVenueState,
        *,
        input_asset: SolanaAssetIdentity,
        requested_input: int,
    ) -> ExactCpmmEdgeEvaluation:
        if not isinstance(state, QualifiedClmmState):
            raise CpmmBindingError(
                CpmmBindingRejection.MISSING_VENUE_STATE,
                "CLMM evaluator requires a QualifiedClmmState",
            )
        if input_asset == state.asset_a:
            zero_for_one = True
            output_asset = state.asset_b
        elif input_asset == state.asset_b:
            zero_for_one = False
            output_asset = state.asset_a
        else:
            raise CpmmBindingError(
                CpmmBindingRejection.NO_EXACT_EVALUATION,
                "input asset identity is not part of the CLMM pool",
            )
        try:
            quote = clmm_exact_in_quote(
                state.pool,
                state.config,
                state.tick_arrays,
                requested_input,
                zero_for_one=zero_for_one,
                bitmap_extension=state.bitmap_extension,
                block_timestamp=state.block_timestamp,
            )
        except NativeCaptureError as exc:
            raise CpmmBindingError(
                CpmmBindingRejection.NO_EXACT_EVALUATION,
                f"CLMM exact quote rejected: {exc}",
            ) from exc
        if quote.amount_out <= 0:
            raise CpmmBindingError(
                CpmmBindingRejection.NEGATIVE_GROSS_OUTPUT,
                "CLMM exact quote produced no positive output",
            )
        return ExactCpmmEdgeEvaluation(
            requested_input=requested_input,
            consumed_input=quote.amount_in + quote.fee_amount,
            residual_input=requested_input - quote.amount_in - quote.fee_amount,
            expected_output=quote.amount_out,
            conservative_output=quote.amount_out,
            embedded_fee_input=quote.fee_amount,
            input_asset=input_asset,
            output_asset=output_asset,
            state_before=state,  # type: ignore[arg-type]
            state_after=state,  # type: ignore[arg-type]  # re-quoted per size
        )

    @staticmethod
    def qualify_state(state: QualifiedClmmState) -> None:
        if not isinstance(state, QualifiedClmmState):
            raise CpmmBindingError(
                CpmmBindingRejection.MISSING_VENUE_STATE,
                "CLMM evaluator requires a QualifiedClmmState",
            )
        if state.decoder_revision != CLMM_DECODER_REVISION:
            raise CpmmBindingError(
                (
                    CpmmBindingRejection.UNSUPPORTED_DECODER_REVISION
                    if hasattr(CpmmBindingRejection, "UNSUPPORTED_DECODER_REVISION")
                    else CpmmBindingRejection.NO_EXACT_EVALUATION
                ),
                "CLMM decoder revision is not qualified",
            )


class QualifiedDlmmAdapter:
    """Fail-closed exact evaluator over the pinned DLMM SDK closure port."""

    def evaluate(
        self,
        state: QualifiedVenueState,
        *,
        input_asset: SolanaAssetIdentity,
        requested_input: int,
    ) -> ExactCpmmEdgeEvaluation:
        if not isinstance(state, QualifiedDlmmState):
            raise CpmmBindingError(
                CpmmBindingRejection.MISSING_VENUE_STATE,
                "DLMM evaluator requires a QualifiedDlmmState",
            )
        if input_asset == state.asset_a:
            swap_for_y = True
            output_asset = state.asset_b
        elif input_asset == state.asset_b:
            swap_for_y = False
            output_asset = state.asset_a
        else:
            raise CpmmBindingError(
                CpmmBindingRejection.NO_EXACT_EVALUATION,
                "input asset identity is not part of the DLMM pair",
            )
        try:
            quote = dlmm_swap_exact_in_quote(
                state.lb_pair,
                state.bin_arrays,
                requested_input,
                swap_for_y=swap_for_y,
                clock_epoch=state.clock_epoch,
                current_timestamp=state.current_timestamp,
                bin_array_bitmap_extension=state.bitmap_extension,
            )
        except NativeCaptureError as exc:
            raise CpmmBindingError(
                CpmmBindingRejection.NO_EXACT_EVALUATION,
                f"DLMM exact quote rejected: {exc}",
            ) from exc
        if quote.partial_fill:
            raise CpmmBindingError(
                CpmmBindingRejection.NO_EXACT_EVALUATION,
                "DLMM partial-fill quotes are never promotable",
            )
        if quote.out_amount <= 0:
            raise CpmmBindingError(
                CpmmBindingRejection.NEGATIVE_GROSS_OUTPUT,
                "DLMM exact quote produced no positive output",
            )
        return ExactCpmmEdgeEvaluation(
            requested_input=requested_input,
            consumed_input=quote.consumed_in_amount,
            residual_input=requested_input - quote.consumed_in_amount,
            expected_output=quote.out_amount,
            conservative_output=quote.out_amount,
            embedded_fee_input=quote.fee + quote.transfer_fee_in,
            input_asset=input_asset,
            output_asset=output_asset,
            state_before=state,  # type: ignore[arg-type]
            state_after=state,  # type: ignore[arg-type]  # re-quoted per size
        )

    @staticmethod
    def qualify_state(state: QualifiedDlmmState) -> None:
        if not isinstance(state, QualifiedDlmmState):
            raise CpmmBindingError(
                CpmmBindingRejection.MISSING_VENUE_STATE,
                "DLMM evaluator requires a QualifiedDlmmState",
            )
        if state.decoder_revision != DLMM_DECODER_REVISION:
            raise CpmmBindingError(
                CpmmBindingRejection.NO_EXACT_EVALUATION,
                "DLMM decoder revision is not qualified",
            )


VENUE_EXACT_ADAPTERS: Mapping[VenueKind, object] = {
    VenueKind.RAYDIUM_CLMM: QualifiedClmmAdapter(),
    VenueKind.METEORA_DLMM: QualifiedDlmmAdapter(),
}

EXACT_VENUE_KINDS = (
    VenueKind.RAYDIUM_CPMM,
    VenueKind.RAYDIUM_CLMM,
    VenueKind.METEORA_DLMM,
)


def _coherence_checks(
    legs: Sequence[QualifiedVenueState],
    *,
    settlement_asset: SolanaAssetIdentity,
    now: float,
    max_snapshot_age_seconds: float,
    max_slot_skew: int,
) -> None:
    slots = [leg.slot for leg in legs]
    if max(slots) - min(slots) > max_slot_skew:
        raise CpmmBindingError(
            CpmmBindingRejection.SLOT_SKEW_EXCEEDED, "bounded slot skew violated"
        )
    generations = {leg.generation.identity for leg in legs}
    if len(generations) != 1:
        raise CpmmBindingError(
            CpmmBindingRejection.MIXED_GENERATION,
            "route cannot mix state generations",
        )
    for pool in legs:
        if (
            pool.observed_at > now
            or now >= pool.expires_at
            or now - pool.observed_at > max_snapshot_age_seconds
        ):
            raise CpmmBindingError(
                CpmmBindingRejection.STALE_OR_FUTURE_STATE,
                f"stale or future state for venue {pool.venue.market_id}",
            )
    venues = [pool.venue for pool in legs]
    if len(set(venues)) != len(venues):
        raise CpmmBindingError(
            CpmmBindingRejection.NON_UNIQUE_PHYSICAL_POOL,
            "route cannot repeat a physical venue",
        )


def evaluate_exact_mixed_route(
    legs: Sequence[QualifiedVenueState],
    *,
    settlement_asset: SolanaAssetIdentity,
    input_amount: int,
    now: float,
    max_snapshot_age_seconds: float = 5.0,
    max_slot_skew: int = 0,
    adapters: Mapping[VenueKind, object] | None = None,
) -> tuple[str, tuple[ExactCpmmEdgeEvaluation, ...]]:
    """Sequential exact N-leg (2..4) evaluation over mixed venue families.

    Leg k+1 input is leg k's conservative guaranteed output; the route must
    close back to the settlement asset. Returns (semantic_route_id, legs).
    """
    _integer(input_amount, "input_amount", minimum=1)
    if not 2 <= len(legs) <= 4:
        raise CpmmBindingError(
            CpmmBindingRejection.EXACT_UNSUPPORTED_HOP_COUNT,
            "mixed exact routes support 2..4 legs",
        )
    # An explicit ``adapters`` mapping replaces the default registry entirely:
    # a caller that omits a family gets a typed rejection, never a silent
    # fallback to the module defaults.
    registry: Mapping[VenueKind, Any] = (
        dict(adapters) if adapters is not None else dict(VENUE_EXACT_ADAPTERS)
    )
    for leg in legs:
        kind = getattr(leg, "venue_kind", VenueKind.RAYDIUM_CPMM)
        if kind not in registry:
            raise CpmmBindingError(
                CpmmBindingRejection.UNSUPPORTED_VENUE_KIND,
                f"no qualified exact evaluator for {getattr(kind, 'value', kind)}",
            )
        registry[kind].qualify_state(leg)
    _coherence_checks(
        legs,
        settlement_asset=settlement_asset,
        now=now,
        max_snapshot_age_seconds=max_snapshot_age_seconds,
        max_slot_skew=max_slot_skew,
    )
    evaluations: list[ExactCpmmEdgeEvaluation] = []
    carry_asset = settlement_asset
    carry_amount = input_amount
    for index, leg in enumerate(legs):
        evaluator = registry[leg.venue_kind]
        edge = evaluator.evaluate(
            leg, input_asset=carry_asset, requested_input=carry_amount
        )
        evaluations.append(edge)
        carry_asset = edge.output_asset
        carry_amount = edge.conservative_output
    if carry_asset != settlement_asset:
        raise CpmmBindingError(
            CpmmBindingRejection.NON_CLOSED_PATH,
            "route does not close back to the settlement asset",
        )
    return mixed_route_semantic_route_id(legs), tuple(evaluations)


def route_is_physically_independent(
    legs: Sequence[QualifiedVenueState],
    lineage_by_market: Mapping[str, PoolLineage],
) -> bool:
    """R13-K verdict: pairwise independence of declared physical pools.

    Legs without declared lineage are UNKNOWN and never independent. The
    dedup projection reuses the #659 owner's lineage-quote shell.
    """
    quotes = []
    for leg in legs:
        lineage = lineage_by_market.get(leg.venue.market_id)
        if lineage is None:
            return False
        quotes.append(
            _lineage_quote(
                leg.venue.market_id,
                lineage,
                input_representation=leg.asset_a.mint,
                output_representation=leg.asset_b.mint,
                slot=leg.slot,
            )
        )
    for i in range(len(quotes)):
        for j in range(i + 1, len(quotes)):
            verdict = PoolIdentityDeduplicator.correlation_verdict(quotes[i], quotes[j])
            if verdict is not IndependenceVerdict.INDEPENDENT:
                return False
    return True


@dataclass(frozen=True, slots=True)
class MixedRouteReplayReport:
    """Deterministic mixed-route replay report (fixture/replay evidence only)."""

    metrics: dict[str, object]
    records: tuple[RouteQualificationRecord, ...]
    replay_digest: str
    evidence_scope: str = REPLAY_EVIDENCE_SCOPE
    contains_live_evidence: bool = False


def run_clmm_dlmm_mixed_route_replay(
    *,
    pools: Sequence[QualifiedVenueState],
    lineage_by_market: Mapping[str, PoolLineage],
    settlement_asset: SolanaAssetIdentity,
    now: float,
    probe_amount: int,
    economics: CapacityEconomics,
    coordinator: DurableCapitalCoordinator,
    wallet_snapshot: WalletBalanceSnapshot,
    blocked_candidates: Sequence[BlockedVenueCandidate] = (),
    paper_gate: PaperGateInputs | None = None,
    amount_grid: Sequence[int] | None = None,
    max_amount_points: int = 8,
    max_snapshot_age_seconds: float = 5.0,
    max_slot_skew: int = 0,
    max_routes: int = 64,
    financing_snapshots: Sequence[object] = (),
) -> MixedRouteReplayReport:
    """Deterministic mixed CPMM/CLMM/DLMM route qualification replay.

    Stages: identity -> lineage dedup (R13-K) -> coherent generation/slot ->
    mixed 2/3/4-hop topology enumeration -> exact evaluation -> PR118 per-size
    grid -> Jupiter Lend R02/R03 evidence seam -> typed fail-closed paper gate.
    Fixture/replay only; the report never mixes in live evidence.
    """
    del financing_snapshots  # R02 evidence is consumed via PaperGateInputs; reserved for the runbook
    records: list[RouteQualificationRecord] = []
    rejections: dict[str, int] = {}
    topology_route_count = 0
    unique_semantic_route_count = 0
    aliased_or_correlated = 0
    exact_quote_route_count = 0
    exact_qualified_route_count = 0
    net_positive_route_count = 0
    size_grid_evaluated_count = 0
    flashloan_eligible = 0
    capital_eligible = 0
    builder_eligible = 0
    simulation_pass = 0
    paper_attempt = 0
    paper_rejected = 0
    shortlisted = 0

    blocked_markets = {candidate.label for candidate in blocked_candidates}

    def record_rejection(reason: str) -> None:
        rejections[reason] = rejections.get(reason, 0) + 1

    # candidate routes: every ordered closed cycle of 2..4 distinct venues
    # over the supplied pool set, both directions, mixed venue kinds.
    candidates: list[tuple[QualifiedVenueState, ...]] = []
    markets = [p for p in pools if p.venue.market_id not in blocked_markets]
    for leg_count in (2, 3, 4):
        for start in markets:
            _enumerate_cycles(start, markets, leg_count, candidates)
    topology_route_count = len(candidates)

    unique_candidates: list[tuple[QualifiedVenueState, ...]] = []
    seen_edge_sets: set[frozenset] = set()
    for legs in candidates:
        edge_set = frozenset(_directed_edge(legs, i) for i in range(len(legs)))
        if edge_set not in seen_edge_sets:
            seen_edge_sets.add(edge_set)
            unique_candidates.append(legs)
    candidates = unique_candidates

    seen_routes: set[str] = set()
    for legs in candidates[:max_routes]:
        support_values = [
            classify_route_support(
                venue_kind=leg.venue_kind,
                hop_count=len(legs),
                exact_venues=EXACT_VENUE_KINDS,
            )
            for leg in legs
        ]
        if any(s is not RouteSupport.EXACT_SUPPORTED for s in support_values):
            support = (
                RouteSupport.BLOCKED
                if any(s is RouteSupport.BLOCKED for s in support_values)
                else RouteSupport.SHORTLIST_ONLY
            )
        else:
            support = RouteSupport.EXACT_SUPPORTED
        if support is not RouteSupport.EXACT_SUPPORTED:
            shortlisted += 1
        semantic_route_id = mixed_route_semantic_route_id(legs)
        if semantic_route_id in seen_routes:
            continue
        seen_routes.add(semantic_route_id)
        unique_semantic_route_count += 1
        venue_labels = tuple(leg.venue.market_id for leg in legs)
        if not route_is_physically_independent(legs, lineage_by_market):
            aliased_or_correlated += 1
            record_rejection(CpmmBindingRejection.NON_UNIQUE_PHYSICAL_POOL.value)
            records.append(
                RouteQualificationRecord(
                    route_kind="mixed-exact",
                    semantic_route_id=semantic_route_id,
                    support=support,
                    status=RouteQualificationStatus.REJECTED,
                    hop_count=len(legs),
                    rejection=CpmmBindingRejection.NON_UNIQUE_PHYSICAL_POOL,
                    detail="shared/correlated physical pool resources (R13-K)",
                    ordered_venues=venue_labels,
                )
            )
            continue
        try:
            route_id, route_legs = evaluate_exact_mixed_route(
                legs,
                settlement_asset=settlement_asset,
                input_amount=probe_amount,
                now=now,
                max_snapshot_age_seconds=max_snapshot_age_seconds,
                max_slot_skew=max_slot_skew,
            )
            gross_profit = (
                route_legs[-1].conservative_output - route_legs[0].requested_input
            )
        except CpmmBindingError as exc:
            record_rejection(exc.reason.value)
            records.append(
                RouteQualificationRecord(
                    route_kind="mixed-exact",
                    semantic_route_id=semantic_route_id,
                    support=support,
                    status=RouteQualificationStatus.REJECTED,
                    hop_count=len(legs),
                    rejection=exc.reason,
                    detail=str(exc),
                    ordered_venues=venue_labels,
                )
            )
            continue
        exact_quote_route_count += 1
        if support is not RouteSupport.EXACT_SUPPORTED:
            record_rejection(CpmmBindingRejection.EXACT_UNSUPPORTED_HOP_COUNT.value)
            records.append(
                RouteQualificationRecord(
                    route_kind="mixed-exact",
                    semantic_route_id=semantic_route_id,
                    support=support,
                    status=RouteQualificationStatus.SHORTLIST_ONLY,
                    hop_count=len(legs),
                    rejection=CpmmBindingRejection.EXACT_UNSUPPORTED_HOP_COUNT,
                    ordered_venues=venue_labels,
                )
            )
            continue

        grid = tuple(
            amount_grid
            or build_pr118_amount_grid(
                lower_lamports=probe_amount,
                upper_lamports=probe_amount * 4,
                max_points=max_amount_points,
            )
        )

        def candidate_factory(amount: int) -> PR118SizingCandidateEvidence:
            evaluated_id, evaluated_legs = evaluate_exact_mixed_route(
                legs,
                settlement_asset=settlement_asset,
                input_amount=amount,
                now=now,
                max_snapshot_age_seconds=max_snapshot_age_seconds,
                max_slot_skew=max_slot_skew,
            )
            ledger = economics.ledger_for_legs(
                evaluated_legs,
                input_amount=evaluated_legs[0].requested_input,
                conservative_output=evaluated_legs[-1].conservative_output,
                provenance_hash=evaluated_id,
            )
            _net_for_ledger(ledger)
            capital_candidate = ledger.to_capital_candidate(
                candidate_id=evaluated_id,
                native_costs=economics.native_costs,
            )
            return PR118SizingCandidateEvidence(
                amount_lamports=amount,
                candidate=capital_candidate,
                quote_hashes=tuple(leg.evaluation_id for leg in evaluated_legs),
                route_id=evaluated_id,
            )

        def sizing_point(amount: int) -> PR118SizingCandidateEvidence:
            try:
                return candidate_factory(amount)
            except CpmmBindingError as exc:
                if exc.reason in (
                    CpmmBindingRejection.NEGATIVE_GROSS_OUTPUT,
                    CpmmBindingRejection.NO_EXACT_EVALUATION,
                ):
                    raise PR118SizingPointRejected(exc.reason.value) from exc
                raise

        try:
            sizing = evaluate_pr118_non_monotonic_sizing(
                coordinator=coordinator,
                wallet_snapshot=wallet_snapshot,
                amounts_lamports=grid,
                candidate_factory=sizing_point,
                max_evaluations=len(grid),
            )
        except CpmmBindingError as exc:
            record_rejection(exc.reason.value)
            records.append(
                RouteQualificationRecord(
                    route_kind="mixed-exact",
                    semantic_route_id=semantic_route_id,
                    support=support,
                    status=RouteQualificationStatus.REJECTED,
                    hop_count=len(legs),
                    rejection=exc.reason,
                    detail=str(exc),
                    ordered_venues=venue_labels,
                )
            )
            continue
        except PR118SizingPointRejected:
            sizing = None
        if sizing is not None:
            size_grid_evaluated_count += len(sizing.evaluations) + len(
                sizing.rejected_points
            )
        exact_qualified_route_count += 1
        selected_net = None
        selected_amount = None
        if sizing is None or sizing.selected is None or not sizing.allowed:
            record_rejection(CpmmBindingRejection.NET_NEGATIVE.value)
            records.append(
                RouteQualificationRecord(
                    route_kind="mixed-exact",
                    semantic_route_id=semantic_route_id,
                    support=support,
                    status=RouteQualificationStatus.REJECTED,
                    hop_count=len(legs),
                    rejection=CpmmBindingRejection.NET_NEGATIVE,
                    detail="no admissible PR118 sizing point",
                    gross_profit_atoms=None,
                    ordered_venues=venue_labels,
                )
            )
            continue
        net_positive_route_count += 1
        selected_net = sizing.selected.decision.conservative_net_profit_lamports
        selected_amount = sizing.selected_amount_lamports
        capital_eligible += 1
        flashloan_eligible += 1

        # Jupiter Lend R02/R03 evidence seam: the paper gate consumes the
        # caller-declared seam state; offline defaults stay fail-closed.
        paper_attempt += 1
        gate_rejection = evaluate_paper_gate(paper_gate or PaperGateInputs())
        paper_rejected += 1
        if gate_rejection not in (
            CpmmBindingRejection.NO_QUALIFIED_LENDER_EDGE,
            CpmmBindingRejection.BUILDER_UNQUALIFIED,
        ):
            builder_eligible += 1
        if gate_rejection not in (
            CpmmBindingRejection.NO_QUALIFIED_LENDER_EDGE,
            CpmmBindingRejection.BUILDER_UNQUALIFIED,
            CpmmBindingRejection.SIMULATION_SOURCE_BLOCKED,
        ):
            simulation_pass += 1
        records.append(
            RouteQualificationRecord(
                route_kind="mixed-exact",
                semantic_route_id=semantic_route_id,
                support=support,
                status=RouteQualificationStatus.PAPER_BLOCKED,
                hop_count=len(legs),
                rejection=gate_rejection,
                detail="paper seam blocked; candidate preserved with typed reason",
                selected_amount=selected_amount,
                conservative_net_atoms=selected_net,
                ordered_venues=venue_labels,
            )
        )

    metrics = {
        "topology_route_count": topology_route_count,
        "shortlist_route_count": shortlisted,
        "unique_semantic_route_count": unique_semantic_route_count,
        "aliased_or_correlated_route_count": aliased_or_correlated,
        "exact_quote_route_count": exact_quote_route_count,
        "exact_qualified_route_count": exact_qualified_route_count,
        "net_positive_route_count": net_positive_route_count,
        "size_grid_evaluated_count": size_grid_evaluated_count,
        "flashloan_eligible_count": flashloan_eligible,
        "capital_eligible_count": capital_eligible,
        "builder_eligible_count": builder_eligible,
        "simulation_pass_count": simulation_pass,
        "paper_attempt_count": paper_attempt,
        "paper_rejected_count": paper_rejected,
        "paper_complete_count": 0,
        "rejections": sorted(rejections.items()),
        "evidence_scope": REPLAY_EVIDENCE_SCOPE,
        "contains_live_evidence": False,
    }
    digest = _hash(
        {
            "metrics": metrics,
            "records": [
                {
                    "route": record.semantic_route_id,
                    "status": record.status.value,
                    "rejection": record.rejection.value if record.rejection else None,
                }
                for record in records
            ],
            "pools": [pool.identity for pool in pools],
        }
    )
    return MixedRouteReplayReport(
        metrics=metrics,
        records=tuple(records),
        replay_digest=digest,
    )


def _directed_edge(
    legs: Sequence[QualifiedVenueState], index: int
) -> tuple[str, str, str]:
    """(venue, input_mint, output_mint) for one directed leg (dedup key)."""
    leg = legs[index]
    if index == 0:
        asset_in = legs[0].asset_a.mint
    else:
        previous = legs[index - 1]
        # the chain asset between previous and this leg
        asset_in = _chain_asset(previous, leg)
    asset_out = leg.asset_b.mint if asset_in == leg.asset_a.mint else leg.asset_a.mint
    return leg.venue.market_id, asset_in, asset_out


def _chain_asset(previous: QualifiedVenueState, leg: QualifiedVenueState) -> str:
    if (
        previous.asset_a.mint == leg.asset_a.mint
        or previous.asset_b.mint == leg.asset_a.mint
    ):
        return leg.asset_a.mint
    return leg.asset_b.mint


def _enumerate_cycles(
    start: QualifiedVenueState,
    markets: Sequence[QualifiedVenueState],
    leg_count: int,
    out: list[tuple[QualifiedVenueState, ...]],
) -> None:
    """Depth-first enumeration of simple directed asset cycles seeded at
    ``start`` (both directions); a cycle closes when the final asset equals
    the entry asset of the first leg."""

    def walk(
        path: tuple[QualifiedVenueState, ...],
        asset: SolanaAssetIdentity,
        close: SolanaAssetIdentity,
    ) -> None:
        if len(path) == leg_count:
            if asset == close:
                out.append(path)
            return
        for nxt in markets:
            if any(nxt.venue == leg.venue for leg in path):
                continue
            if nxt.asset_a == asset:
                walk(path + (nxt,), nxt.asset_b, close)
            elif nxt.asset_b == asset:
                walk(path + (nxt,), nxt.asset_a, close)

    for close_asset in (start.asset_a,):
        walk((start,), start.asset_b, close_asset)
        walk((start,), start.asset_a, close_asset)
