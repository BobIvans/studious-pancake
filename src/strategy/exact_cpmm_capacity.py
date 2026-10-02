"""Qualified, sender-free CPMM evaluation and sampled capacity evidence.

This module is the bounded bridge between the existing integer CPMM owner,
the PR559 exact-observation graph, and PR118 non-monotonic sizing.  It never
fetches state, builds transactions, signs, submits, or grants live authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
import hashlib
import json
import math
from typing import Iterable

from src.economics.capital import NativeCostBreakdown
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)
from src.economics.non_monotonic_sizing import (
    PR118AssetAmount,
    PR118CostComponentKind,
    PR118CostLedgerEntry,
    PR118FlashRepaymentTerms,
    PR118NonMonotonicSizingResult,
    PR118SizingCandidateEvidence,
    PR118TypedCostLedger,
    evaluate_pr118_non_monotonic_sizing,
)
from src.direct_venue.cpmm_math import cpmm_exact_input_quote
from src.market.observations import MarketObservationV2, ObservationGeneration

from .arbitrage_graph import (
    CircularGraphCandidateDetector,
    CircularGraphPolicy,
    CircularShadowRoute,
    DirectedQuoteEdge,
    UniversalArbitrageGraph,
    VenueIdentity,
)

RAYDIUM_CPMM_PROGRAM_ID = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
PINNED_CPMM_MODEL_REVISION = "super03-cpmm-integer-v1"
PINNED_DECODER_REVISION = "raydium-cpmm-state.v1"
PINNED_TOKEN_REVISION = "spl-token-v1"


def _hash(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be non-empty normalized text")


def _integer(value: int, field: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")


@dataclass(frozen=True, slots=True, order=True)
class SolanaAssetIdentity:
    """Canonical asset identity; symbol is deliberately absent."""

    domain: str
    genesis_hash: str
    mint: str
    token_program: str
    token_revision: str
    decimals: int

    def __post_init__(self) -> None:
        for field in (
            "domain",
            "genesis_hash",
            "mint",
            "token_program",
            "token_revision",
        ):
            _text(getattr(self, field), field)
        _integer(self.decimals, "decimals")
        if self.decimals > 18:
            raise ValueError("decimals must be <= 18")

    @property
    def identity(self) -> str:
        return _hash(asdict(self))


class CpmmEvaluationRejection(StrEnum):
    WRONG_DOMAIN = "wrong-domain"
    WRONG_PROGRAM = "wrong-program"
    UNSUPPORTED_MODEL_REVISION = "unsupported-model-revision"
    UNSUPPORTED_DECODER_REVISION = "unsupported-decoder-revision"
    UNSUPPORTED_TOKEN_REVISION = "unsupported-token-revision"
    ASSET_NOT_IN_POOL = "asset-not-in-pool"
    INVALID_AMOUNT = "invalid-amount"
    ZERO_OUTPUT = "zero-output"
    INCOHERENT_ROUTE_STATE = "incoherent-route-state"
    NO_EXACT_GRAPH_CANDIDATE = "no-exact-graph-candidate"


class CpmmEvaluationError(ValueError):
    def __init__(self, reason: CpmmEvaluationRejection, detail: str) -> None:
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


@dataclass(frozen=True, slots=True)
class QualifiedCpmmState:
    """One immutable, already-decoded pool state for local evaluation."""

    venue: VenueIdentity
    asset_a: SolanaAssetIdentity
    asset_b: SolanaAssetIdentity
    reserve_a: int
    reserve_b: int
    fee_bps: int
    slot: int
    observed_at: float
    expires_at: float
    generation: ObservationGeneration
    decoder_revision: str = PINNED_DECODER_REVISION
    model_revision: str = PINNED_CPMM_MODEL_REVISION

    def __post_init__(self) -> None:
        if not isinstance(self.venue, VenueIdentity):
            raise ValueError("venue must be VenueIdentity")
        if self.asset_a == self.asset_b:
            raise ValueError("pool assets must be distinct")
        if (
            self.asset_a.domain != self.asset_b.domain
            or self.asset_a.genesis_hash != self.asset_b.genesis_hash
        ):
            raise ValueError("pool assets must share one settlement domain")
        _integer(self.reserve_a, "reserve_a", minimum=1)
        _integer(self.reserve_b, "reserve_b", minimum=1)
        _integer(self.fee_bps, "fee_bps")
        if self.fee_bps >= 10_000:
            raise ValueError("fee_bps must be < 10000")
        _integer(self.slot, "slot")
        if not math.isfinite(self.observed_at) or self.observed_at <= 0:
            raise ValueError("observed_at must be finite and positive")
        if not math.isfinite(self.expires_at) or self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be finite and after observed_at")
        if not isinstance(self.generation, ObservationGeneration):
            raise ValueError("generation must be ObservationGeneration")
        _text(self.decoder_revision, "decoder_revision")
        _text(self.model_revision, "model_revision")

    @property
    def identity(self) -> str:
        return _hash(
            {
                "venue": asdict(self.venue),
                "assets": [self.asset_a.identity, self.asset_b.identity],
                "reserves": [str(self.reserve_a), str(self.reserve_b)],
                "fee_bps": self.fee_bps,
                "slot": self.slot,
                "observed_at": self.observed_at,
                "expires_at": self.expires_at,
                "generation": self.generation.identity,
                "decoder_revision": self.decoder_revision,
                "model_revision": self.model_revision,
            }
        )


@dataclass(frozen=True, slots=True)
class ExactCpmmEdgeEvaluation:
    requested_input: int
    consumed_input: int
    residual_input: int
    expected_output: int
    conservative_output: int
    embedded_fee_input: int
    input_asset: SolanaAssetIdentity
    output_asset: SolanaAssetIdentity
    state_before: QualifiedCpmmState
    state_after: QualifiedCpmmState

    def __post_init__(self) -> None:
        for field in (
            "requested_input",
            "consumed_input",
            "residual_input",
            "expected_output",
            "conservative_output",
            "embedded_fee_input",
        ):
            _integer(getattr(self, field), field)
        if self.requested_input <= 0 or self.consumed_input <= 0:
            raise ValueError("requested and consumed input must be positive")
        if self.requested_input != self.consumed_input + self.residual_input:
            raise ValueError("requested input must equal consumed plus residual")
        if self.conservative_output > self.expected_output:
            raise ValueError("conservative output cannot exceed expected output")
        if self.conservative_output <= 0:
            raise ValueError("qualified output must be positive")

    @property
    def evaluation_id(self) -> str:
        return _hash(
            {
                "schema": "shadow.exact-cpmm-edge.v1",
                "requested_input": str(self.requested_input),
                "consumed_input": str(self.consumed_input),
                "residual_input": str(self.residual_input),
                "expected_output": str(self.expected_output),
                "conservative_output": str(self.conservative_output),
                "embedded_fee_input": str(self.embedded_fee_input),
                "input_asset": self.input_asset.identity,
                "output_asset": self.output_asset.identity,
                "state_before": self.state_before.identity,
                "state_after": self.state_after.identity,
            }
        )

    def to_observation(self) -> MarketObservationV2:
        """Project exact evidence into the existing canonical observation owner."""

        return MarketObservationV2(
            provider="raydium-cpmm-qualified-local",
            source="offline-state-fixture",
            input_mint=self.input_asset.mint,
            output_mint=self.output_asset.mint,
            input_amount=self.requested_input,
            expected_output=self.expected_output,
            guaranteed_output=self.conservative_output,
            slot=self.state_before.slot,
            observed_at=self.state_before.observed_at,
            expires_at=self.state_before.expires_at,
            quote_id=self.evaluation_id,
            confidence="qualified-local-integer",
            commitment="fixture",
            request_fingerprint=_hash(
                {
                    "amount": str(self.requested_input),
                    "state": self.state_before.identity,
                    "direction": [
                        self.input_asset.identity,
                        self.output_asset.identity,
                    ],
                }
            ),
            response_hash=self.evaluation_id,
            generation=self.state_before.generation,
        )


class QualifiedRaydiumCpmmAdapter:
    """Fail-closed adapter over the existing integer CPMM math owner."""

    def evaluate(
        self,
        state: QualifiedCpmmState,
        *,
        input_asset: SolanaAssetIdentity,
        requested_input: int,
    ) -> ExactCpmmEdgeEvaluation:
        if isinstance(requested_input, bool) or not isinstance(requested_input, int):
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.INVALID_AMOUNT,
                "requested input must be an exact integer",
            )
        if requested_input <= 0:
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.INVALID_AMOUNT,
                "requested input must be positive",
            )
        self._qualify(state)
        if input_asset == state.asset_a:
            output_asset = state.asset_b
            reserve_in, reserve_out = state.reserve_a, state.reserve_b
            output, embedded_fee = cpmm_exact_input_quote(
                amount_in=requested_input,
                reserve_in=reserve_in,
                reserve_out=reserve_out,
                trade_fee_numerator=state.fee_bps,
                trade_fee_denominator=10_000,
            )
            next_state = replace(
                state,
                reserve_a=state.reserve_a + requested_input,
                reserve_b=state.reserve_b - output,
            )
        elif input_asset == state.asset_b:
            output_asset = state.asset_a
            reserve_in, reserve_out = state.reserve_b, state.reserve_a
            output, embedded_fee = cpmm_exact_input_quote(
                amount_in=requested_input,
                reserve_in=reserve_in,
                reserve_out=reserve_out,
                trade_fee_numerator=state.fee_bps,
                trade_fee_denominator=10_000,
            )
            next_state = replace(
                state,
                reserve_b=state.reserve_b + requested_input,
                reserve_a=state.reserve_a - output,
            )
        else:
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.ASSET_NOT_IN_POOL,
                "input asset identity is not part of the pool",
            )
        if output <= 0 or output >= reserve_out:
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.ZERO_OUTPUT,
                "integer CPMM evaluation produced no admissible output",
            )
        return ExactCpmmEdgeEvaluation(
            requested_input=requested_input,
            consumed_input=requested_input,
            residual_input=0,
            expected_output=output,
            conservative_output=output,
            embedded_fee_input=embedded_fee,
            input_asset=input_asset,
            output_asset=output_asset,
            state_before=state,
            state_after=next_state,
        )

    @staticmethod
    def _qualify(state: QualifiedCpmmState) -> None:
        if state.asset_a.domain != "solana-mainnet":
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.WRONG_DOMAIN,
                "only solana-mainnet is qualified in this slice",
            )
        if state.venue.program_id != RAYDIUM_CPMM_PROGRAM_ID:
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.WRONG_PROGRAM,
                "pool is not the pinned Raydium CPMM program",
            )
        if state.model_revision != PINNED_CPMM_MODEL_REVISION:
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.UNSUPPORTED_MODEL_REVISION,
                "model revision is not qualified",
            )
        if state.decoder_revision != PINNED_DECODER_REVISION:
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.UNSUPPORTED_DECODER_REVISION,
                "decoder revision is not qualified",
            )
        if any(
            asset.token_revision != PINNED_TOKEN_REVISION
            for asset in (state.asset_a, state.asset_b)
        ):
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.UNSUPPORTED_TOKEN_REVISION,
                "transfer-fee or unknown token revisions are outside this slice",
            )


@dataclass(frozen=True, slots=True)
class ExactCpmmRoutePlan:
    settlement_asset: SolanaAssetIdentity
    pools: tuple[QualifiedCpmmState, ...]

    def __post_init__(self) -> None:
        pools = tuple(self.pools)
        object.__setattr__(self, "pools", pools)
        if len(pools) not in (3, 4):
            raise ValueError("bounded route plan requires exactly 3 or 4 pools")
        if len({pool.venue for pool in pools}) != len(pools):
            raise ValueError("bounded route plan cannot repeat a venue")
        if len({pool.generation.identity for pool in pools}) != 1:
            raise ValueError("bounded route plan cannot mix state generations")
        if any(
            self.settlement_asset not in (pool.asset_a, pool.asset_b)
            for pool in (pools[0], pools[-1])
        ):
            raise ValueError("route endpoints must contain the settlement asset")

    @property
    def semantic_route_id(self) -> str:
        return _hash(
            {
                "schema": "shadow.cpmm-semantic-route.v1",
                "settlement_asset": self.settlement_asset.identity,
                "ordered_venues": [asdict(pool.venue) for pool in self.pools],
            }
        )


@dataclass(frozen=True, slots=True)
class ExactCpmmRouteEvaluation:
    semantic_route_id: str
    graph_route: CircularShadowRoute
    legs: tuple[ExactCpmmEdgeEvaluation, ...]

    @property
    def input_amount(self) -> int:
        return self.legs[0].requested_input

    @property
    def conservative_output(self) -> int:
        return self.legs[-1].conservative_output

    @property
    def evaluation_id(self) -> str:
        return _hash(
            {
                "schema": "shadow.exact-cpmm-route.v1",
                "semantic_route_id": self.semantic_route_id,
                "graph_route_id": self.graph_route.identity,
                "ordered_leg_evaluations": [leg.evaluation_id for leg in self.legs],
            }
        )


def evaluate_exact_cpmm_route(
    plan: ExactCpmmRoutePlan,
    *,
    input_amount: int,
    now: float,
    max_snapshot_age_seconds: float = 5.0,
    max_slot_skew: int = 0,
    adapter: QualifiedRaydiumCpmmAdapter | None = None,
) -> ExactCpmmRouteEvaluation:
    """Re-evaluate every leg at the previous leg's conservative output."""

    evaluator = adapter or QualifiedRaydiumCpmmAdapter()
    current_asset = plan.settlement_asset
    current_amount = input_amount
    legs: list[ExactCpmmEdgeEvaluation] = []
    edges: list[DirectedQuoteEdge] = []
    for state in plan.pools:
        leg = evaluator.evaluate(
            state, input_asset=current_asset, requested_input=current_amount
        )
        legs.append(leg)
        observation = leg.to_observation()
        edges.append(DirectedQuoteEdge(state.venue, observation))
        current_asset = leg.output_asset
        current_amount = leg.conservative_output
    if current_asset != plan.settlement_asset:
        raise CpmmEvaluationError(
            CpmmEvaluationRejection.INCOHERENT_ROUTE_STATE,
            "ordered pools do not close back to settlement asset",
        )

    # ObservationBatch's compatibility constructor creates a deterministic
    # watermark from the exact observations; PR559 still owns graph admission.
    from src.market.observations import ObservationBatch

    graph = UniversalArbitrageGraph(
        ObservationBatch(tuple(edge.observation for edge in edges)), tuple(edges)
    )
    detection = CircularGraphCandidateDetector(
        CircularGraphPolicy(
            base_mint=plan.settlement_asset.mint,
            lower_amount_base_units=input_amount,
            upper_amount_base_units=input_amount,
            max_amount_points=1,
            min_gross_profit_base_units=0,
            max_snapshot_age_seconds=max_snapshot_age_seconds,
            max_slot_skew=max_slot_skew,
        )
    ).detect(graph, now=now)
    if len(detection.candidates) != 1:
        raise CpmmEvaluationError(
            CpmmEvaluationRejection.NO_EXACT_GRAPH_CANDIDATE,
            f"PR559 rejected the route ({detection.stop_reason.value}; "
            f"rejections={dict(detection.rejections)})",
        )
    return ExactCpmmRouteEvaluation(
        plan.semantic_route_id, detection.candidates[0], tuple(legs)
    )


