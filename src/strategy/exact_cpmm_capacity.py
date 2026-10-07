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
from typing import Callable, Iterable
from solders.pubkey import Pubkey

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
    PR118SizingPointRejected,
    PR118TypedCostLedger,
    evaluate_pr118_non_monotonic_sizing,
)
from src.direct_venue.cpmm_math import (
    cpmm_fee_accounted_quote,
    RAYDIUM_FEE_SOURCE_REVISION,
)
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
MAINNET_GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
WSOL_MINT = "So11111111111111111111111111111111111111112"


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
    INVALID_ASSET_IDENTITY = "invalid-asset-identity"
    UNSUPPORTED_MODEL_REVISION = "unsupported-model-revision"
    UNSUPPORTED_DECODER_REVISION = "unsupported-decoder-revision"
    UNSUPPORTED_TOKEN_REVISION = "unsupported-token-revision"
    ASSET_NOT_IN_POOL = "asset-not-in-pool"
    INVALID_AMOUNT = "invalid-amount"
    ZERO_OUTPUT = "zero-output"
    INPUT_CAPACITY_EXCEEDED = "input-capacity-exceeded"
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
    trade_fee_rate_ppm: int | None = None
    protocol_fee_rate_ppm: int = 0
    fund_fee_rate_ppm: int = 0
    creator_fee_rate_ppm: int = 0
    creator_fee_on: str = "both"
    fee_accounting_revision: str = RAYDIUM_FEE_SOURCE_REVISION
    accrued_fees_a: tuple[int, ...] = (0, 0, 0)
    accrued_fees_b: tuple[int, ...] = (0, 0, 0)

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
        if self.trade_fee_rate_ppm is not None:
            _integer(self.trade_fee_rate_ppm, "trade_fee_rate_ppm")
            if self.fee_bps != 0 or self.trade_fee_rate_ppm >= 1_000_000:
                raise ValueError(
                    "explicit ppm fee requires zero legacy fee_bps and valid rate"
                )
        for field in (
            "protocol_fee_rate_ppm",
            "fund_fee_rate_ppm",
            "creator_fee_rate_ppm",
        ):
            _integer(getattr(self, field), field)
            if getattr(self, field) >= 1_000_000:
                raise ValueError("fee rate must be below one million")
        if (
            self.protocol_fee_rate_ppm + self.fund_fee_rate_ppm > 1_000_000
            or self.effective_trade_fee_rate_ppm + self.creator_fee_rate_ppm
            >= 1_000_000
        ):
            raise ValueError("invalid fee rate sums")
        if self.creator_fee_on not in {"both", "token-a", "token-b"}:
            raise ValueError("unsupported creator fee direction")
        for field in ("accrued_fees_a", "accrued_fees_b"):
            vector = tuple(getattr(self, field))
            if len(vector) != 3:
                raise ValueError("three accrued fee counters required")
            for value in vector:
                _integer(value, field)
            object.__setattr__(self, field, vector)
        if (
            self.reserve_a + sum(self.accrued_fees_a) > 2**64 - 1
            or self.reserve_b + sum(self.accrued_fees_b) > 2**64 - 1
        ):
            raise ValueError("pool vault amount exceeds u64")
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
    def effective_trade_fee_rate_ppm(self) -> int:
        return (
            self.fee_bps * 100
            if self.trade_fee_rate_ppm is None
            else self.trade_fee_rate_ppm
        )

    @property
    def identity(self) -> str:
        return _hash(
            {
                "venue": asdict(self.venue),
                "assets": [self.asset_a.identity, self.asset_b.identity],
                "reserves": [str(self.reserve_a), str(self.reserve_b)],
                "fee_bps": self.fee_bps,
                "fee_accounting": {
                    "revision": self.fee_accounting_revision,
                    "trade_rate": self.effective_trade_fee_rate_ppm,
                    "protocol_rate": self.protocol_fee_rate_ppm,
                    "fund_rate": self.fund_fee_rate_ppm,
                    "creator_rate": self.creator_fee_rate_ppm,
                    "creator_on": self.creator_fee_on,
                    "accrued_a": self.accrued_fees_a,
                    "accrued_b": self.accrued_fees_b,
                },
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
        self.qualify_state(state)
        if input_asset == state.asset_a:
            output_asset = state.asset_b
            reserve_in, reserve_out = state.reserve_a, state.reserve_b
            input_is_a = True
        elif input_asset == state.asset_b:
            output_asset = state.asset_a
            reserve_in, reserve_out = state.reserve_b, state.reserve_a
            input_is_a = False
        else:
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.ASSET_NOT_IN_POOL,
                "input asset identity is not part of the pool",
            )
        input_fees = state.accrued_fees_a if input_is_a else state.accrued_fees_b
        if reserve_in + sum(input_fees) + requested_input > 2**64 - 1:
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.INPUT_CAPACITY_EXCEEDED,
                "input vault would overflow u64",
            )
        creator_on_input = (
            state.creator_fee_on == "both"
            or (state.creator_fee_on == "token-a" and input_is_a)
            or (state.creator_fee_on == "token-b" and not input_is_a)
        )
        quote = cpmm_fee_accounted_quote(
            amount_in=requested_input,
            reserve_in=reserve_in,
            reserve_out=reserve_out,
            trade_fee_rate_ppm=state.effective_trade_fee_rate_ppm,
            protocol_fee_rate_ppm=state.protocol_fee_rate_ppm,
            fund_fee_rate_ppm=state.fund_fee_rate_ppm,
            creator_fee_rate_ppm=state.creator_fee_rate_ppm,
            creator_fee_on_input=creator_on_input,
        )
        output, embedded_fee = quote.output_amount, quote.input_fee_amount
        input_counters = list(
            state.accrued_fees_a if input_is_a else state.accrued_fees_b
        )
        output_counters = list(
            state.accrued_fees_b if input_is_a else state.accrued_fees_a
        )
        input_counters[0] += quote.protocol_fee_amount
        input_counters[1] += quote.fund_fee_amount
        (input_counters if creator_on_input else output_counters)[
            2
        ] += quote.creator_fee_amount
        next_state = replace(
            state,
            reserve_a=(
                quote.next_input_reserve if input_is_a else quote.next_output_reserve
            ),
            reserve_b=(
                quote.next_output_reserve if input_is_a else quote.next_input_reserve
            ),
            accrued_fees_a=tuple(input_counters if input_is_a else output_counters),
            accrued_fees_b=tuple(output_counters if input_is_a else input_counters),
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
    def qualify_state(state: QualifiedCpmmState) -> None:
        if state.asset_a.domain != "solana-mainnet":
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.WRONG_DOMAIN,
                "only solana-mainnet is qualified in this slice",
            )
        for asset in (state.asset_a, state.asset_b):
            if (
                asset.genesis_hash != MAINNET_GENESIS
                or asset.token_program != SPL_TOKEN_PROGRAM
            ):
                raise CpmmEvaluationError(
                    CpmmEvaluationRejection.INVALID_ASSET_IDENTITY,
                    "unsupported genesis or token program",
                )
            try:
                Pubkey.from_string(asset.mint)
            except ValueError as exc:
                raise CpmmEvaluationError(
                    CpmmEvaluationRejection.INVALID_ASSET_IDENTITY,
                    "mint must be a canonical public key",
                ) from exc
            if asset.mint == WSOL_MINT and asset.decimals != 9:
                raise CpmmEvaluationError(
                    CpmmEvaluationRejection.INVALID_ASSET_IDENTITY,
                    "WSOL decimals must be nine",
                )
        if state.venue.program_id != RAYDIUM_CPMM_PROGRAM_ID:
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.WRONG_PROGRAM,
                "pool is not the pinned Raydium CPMM program",
            )
        if state.fee_accounting_revision != RAYDIUM_FEE_SOURCE_REVISION:
            raise CpmmEvaluationError(
                CpmmEvaluationRejection.UNSUPPORTED_MODEL_REVISION,
                "fee accounting source revision is not qualified",
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
        self.directed_asset_pairs

    @property
    def directed_asset_pairs(self) -> tuple[tuple[str, str], ...]:
        current = self.settlement_asset
        pairs = []
        visited = {current}
        for index, pool in enumerate(self.pools):
            if current == pool.asset_a:
                following = pool.asset_b
            elif current == pool.asset_b:
                following = pool.asset_a
            else:
                raise ValueError("route assets do not couple")
            if following in visited and index != len(self.pools) - 1:
                raise ValueError("route cannot repeat an intermediate asset")
            visited.add(following)
            pairs.append((current.identity, following.identity))
            current = following
        if current != self.settlement_asset:
            raise ValueError("route does not close")
        return tuple(pairs)

    @property
    def semantic_route_id(self) -> str:
        return _hash(
            {
                "schema": "shadow.cpmm-semantic-route.v2",
                "settlement_asset": self.settlement_asset.identity,
                "ordered_venues": [asdict(pool.venue) for pool in self.pools],
                "ordered_assets": self.directed_asset_pairs,
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


@dataclass(frozen=True, slots=True)
class ExactCpmmTopologyScan:
    plans: tuple[ExactCpmmRoutePlan, ...]
    expansions: int
    stop_reason: str


def enumerate_exact_cpmm_routes(
    pools: tuple[QualifiedCpmmState, ...],
    settlement_asset: SolanaAssetIdentity,
    *,
    max_plans: int = 32,
    max_expansions: int = 1024,
) -> ExactCpmmTopologyScan:
    """Bounded 3/4-hop topology enumeration; contains no quote or sizing math."""
    if not 1 <= len(pools) <= 8 or len({p.venue for p in pools}) != len(pools):
        raise ValueError("require 1..8 unique pools")
    _integer(max_plans, "max_plans", minimum=1)
    _integer(max_expansions, "max_expansions", minimum=1)
    if max_plans > 64 or max_expansions > 4096:
        raise ValueError("topology budget above hard cap")
    ordered = tuple(sorted(pools, key=lambda p: p.venue))
    plans: dict[str, ExactCpmmRoutePlan] = {}
    expansions = 0
    stop = "complete"

    def visit(
        asset: SolanaAssetIdentity,
        path: tuple[QualifiedCpmmState, ...],
        seen: frozenset[SolanaAssetIdentity],
    ) -> None:
        nonlocal expansions, stop
        for pool in ordered:
            if stop != "complete":
                return
            if pool in path or asset not in (pool.asset_a, pool.asset_b):
                continue
            if expansions == max_expansions:
                stop = "expansion-limit"
                return
            expansions += 1
            target = pool.asset_b if asset == pool.asset_a else pool.asset_a
            next_path = (*path, pool)
            if target == settlement_asset:
                if len(next_path) in (3, 4):
                    plan = ExactCpmmRoutePlan(settlement_asset, next_path)
                    if len(plans) == max_plans and plan.semantic_route_id not in plans:
                        stop = "plan-limit"
                        return
                    plans[plan.semantic_route_id] = plan
            elif target not in seen and len(next_path) < 4:
                visit(target, next_path, seen | {target})

    visit(settlement_asset, (), frozenset({settlement_asset}))
    return ExactCpmmTopologyScan(
        tuple(plans[p] for p in sorted(plans)), expansions, stop
    )


def evaluate_exact_cpmm_route(
    plan: ExactCpmmRoutePlan,
    *,
    input_amount: int,
    now: float,
    max_snapshot_age_seconds: float = 5.0,
    max_slot_skew: int = 0,
    adapter: QualifiedRaydiumCpmmAdapter | None = None,
    observation_builder: (
        Callable[[ExactCpmmEdgeEvaluation], MarketObservationV2] | None
    ) = None,
) -> ExactCpmmRouteEvaluation:
    """Re-evaluate every leg at the previous leg's conservative output."""

    # Fail closed on shared state before treating an amount-local failure as skippable.
    _integer(input_amount, "input_amount", minimum=1)
    _integer(max_slot_skew, "max_slot_skew")
    if (
        isinstance(now, bool)
        or isinstance(max_snapshot_age_seconds, bool)
        or not math.isfinite(max_snapshot_age_seconds)
        or max_snapshot_age_seconds <= 0
    ):
        raise ValueError("invalid snapshot clock or age policy")
    if not math.isfinite(now) or max_snapshot_age_seconds < 0 or max_slot_skew < 0:
        raise ValueError("invalid freshness policy")
    if any(
        pool.observed_at > now
        or now >= pool.expires_at
        or now - pool.observed_at > max_snapshot_age_seconds
        for pool in plan.pools
    ):
        raise CpmmEvaluationError(
            CpmmEvaluationRejection.NO_EXACT_GRAPH_CANDIDATE, "stale or future state"
        )
    if (
        max(pool.slot for pool in plan.pools) - min(pool.slot for pool in plan.pools)
        > max_slot_skew
    ):
        raise CpmmEvaluationError(
            CpmmEvaluationRejection.INCOHERENT_ROUTE_STATE, "slot skew"
        )
    evaluator = adapter or QualifiedRaydiumCpmmAdapter()
    for pool in plan.pools:
        evaluator.qualify_state(pool)
    current_asset = plan.settlement_asset
    current_amount = input_amount
    legs: list[ExactCpmmEdgeEvaluation] = []
    edges: list[DirectedQuoteEdge] = []
    for state in plan.pools:
        leg = evaluator.evaluate(
            state, input_asset=current_asset, requested_input=current_amount
        )
        legs.append(leg)
        observation = (
            leg.to_observation()
            if observation_builder is None
            else observation_builder(leg)
        )
        if (
            observation.input_mint != leg.input_asset.mint
            or observation.output_mint != leg.output_asset.mint
            or observation.input_amount != leg.requested_input
            or observation.expected_output != leg.expected_output
            or observation.guaranteed_output != leg.conservative_output
            or observation.slot != state.slot
            or observation.generation != state.generation
            or observation.observed_at != state.observed_at
            or observation.expires_at != state.expires_at
        ):
            raise ValueError("observation builder changed exact amount/state semantics")
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
    if dict(detection.rejections).get("below_min_gross_profit"):
        raise PR118SizingPointRejected("negative-gross-output")
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
        asset = route.legs[0].input_asset
        if (asset.mint, asset.decimals, asset.token_program, asset.genesis_hash) != (
            WSOL_MINT,
            9,
            SPL_TOKEN_PROGRAM,
            MAINNET_GENESIS,
        ):
            raise ValueError("native capacity ledger requires canonical WSOL identity")
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
                "rejected_points": self.pr118_result.to_json()["rejected_points"],
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
        try:
            route = evaluate_exact_cpmm_route(
                plan,
                input_amount=amount,
                now=now,
                max_snapshot_age_seconds=max_snapshot_age_seconds,
                max_slot_skew=max_slot_skew,
            )
        except CpmmEvaluationError as exc:
            if exc.reason not in (
                CpmmEvaluationRejection.ZERO_OUTPUT,
                CpmmEvaluationRejection.INPUT_CAPACITY_EXCEEDED,
            ):
                raise
            raise PR118SizingPointRejected(exc.reason.value) from exc
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
