"""Bounded, offline 3/4-hop discovery over canonical exact observations.

These types are shadow evidence, not executable Opportunities. Venue bindings
must identify the underlying market; a provider name is not a pool identity.
PR118 remains the owner of amount grids and non-monotonic economic sizing.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import math

from src.economics.non_monotonic_sizing import build_pr118_amount_grid
from src.market.snapshots import MarketObservationV2, ObservationBatch


def _identity(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be non-empty normalized text")


def _integer(value: int, name: str, lower: int, upper: int | None = None) -> None:
    if type(value) is not int or value < lower or (upper is not None and value > upper):
        raise ValueError(f"{name} outside bounded integer domain")


@dataclass(frozen=True, slots=True, order=True)
class AssetNode:
    mint: str

    def __post_init__(self) -> None:
        _text(self.mint, "mint")


@dataclass(frozen=True, slots=True, order=True)
class VenueIdentity:
    """Underlying program/market, shared across providers and swap directions."""

    program_id: str
    market_id: str

    def __post_init__(self) -> None:
        _text(self.program_id, "program_id")
        _text(self.market_id, "market_id")


@dataclass(frozen=True, slots=True)
class DirectedQuoteEdge:
    venue: VenueIdentity
    observation: MarketObservationV2

    def __post_init__(self) -> None:
        if not isinstance(self.venue, VenueIdentity):
            raise ValueError("edge requires a typed underlying venue identity")
        if not isinstance(self.observation, MarketObservationV2):
            raise ValueError("edge requires a canonical observation")
        AssetNode(self.observation.input_mint)
        AssetNode(self.observation.output_mint)

    @property
    def source(self) -> AssetNode:
        return AssetNode(self.observation.input_mint)

    @property
    def target(self) -> AssetNode:
        return AssetNode(self.observation.output_mint)

    @property
    def identity(self) -> str:
        # Preserve expiry, expected output, cursor and quote ID as well as the
        # canonical observation ID: changed evidence must change route identity.
        return _identity(
            {"venue": asdict(self.venue), "quote": asdict(self.observation)}
        )


@dataclass(frozen=True, slots=True)
class UniversalArbitrageGraph:
    """Directed multigraph of explicit venue bindings to one immutable batch.

    No rate projection, RPC fetch, decoder or implicit provider-to-pool mapping.
    A hard 512-edge cap bounds graph validation before any detector policy runs.
    """

    batch: ObservationBatch
    edges: tuple[DirectedQuoteEdge, ...]

    def __post_init__(self) -> None:
        edges = tuple(self.edges)
        if len(edges) > 512:
            raise ValueError("graph exceeds 512-edge hard limit")
        active = set(self.batch.active_observations())
        for edge in edges:
            if edge.observation not in active:
                raise ValueError("edge must bind an active observation from this batch")
        edges = tuple(sorted(edges, key=lambda edge: edge.identity))
        identities = tuple(edge.identity for edge in edges)
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate graph edge")
        object.__setattr__(self, "edges", edges)

    @property
    def nodes(self) -> tuple[AssetNode, ...]:
        return tuple(
            sorted({node for edge in self.edges for node in (edge.source, edge.target)})
        )


@dataclass(frozen=True, slots=True)
class CircularShadowRoute:
    """Exact integer amounts coupled through guaranteed output at every hop."""

    edges: tuple[DirectedQuoteEdge, ...]
    batch_id: str
    watermark_identity: str
    generation_identity: str

    def __post_init__(self) -> None:
        edges = tuple(self.edges)
        object.__setattr__(self, "edges", edges)
        if len(edges) not in (3, 4):
            raise ValueError("shadow circular route must have 3 or 4 hops")
        for current, following in zip(edges, edges[1:]):
            if current.target != following.source:
                raise ValueError("route assets are disconnected")
            if (
                current.observation.exact_output_for(current.observation.input_amount)
                != following.observation.input_amount
            ):
                raise ValueError("route requires exact guaranteed amount coupling")
        if edges[-1].target != edges[0].source:
            raise ValueError("route must return to its settlement mint")
        if len({edge.source for edge in edges}) != len(edges):
            raise ValueError("route must be asset-simple except circular closure")
        if len({edge.venue for edge in edges}) != len(edges):
            raise ValueError("route cannot repeat an underlying venue")
        if len({edge.observation.generation for edge in edges}) != 1:
            raise ValueError("route cannot mix observation generations")

    @property
    def amounts_base_units(self) -> tuple[int, ...]:
        return (self.edges[0].observation.input_amount,) + tuple(
            edge.observation.guaranteed_output for edge in self.edges
        )

    @property
    def gross_profit_base_units(self) -> int:
        return self.amounts_base_units[-1] - self.amounts_base_units[0]

    @property
    def identity(self) -> str:
        return _identity(
            {
                "schema": "shadow.circular-graph-route.v1",
                "batch": self.batch_id,
                "watermark": self.watermark_identity,
                "generation": self.generation_identity,
                "ordered_edges": [edge.identity for edge in self.edges],
            }
        )


@dataclass(frozen=True, slots=True)
class CircularGraphPolicy:
    base_mint: str
    lower_amount_base_units: int
    upper_amount_base_units: int
    max_amount_points: int = 8
    min_gross_profit_base_units: int = 1
    max_snapshot_age_seconds: float = 5.0
    max_slot_skew: int = 0
    max_edges: int = 512
    max_expansions: int = 4096
    max_candidates: int = 100

    def __post_init__(self) -> None:
        _text(self.base_mint, "base_mint")
        _integer(self.lower_amount_base_units, "lower_amount_base_units", 1)
        _integer(
            self.upper_amount_base_units,
            "upper_amount_base_units",
            self.lower_amount_base_units,
        )
        _integer(self.max_amount_points, "max_amount_points", 1, 8)
        _integer(self.min_gross_profit_base_units, "min_gross_profit_base_units", 0)
        _integer(self.max_slot_skew, "max_slot_skew", 0)
        _integer(self.max_edges, "max_edges", 1, 512)
        _integer(self.max_expansions, "max_expansions", 1, 100_000)
        _integer(self.max_candidates, "max_candidates", 1, 1000)
        if (
            not math.isfinite(self.max_snapshot_age_seconds)
            or self.max_snapshot_age_seconds <= 0
        ):
            raise ValueError("max_snapshot_age_seconds must be finite and positive")

    @property
    def amount_points(self) -> tuple[int, ...]:
        # PR118's historical argument names say lamports; its integer grid has
        # no asset conversion. Here each point is in the selected base mint.
        return build_pr118_amount_grid(
            lower_lamports=self.lower_amount_base_units,
            upper_lamports=self.upper_amount_base_units,
            max_points=self.max_amount_points,
        )


class GraphSearchStop(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE_BATCH = "incomplete-batch"
    EDGE_LIMIT = "edge-limit"
    EXPANSION_LIMIT = "expansion-limit"
    CANDIDATE_LIMIT = "candidate-limit"


@dataclass(frozen=True, slots=True)
class CircularGraphDetection:
    candidates: tuple[CircularShadowRoute, ...]
    stop_reason: GraphSearchStop
    expansions: int
    rejections: tuple[tuple[str, int], ...]


class CircularGraphCandidateDetector:
    """Deterministic bounded DFS, with no execution or economic authorization."""

    def __init__(self, policy: CircularGraphPolicy) -> None:
        self.policy = policy

    def detect(
        self, graph: UniversalArbitrageGraph, *, now: float
    ) -> CircularGraphDetection:
        if not math.isfinite(now) or now <= 0:
            raise ValueError("now must be a finite positive timestamp")
        policy = self.policy
        candidates: list[CircularShadowRoute] = []
        rejected: Counter[str] = Counter()
        expansions = 0
        stop = GraphSearchStop.COMPLETE

        def result() -> CircularGraphDetection:
            return CircularGraphDetection(
                tuple(sorted(candidates, key=lambda route: route.identity)),
                stop,
                expansions,
                tuple(sorted(rejected.items())),
            )

        if not graph.batch.admissible:
            stop = GraphSearchStop.INCOMPLETE_BATCH
            return result()
        if len(graph.edges) > policy.max_edges:
            stop = GraphSearchStop.EDGE_LIMIT
            return result()

        adjacency: dict[AssetNode, list[DirectedQuoteEdge]] = {}
        for edge in graph.edges:
            quote = edge.observation
            # is_fresh owns age/expiry semantics; also reject future/non-finite
            # timestamps, since the compatibility age function clamps to zero.
            if (
                not math.isfinite(quote.observed_at)
                or quote.observed_at > now
                or (
                    quote.expires_at is not None and not math.isfinite(quote.expires_at)
                )
                or not quote.is_fresh(
                    now=now, max_age_seconds=policy.max_snapshot_age_seconds
                )
            ):
                rejected["stale_or_future_snapshot"] += 1
                continue
            adjacency.setdefault(edge.source, []).append(edge)

        base = AssetNode(policy.base_mint)

        def walk(
            node: AssetNode, amount: int, path: tuple[DirectedQuoteEdge, ...]
        ) -> None:
            nonlocal expansions, stop
            for edge in adjacency.get(node, ()):
                if stop is not GraphSearchStop.COMPLETE:
                    return
                if expansions >= policy.max_expansions:
                    stop = GraphSearchStop.EXPANSION_LIMIT
                    return
                expansions += 1
                quote = edge.observation
                if quote.input_amount != amount:
                    rejected["amount_mismatch"] += 1
                    continue
                if any(previous.venue == edge.venue for previous in path):
                    rejected["repeated_venue"] += 1
                    continue
                quotes = tuple(previous.observation for previous in path) + (quote,)
                if (
                    max(item.slot for item in quotes)
                    - min(item.slot for item in quotes)
                    > policy.max_slot_skew
                ):
                    rejected["slot_skew"] += 1
                    continue
                if path and quote.generation != path[0].observation.generation:
                    rejected["mixed_generation"] += 1
                    continue
                output = quote.exact_output_for(amount)
                extended = path + (edge,)
                if edge.target == base:
                    if len(extended) not in (3, 4):
                        rejected["unsupported_hop_count"] += 1
                        continue
                    route = CircularShadowRoute(
                        extended,
                        graph.batch.batch_id,
                        graph.batch.watermark.identity,
                        graph.batch.generation_identity,
                    )
                    if (
                        route.gross_profit_base_units
                        < policy.min_gross_profit_base_units
                    ):
                        rejected["below_min_gross_profit"] += 1
                        continue
                    candidates.append(route)
                    if len(candidates) >= policy.max_candidates:
                        stop = GraphSearchStop.CANDIDATE_LIMIT
                        return
                elif len(extended) < 4 and output > 0:
                    if edge.target in {previous.source for previous in extended}:
                        rejected["repeated_asset"] += 1
                        continue
                    walk(edge.target, output, extended)

        for amount in policy.amount_points:
            if stop is not GraphSearchStop.COMPLETE:
                break
            walk(base, amount, ())
        return result()