@dataclass(frozen=True, slots=True)
class CapacityEconomics:
    """Known SOL/WSOL financing and wallet costs for every sampled amount."""

    settlement_asset_id: str
    flash_fee_bps: int
    protocol_rounding_atoms: int
    native_costs: NativeCostBreakdown
    slippage_buffer_atoms: int = 0
    uncertainty_buffer_atoms: int = 0

    def __post_init__(self) -> None:
        if self.settlement_asset_id not in {"SOL", "WSOL"}:
            raise ValueError("first capacity slice requires SOL/WSOL settlement")
        for field in (
            "flash_fee_bps",
            "protocol_rounding_atoms",
            "slippage_buffer_atoms",
            "uncertainty_buffer_atoms",
        ):
            _integer(getattr(self, field), field)
        if self.flash_fee_bps >= 10_000:
            raise ValueError("flash_fee_bps must be < 10000")

    def ledger_for(self, route: ExactCpmmRouteEvaluation) -> PR118TypedCostLedger:
        fee = (route.input_amount * self.flash_fee_bps + 9_999) // 10_000
        entries: list[PR118CostLedgerEntry] = []
        if self.slippage_buffer_atoms:
            entries.append(
                PR118CostLedgerEntry(
                    self.settlement_asset_id,
                    PR118CostComponentKind.SLIPPAGE,
                    self.slippage_buffer_atoms,
                )
            )
        if self.uncertainty_buffer_atoms:
            entries.append(
                PR118CostLedgerEntry(
                    self.settlement_asset_id,
                    PR118CostComponentKind.UNCERTAINTY,
                    self.uncertainty_buffer_atoms,
                )
            )
        return PR118TypedCostLedger(
            min_out=PR118AssetAmount(
                self.settlement_asset_id, route.conservative_output
            ),
            flash_repayment=PR118FlashRepaymentTerms(
                self.settlement_asset_id,
                route.input_amount,
                fee,
                self.protocol_rounding_atoms,
            ),
            entries=tuple(entries),
            route_provenance_hash=route.evaluation_id,
        )


