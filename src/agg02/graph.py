"""AGG-02 asset, operation, shared-resource and evidence lineage graphs."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Mapping

from .contracts import Agg02Error, canonical_hash


@dataclass(frozen=True, slots=True)
class AssetIdentity:
    chain_id: str
    onchain_id: str
    token_program: str
    decimals: int
    native: bool = False
    underlying_asset_id: str | None = None

    def __post_init__(self) -> None:
        if not self.chain_id or not self.onchain_id or not self.token_program:
            raise Agg02Error("AGG02_ASSET_IDENTITY_INCOMPLETE")
        if (
            isinstance(self.decimals, bool)
            or not isinstance(self.decimals, int)
            or self.decimals < 0
        ):
            raise Agg02Error("AGG02_ASSET_DECIMALS_INVALID")
        if not isinstance(self.native, bool):
            raise Agg02Error("AGG02_ASSET_NATIVE_FLAG_INVALID")

    @property
    def asset_id(self) -> str:
        return canonical_hash(
            {
                "chain_id": self.chain_id,
                "onchain_id": self.onchain_id,
                "token_program": self.token_program,
                "native": self.native,
            }
        )


@dataclass(frozen=True, slots=True)
class OperationEdge:
    edge_id: str
    kind: str
    input_asset_ids: tuple[str, ...]
    output_asset_ids: tuple[str, ...]
    dependency_ids: tuple[str, ...]
    read_resources: tuple[str, ...] = ()
    write_resources: tuple[str, ...] = ()
    economic_resources: tuple[str, ...] = ()
    generation: str = "v1"
    executable: bool = True

    def __post_init__(self) -> None:
        if not self.edge_id or not self.kind or not self.generation:
            raise Agg02Error("AGG02_OPERATION_IDENTITY_INCOMPLETE")
        if not self.input_asset_ids or not self.output_asset_ids:
            raise Agg02Error("AGG02_OPERATION_ASSETS_REQUIRED")
        if not self.dependency_ids:
            raise Agg02Error("AGG02_OPERATION_DEPENDENCIES_REQUIRED")


@dataclass(frozen=True, slots=True)
class ExecutableGraph:
    assets: Mapping[str, AssetIdentity]
    edges: Mapping[str, OperationEdge]
    generation: str

    def __post_init__(self) -> None:
        if not self.assets or not self.edges or not self.generation:
            raise Agg02Error("AGG02_EMPTY_EXECUTABLE_GRAPH")
        for asset_id, asset in self.assets.items():
            if asset_id != asset.asset_id:
                raise Agg02Error("AGG02_ASSET_REGISTRY_KEY_MISMATCH")
        for edge_id, edge in self.edges.items():
            if edge_id != edge.edge_id:
                raise Agg02Error("AGG02_EDGE_REGISTRY_KEY_MISMATCH")
            if not edge.executable:
                raise Agg02Error("AGG02_NON_EXECUTABLE_EDGE_IN_GRAPH")
            unknown = (
                set(edge.input_asset_ids) | set(edge.output_asset_ids)
            ) - set(self.assets)
            if unknown:
                raise Agg02Error("AGG02_EDGE_UNKNOWN_ASSET")


@dataclass(frozen=True, slots=True)
class RouteDefinition:
    route_id: str
    edge_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.route_id or not self.edge_ids:
            raise Agg02Error("AGG02_ROUTE_INVALID")


class AffectedRouteIndex:
    def __init__(
        self, graph: ExecutableGraph, routes: Iterable[RouteDefinition]
    ) -> None:
        self._graph = graph
        self._routes = tuple(routes)
        reverse: dict[str, set[str]] = {}
        for route in self._routes:
            for edge_id in route.edge_ids:
                try:
                    edge = graph.edges[edge_id]
                except KeyError as exc:
                    raise Agg02Error("AGG02_ROUTE_UNKNOWN_EDGE") from exc
                for dependency in edge.dependency_ids:
                    reverse.setdefault(dependency, set()).add(route.route_id)
        self._reverse = reverse

    def affected_by(self, dependency_ids: Iterable[str]) -> tuple[str, ...]:
        affected: set[str] = set()
        for dependency_id in dependency_ids:
            affected.update(self._reverse.get(dependency_id, ()))
        return tuple(sorted(affected))


@dataclass(frozen=True, slots=True)
class RouteResourceFootprint:
    route_id: str
    read_resources: frozenset[str]
    write_resources: frozenset[str]
    economic_resources: frozenset[str]


def route_resource_footprint(
    graph: ExecutableGraph, route: RouteDefinition
) -> RouteResourceFootprint:
    reads: set[str] = set()
    writes: set[str] = set()
    economics: set[str] = set()
    for edge_id in route.edge_ids:
        edge = graph.edges[edge_id]
        reads.update(edge.read_resources)
        writes.update(edge.write_resources)
        economics.update(edge.economic_resources)
    return RouteResourceFootprint(
        route.route_id, frozenset(reads), frozenset(writes), frozenset(economics)
    )


def routes_conflict(
    left: RouteResourceFootprint, right: RouteResourceFootprint
) -> bool:
    if left.write_resources & (right.write_resources | right.read_resources):
        return True
    if right.write_resources & left.read_resources:
        return True
    return bool(left.economic_resources & right.economic_resources)


@dataclass(frozen=True, slots=True)
class CapacityPoint:
    input_amount: int
    output_amount: int | None
    feasible: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.input_amount, bool)
            or not isinstance(self.input_amount, int)
            or self.input_amount <= 0
        ):
            raise Agg02Error("AGG02_CAPACITY_INPUT_INVALID")
        if self.output_amount is not None and (
            isinstance(self.output_amount, bool)
            or not isinstance(self.output_amount, int)
            or self.output_amount < 0
        ):
            raise Agg02Error("AGG02_CAPACITY_OUTPUT_INVALID")
        if self.feasible and self.output_amount is None:
            raise Agg02Error("AGG02_FEASIBLE_CAPACITY_WITHOUT_OUTPUT")


@dataclass(frozen=True, slots=True)
class CapacitySurface:
    edge_id: str
    state_frame_hash: str
    points: tuple[CapacityPoint, ...]

    def __post_init__(self) -> None:
        if not self.edge_id or not self.state_frame_hash or not self.points:
            raise Agg02Error("AGG02_CAPACITY_SURFACE_INVALID")
        amounts = tuple(point.input_amount for point in self.points)
        if tuple(sorted(set(amounts))) != amounts:
            raise Agg02Error("AGG02_CAPACITY_POINTS_NOT_STRICTLY_SORTED")


@dataclass(frozen=True, slots=True)
class FeeComponent:
    category: str
    asset_id: str
    amount: int | None
    included_in_output: bool
    state_generation: str

    def __post_init__(self) -> None:
        if not self.category or not self.asset_id or not self.state_generation:
            raise Agg02Error("AGG02_FEE_COMPONENT_INVALID")
        if self.amount is not None and (
            isinstance(self.amount, bool)
            or not isinstance(self.amount, int)
            or self.amount < 0
        ):
            raise Agg02Error("AGG02_FEE_AMOUNT_INVALID")


@dataclass(frozen=True, slots=True)
class FeeSurface:
    edge_id: str
    components: tuple[FeeComponent, ...]

    def __post_init__(self) -> None:
        if not self.edge_id or not self.components:
            raise Agg02Error("AGG02_FEE_SURFACE_INVALID")
        if any(component.amount is None for component in self.components):
            raise Agg02Error("AGG02_UNKNOWN_FEE_BLOCKS_ADMISSION")


@dataclass(frozen=True, slots=True)
class EvidenceNode:
    node_id: str
    kind: str
    payload_hash: str
    parent_ids: tuple[str, ...] = ()


class EvidenceLineageDAG:
    def __init__(self, nodes: Iterable[EvidenceNode]) -> None:
        self.nodes = {node.node_id: node for node in nodes}
        if not self.nodes:
            raise Agg02Error("AGG02_EMPTY_EVIDENCE_DAG")
        for node in self.nodes.values():
            missing = set(node.parent_ids) - set(self.nodes)
            if missing:
                raise Agg02Error("AGG02_EVIDENCE_PARENT_MISSING")
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            if node_id in visiting:
                raise Agg02Error("AGG02_EVIDENCE_CYCLE")
            visiting.add(node_id)
            for parent in self.nodes[node_id].parent_ids:
                visit(parent)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in self.nodes:
            visit(node_id)

    def ancestors(self, node_id: str) -> tuple[str, ...]:
        if node_id not in self.nodes:
            raise Agg02Error("AGG02_EVIDENCE_NODE_UNKNOWN")
        result: set[str] = set()

        def collect(current: str) -> None:
            for parent in self.nodes[current].parent_ids:
                if parent not in result:
                    result.add(parent)
                    collect(parent)

        collect(node_id)
        return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class UniverseCandidate:
    market_id: str
    expected_useful_episodes: int
    source_cost_units: int
    exit_liquidity_units: int
    trusted: bool


def schedule_market_universe(
    candidates: Iterable[UniverseCandidate], *, max_source_cost_units: int
) -> tuple[str, ...]:
    remaining = max_source_cost_units
    ranked: list[tuple[Fraction, UniverseCandidate]] = []
    for item in candidates:
        if (
            not item.trusted
            or item.source_cost_units <= 0
            or item.exit_liquidity_units <= 0
        ):
            continue
        ranked.append(
            (Fraction(item.expected_useful_episodes, item.source_cost_units), item)
        )
    selected: list[str] = []
    for _score, item in sorted(
        ranked, key=lambda pair: (-pair[0], pair[1].market_id)
    ):
        if item.source_cost_units <= remaining:
            selected.append(item.market_id)
            remaining -= item.source_cost_units
    return tuple(selected)
