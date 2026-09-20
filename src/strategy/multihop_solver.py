"""AGG-05 bounded multihop search and resource-aware exact-route ranking.

Marginal graph search only produces a shortlist. A route is not an executable or
profitable candidate until a caller-supplied exact evaluator has bound amount,
state generation and full resource costs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
import hashlib
import json


class SearchStopReason(StrEnum):
    COMPLETE = "complete"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ExactEvaluationStopReason(StrEnum):
    COMPLETE = "complete"
    BUDGET_EXHAUSTED = "budget_exhausted"


class RouteRejection(StrEnum):
    HOP_LIMIT = "hop_limit"
    COMPUTE_LIMIT = "compute_limit"
    MESSAGE_SIZE_LIMIT = "message_size_limit"
    WRITABLE_ACCOUNT_LIMIT = "writable_account_limit"
    RENT_LIMIT = "rent_limit"
    TOTAL_COST_LIMIT = "total_cost_limit"
    NON_POSITIVE_NET = "non_positive_net"


@dataclass(frozen=True, slots=True)
class SearchEdge:
    edge_id: str
    input_asset: str
    output_asset: str
    pool_key: str
    marginal_rate_numerator: int
    marginal_rate_denominator: int
    state_generation: str
    writable_accounts: tuple[str, ...] = ()
    financing_resources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in (
            "edge_id",
            "input_asset",
            "output_asset",
            "pool_key",
            "state_generation",
        ):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} is required")
        if self.input_asset == self.output_asset:
            raise ValueError("search edge must convert between distinct assets")
        for field in ("marginal_rate_numerator", "marginal_rate_denominator"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive integer")
        for field in ("writable_accounts", "financing_resources"):
            values = tuple(getattr(self, field))
            if len(values) != len(set(values)):
                raise ValueError(f"{field} contains duplicates")
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"{field} must contain nonblank strings")
            object.__setattr__(self, field, tuple(sorted(values)))

    @property
    def marginal_rate(self) -> Fraction:
        return Fraction(self.marginal_rate_numerator, self.marginal_rate_denominator)


@dataclass(frozen=True, slots=True)
class BoundedRoute:
    start_asset: str
    edges: tuple[SearchEdge, ...]

    def __post_init__(self) -> None:
        edges = tuple(self.edges)
        object.__setattr__(self, "edges", edges)
        if len(edges) < 2:
            raise ValueError("route requires at least two edges")
        if edges[0].input_asset != self.start_asset:
            raise ValueError("route does not start at start_asset")
        previous = self.start_asset
        generations = set()
        for edge in edges:
            if edge.input_asset != previous:
                raise ValueError("route edges are not contiguous")
            previous = edge.output_asset
            generations.add(edge.state_generation)
        if previous != self.start_asset:
            raise ValueError("route must close back to start_asset")
        if len(generations) != 1:
            raise ValueError("route cannot mix state generations")

    @property
    def hop_count(self) -> int:
        return len(self.edges)

    @property
    def marginal_multiplier(self) -> Fraction:
        result = Fraction(1, 1)
        for edge in self.edges:
            result *= edge.marginal_rate
        return result

    @property
    def route_id(self) -> str:
        payload = {
            "start_asset": self.start_asset,
            "edges": [edge.edge_id for edge in self.edges],
            "state_generation": self.edges[0].state_generation,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @property
    def writable_accounts(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {account for edge in self.edges for account in edge.writable_accounts}
            )
        )

    @property
    def financing_resources(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    resource
                    for edge in self.edges
                    for resource in edge.financing_resources
                }
            )
        )


@dataclass(frozen=True, slots=True)
class CycleSearchResult:
    routes: tuple[BoundedRoute, ...]
    expansions: int
    max_expansions: int
    stop_reason: SearchStopReason


def search_bounded_cycles(
    edges: Iterable[SearchEdge],
    *,
    start_asset: str,
    min_hops: int = 2,
    max_hops: int = 5,
    max_expansions: int = 10_000,
    max_routes: int = 1_000,
    minimum_marginal_gain_ppm: int = 0,
    pool_simple: bool = True,
) -> CycleSearchResult:
    """Deterministically shortlist bounded cycles without claiming exact profit."""

    if not start_asset.strip():
        raise ValueError("start_asset is required")
    for field, value in (
        ("min_hops", min_hops),
        ("max_hops", max_hops),
        ("max_expansions", max_expansions),
        ("max_routes", max_routes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} must be a positive integer")
    if min_hops < 2 or max_hops < min_hops or max_hops > 5:
        raise ValueError("hop range must satisfy 2 <= min_hops <= max_hops <= 5")
    if (
        isinstance(minimum_marginal_gain_ppm, bool)
        or not isinstance(minimum_marginal_gain_ppm, int)
        or minimum_marginal_gain_ppm < 0
    ):
        raise ValueError("minimum_marginal_gain_ppm must be non-negative")

    ordered = tuple(sorted(tuple(edges), key=lambda item: item.edge_id))
    by_input: dict[str, tuple[SearchEdge, ...]] = {}
    for asset in sorted({edge.input_asset for edge in ordered}):
        by_input[asset] = tuple(edge for edge in ordered if edge.input_asset == asset)

    routes: list[BoundedRoute] = []
    identities: set[str] = set()
    expansions = 0
    exhausted = False
    threshold = Fraction(1_000_000 + minimum_marginal_gain_ppm, 1_000_000)

    def walk(
        current_asset: str,
        path: tuple[SearchEdge, ...],
        used_pools: frozenset[str],
    ) -> None:
        nonlocal expansions, exhausted
        if exhausted:
            return
        if len(routes) >= max_routes:
            exhausted = True
            return
        if len(path) >= max_hops:
            return
        for edge in by_input.get(current_asset, ()):
            if expansions >= max_expansions:
                exhausted = True
                return
            expansions += 1
            if pool_simple and edge.pool_key in used_pools:
                continue
            if path and edge.state_generation != path[0].state_generation:
                continue
            candidate_path = path + (edge,)
            next_asset = edge.output_asset
            next_pools = used_pools | {edge.pool_key}
            if next_asset == start_asset:
                if len(candidate_path) >= min_hops:
                    route = BoundedRoute(start_asset=start_asset, edges=candidate_path)
                    if route.marginal_multiplier >= threshold:
                        identity = route.route_id
                        if identity not in identities:
                            identities.add(identity)
                            routes.append(route)
                            if len(routes) >= max_routes:
                                exhausted = True
                                return
                continue
            walk(next_asset, candidate_path, frozenset(next_pools))
            if exhausted or len(routes) >= max_routes:
                return

    walk(start_asset, (), frozenset())
    routes.sort(key=lambda item: (item.hop_count, item.route_id))
    return CycleSearchResult(
        routes=tuple(routes),
        expansions=expansions,
        max_expansions=max_expansions,
        stop_reason=(
            SearchStopReason.BUDGET_EXHAUSTED
            if exhausted
            else SearchStopReason.COMPLETE
        ),
    )


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    max_hops: int
    max_compute_units: int
    max_message_bytes: int
    max_writable_accounts: int
    max_rent_units: int
    max_total_cost_units: int

    def __post_init__(self) -> None:
        for field in (
            "max_hops",
            "max_compute_units",
            "max_message_bytes",
            "max_writable_accounts",
            "max_rent_units",
            "max_total_cost_units",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive integer")


@dataclass(frozen=True, slots=True)
class RouteVariant:
    route_id: str
    hop_count: int
    amount_units: int
    conservative_net_units: int
    compute_units: int
    message_bytes: int
    writable_accounts: tuple[str, ...]
    rent_units: int
    fee_units: int
    state_generation: str

    def __post_init__(self) -> None:
        if not self.route_id.strip() or not self.state_generation.strip():
            raise ValueError("route_id and state_generation are required")
        for field in (
            "hop_count",
            "amount_units",
            "compute_units",
            "message_bytes",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive integer")
        for field in ("rent_units", "fee_units"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if isinstance(self.conservative_net_units, bool) or not isinstance(
            self.conservative_net_units, int
        ):
            raise ValueError("conservative_net_units must be an integer")
        accounts = tuple(self.writable_accounts)
        if len(accounts) != len(set(accounts)):
            raise ValueError("writable_accounts contains duplicates")
        object.__setattr__(self, "writable_accounts", tuple(sorted(accounts)))

    @property
    def total_explicit_cost_units(self) -> int:
        return self.rent_units + self.fee_units


@dataclass(frozen=True, slots=True)
class ExactRouteEvaluation:
    variants: tuple[RouteVariant, ...]
    evaluated_route_ids: tuple[str, ...]
    stop_reason: ExactEvaluationStopReason


def evaluate_shortlisted_routes(
    routes: Iterable[BoundedRoute],
    *,
    exact_evaluator: Callable[[BoundedRoute], RouteVariant],
    max_evaluations: int,
) -> ExactRouteEvaluation:
    """Bind shortlisted routes to exact amount/state/resource evidence."""

    if (
        isinstance(max_evaluations, bool)
        or not isinstance(max_evaluations, int)
        or max_evaluations <= 0
    ):
        raise ValueError("max_evaluations must be a positive integer")
    ordered = tuple(sorted(tuple(routes), key=lambda item: item.route_id))
    variants: list[RouteVariant] = []
    evaluated: list[str] = []
    for route in ordered[:max_evaluations]:
        variant = exact_evaluator(route)
        if not isinstance(variant, RouteVariant):
            raise TypeError("exact_evaluator must return RouteVariant")
        if variant.route_id != route.route_id:
            raise ValueError("exact evaluator returned a different route identity")
        if variant.hop_count != route.hop_count:
            raise ValueError("exact evaluator hop count mismatch")
        if variant.state_generation != route.edges[0].state_generation:
            raise ValueError("exact evaluator state generation mismatch")
        variants.append(variant)
        evaluated.append(route.route_id)
    return ExactRouteEvaluation(
        variants=tuple(variants),
        evaluated_route_ids=tuple(evaluated),
        stop_reason=(
            ExactEvaluationStopReason.BUDGET_EXHAUSTED
            if len(ordered) > len(evaluated)
            else ExactEvaluationStopReason.COMPLETE
        ),
    )


@dataclass(frozen=True, slots=True)
class RankedFeasibleRoutes:
    accepted: tuple[RouteVariant, ...]
    rejections: tuple[tuple[str, RouteRejection], ...]


def rank_resource_feasible_routes(
    variants: Iterable[RouteVariant],
    *,
    limits: ResourceLimits,
    require_positive_net: bool = True,
) -> RankedFeasibleRoutes:
    accepted: list[RouteVariant] = []
    rejected: list[tuple[str, RouteRejection]] = []
    for variant in variants:
        reason: RouteRejection | None = None
        if variant.hop_count > limits.max_hops:
            reason = RouteRejection.HOP_LIMIT
        elif variant.compute_units > limits.max_compute_units:
            reason = RouteRejection.COMPUTE_LIMIT
        elif variant.message_bytes > limits.max_message_bytes:
            reason = RouteRejection.MESSAGE_SIZE_LIMIT
        elif len(variant.writable_accounts) > limits.max_writable_accounts:
            reason = RouteRejection.WRITABLE_ACCOUNT_LIMIT
        elif variant.rent_units > limits.max_rent_units:
            reason = RouteRejection.RENT_LIMIT
        elif variant.total_explicit_cost_units > limits.max_total_cost_units:
            reason = RouteRejection.TOTAL_COST_LIMIT
        elif require_positive_net and variant.conservative_net_units <= 0:
            reason = RouteRejection.NON_POSITIVE_NET
        if reason is not None:
            rejected.append((variant.route_id, reason))
        else:
            accepted.append(variant)
    accepted.sort(
        key=lambda item: (
            -item.conservative_net_units,
            item.compute_units,
            item.message_bytes,
            item.route_id,
        )
    )
    rejected.sort(key=lambda item: (item[0], item[1].value))
    return RankedFeasibleRoutes(tuple(accepted), tuple(rejected))


@dataclass(frozen=True, slots=True)
class FeeBidOption:
    option_id: str
    priority_fee_units: int
    tip_units: int
    observed_landing_probability_ppm: int | None = None
    label_count: int = 0

    def __post_init__(self) -> None:
        if not self.option_id.strip():
            raise ValueError("option_id is required")
        for field in ("priority_fee_units", "tip_units", "label_count"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if self.observed_landing_probability_ppm is not None:
            probability = self.observed_landing_probability_ppm
            if (
                isinstance(probability, bool)
                or not isinstance(probability, int)
                or not 0 <= probability <= 1_000_000
            ):
                raise ValueError("observed_landing_probability_ppm is out of range")
            if self.label_count <= 0:
                raise ValueError("landing probability requires labelled support")

    @property
    def bid_units(self) -> int:
        return self.priority_fee_units + self.tip_units


@dataclass(frozen=True, slots=True)
class FeeBidDecision:
    selected: FeeBidOption | None
    conservative_net_units: int | None
    reason: str


def select_bounded_fee_bid(
    options: Iterable[FeeBidOption],
    *,
    gross_edge_units: int,
    base_network_fee_units: int,
    max_total_bid_units: int,
    minimum_conservative_net_units: int = 1,
) -> FeeBidDecision:
    """Choose within hard caps; probabilities only break ties when they are labelled."""

    for field, value in (
        ("gross_edge_units", gross_edge_units),
        ("base_network_fee_units", base_network_fee_units),
        ("max_total_bid_units", max_total_bid_units),
        ("minimum_conservative_net_units", minimum_conservative_net_units),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")

    feasible: list[tuple[int, int, int, str, FeeBidOption]] = []
    for option in options:
        if option.bid_units > max_total_bid_units:
            continue
        net = gross_edge_units - base_network_fee_units - option.bid_units
        if net < minimum_conservative_net_units:
            continue
        probability = option.observed_landing_probability_ppm
        supported_probability = -1 if probability is None else probability
        feasible.append(
            (
                -net,
                -supported_probability,
                option.bid_units,
                option.option_id,
                option,
            )
        )
    if not feasible:
        return FeeBidDecision(None, None, "no_cap_respecting_positive_bid")
    feasible.sort()
    option = feasible[0][-1]
    net = gross_edge_units - base_network_fee_units - option.bid_units
    return FeeBidDecision(option, net, "selected_conservative_bounded_bid")


@dataclass(frozen=True, slots=True)
class MultiHopCandidate:
    route_id: str
    hop_count: int
    amount_units: int
    conservative_net_units: int
    state_generation: str


def build_multihop_candidate(
    route: BoundedRoute,
    variant: RouteVariant,
) -> MultiHopCandidate:
    if not 3 <= route.hop_count <= 5:
        raise ValueError("generalized multihop candidate requires 3-5 hops")
    if route.route_id != variant.route_id:
        raise ValueError("route/variant identity mismatch")
    if route.hop_count != variant.hop_count:
        raise ValueError("route/variant hop mismatch")
    if route.edges[0].state_generation != variant.state_generation:
        raise ValueError("route/variant generation mismatch")
    if variant.conservative_net_units <= 0:
        raise ValueError("multihop candidate must be positive after full costs")
    return MultiHopCandidate(
        route_id=route.route_id,
        hop_count=route.hop_count,
        amount_units=variant.amount_units,
        conservative_net_units=variant.conservative_net_units,
        state_generation=variant.state_generation,
    )


__all__ = [
    "BoundedRoute",
    "CycleSearchResult",
    "ExactEvaluationStopReason",
    "ExactRouteEvaluation",
    "FeeBidDecision",
    "FeeBidOption",
    "MultiHopCandidate",
    "RankedFeasibleRoutes",
    "ResourceLimits",
    "RouteRejection",
    "RouteVariant",
    "SearchEdge",
    "SearchStopReason",
    "build_multihop_candidate",
    "evaluate_shortlisted_routes",
    "rank_resource_feasible_routes",
    "search_bounded_cycles",
    "select_bounded_fee_bid",
]