@dataclass(frozen=True, slots=True)
class ExactCapacityPoint:
    amount: int
    semantic_route_id: str
    evaluation_id: str
    ordered_leg_evaluation_ids: tuple[str, ...]
    conservative_output: int
    ledger: PR118TypedCostLedger
    allowed: bool
    decision_reason: str
    conservative_net_atoms: int

    def to_json(self) -> dict[str, object]:
        return {
            "amount": str(self.amount),
            "semantic_route_id": self.semantic_route_id,
            "evaluation_id": self.evaluation_id,
            "ordered_leg_evaluation_ids": list(self.ordered_leg_evaluation_ids),
            "conservative_output": str(self.conservative_output),
            "ledger": self.ledger.to_json(),
            "allowed": self.allowed,
            "decision_reason": self.decision_reason,
            "conservative_net_atoms": str(self.conservative_net_atoms),
        }


@dataclass(frozen=True, slots=True)
class ExactCapacityReport:
    semantic_route_id: str
    points: tuple[ExactCapacityPoint, ...]
    selected_amount: int | None
    budget_status: str
    pr118_result: PR118NonMonotonicSizingResult

    @property
    def report_id(self) -> str:
        return _hash(
            {
                "schema": "shadow.sampled-cpmm-capacity.v1",
                "semantic_route_id": self.semantic_route_id,
                "points": [point.to_json() for point in self.points],
                "selected_amount": self.selected_amount,
                "budget_status": self.budget_status,
            }
        )


def evaluate_sampled_cpmm_capacity(
    plan: ExactCpmmRoutePlan,
    *,
    amounts: Iterable[int],
    economics: CapacityEconomics,
    coordinator: DurableCapitalCoordinator,
    wallet_snapshot: WalletBalanceSnapshot,
    now: float,
    max_evaluations: int = 8,
    max_snapshot_age_seconds: float = 5.0,
    max_slot_skew: int = 0,
) -> ExactCapacityReport:
    """Let PR118 select only among independently evaluated exact points."""

    evaluated: dict[int, tuple[ExactCpmmRouteEvaluation, PR118TypedCostLedger]] = {}

    def candidate_factory(amount: int) -> PR118SizingCandidateEvidence:
        route = evaluate_exact_cpmm_route(
            plan,
            input_amount=amount,
            now=now,
            max_snapshot_age_seconds=max_snapshot_age_seconds,
            max_slot_skew=max_slot_skew,
        )
        ledger = economics.ledger_for(route)
        evaluated[amount] = (route, ledger)
        candidate = ledger.to_capital_candidate(
            candidate_id=route.evaluation_id,
            native_costs=economics.native_costs,
        )
        return PR118SizingCandidateEvidence(
            amount_lamports=amount,
            candidate=candidate,
            quote_hashes=tuple(leg.evaluation_id for leg in route.legs),
            route_id=route.semantic_route_id,
        )

    result = evaluate_pr118_non_monotonic_sizing(
        coordinator=coordinator,
        wallet_snapshot=wallet_snapshot,
        amounts_lamports=amounts,
        candidate_factory=candidate_factory,
        max_evaluations=max_evaluations,
    )
    points: list[ExactCapacityPoint] = []
    for item in result.evaluations:
        route, ledger = evaluated[item.amount_lamports]
        points.append(
            ExactCapacityPoint(
                amount=item.amount_lamports,
                semantic_route_id=route.semantic_route_id,
                evaluation_id=route.evaluation_id,
                ordered_leg_evaluation_ids=tuple(
                    leg.evaluation_id for leg in route.legs
                ),
                conservative_output=route.conservative_output,
                ledger=ledger,
                allowed=item.allowed,
                decision_reason=item.decision.reason.value,
                conservative_net_atoms=(item.decision.conservative_net_profit_lamports),
            )
        )
    return ExactCapacityReport(
        semantic_route_id=plan.semantic_route_id,
        points=tuple(points),
        selected_amount=result.selected_amount_lamports,
        budget_status=result.stop_reason.value,
        pr118_result=result,
    )


__all__ = [
    "CapacityEconomics",
    "CpmmEvaluationError",
    "CpmmEvaluationRejection",
    "ExactCapacityPoint",
    "ExactCapacityReport",
    "ExactCpmmEdgeEvaluation",
    "ExactCpmmRouteEvaluation",
    "ExactCpmmRoutePlan",
    "PINNED_CPMM_MODEL_REVISION",
    "PINNED_DECODER_REVISION",
    "PINNED_TOKEN_REVISION",
    "QualifiedCpmmState",
    "QualifiedRaydiumCpmmAdapter",
    "RAYDIUM_CPMM_PROGRAM_ID",
    "SolanaAssetIdentity",
    "evaluate_exact_cpmm_route",
    "evaluate_sampled_cpmm_capacity",
]
