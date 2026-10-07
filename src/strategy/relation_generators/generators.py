from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations

from src.assets.resolution.evidence import Evidence, digest
from src.assets.resolution.resolver import AssetIdentity
from src.discovery.dynamic_universe.universe import MarketIdentity
from src.economics.flash_capital_graph.graph import FlashCapitalEdge


@dataclass(frozen=True)
class StructuralAnchor:
    asset_id: str
    kind: str
    underlying: str
    evidence: Evidence
    conversion_cost_known: bool


@dataclass(frozen=True)
class ResearchRelation:
    kind: str
    asset_ids: tuple[str, ...]
    market_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    correlation_groups: tuple[str, ...]
    liquidity_resources: tuple[str, ...]
    atomicity_class: str = "RESEARCH_ONLY"

    @property
    def identity(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class RelationBatch:
    relations: tuple[ResearchRelation, ...]
    examined: int
    truncated: bool


def generate(
    assets: tuple[AssetIdentity, ...],
    markets: tuple[MarketIdentity, ...],
    anchors: tuple[StructuralAnchor, ...],
    *,
    hubs: frozenset[str],
    now: float,
    generation: str,
    max_relations: int = 512,
    max_work: int = 4096,
    max_neighbors: int = 16,
    capital_edges: tuple[FlashCapitalEdge, ...] = (),
) -> RelationBatch:
    if (
        any(
            type(n) is not int or not 1 <= n <= 65536
            for n in (max_relations, max_work, max_neighbors)
        )
        or len(assets) > 8192
        or len(markets) > 4096
        or len(anchors) > 8192
        or len(capital_edges) > 4096
    ):
        raise ValueError("bounded generator inputs required")
    by_identity = {
        (a.chain, a.canonical_identifier): a
        for a in assets
        if a.resolver_generation == generation
    }
    by_id = {a.asset_id: a for a in by_identity.values()}
    active = tuple(
        sorted(
            {
                m.identity: m
                for m in markets
                if m.evidence is not None
                and m.evidence.fresh(now=now, max_age=300, generation=generation)
            }.values(),
            key=lambda m: m.identity,
        )
    )
    result: dict[str, ResearchRelation] = {}
    work = 0
    truncated = False

    def emit(
        kind: str,
        asset_ids: tuple[str, ...],
        ms: tuple[MarketIdentity, ...],
        refs: tuple[str, ...] = (),
        atomicity: str = "RESEARCH_ONLY",
    ) -> bool:
        nonlocal work, truncated
        if work >= max_work or len(result) >= max_relations:
            truncated = True
            return False
        work += 1
        relation = ResearchRelation(
            kind,
            asset_ids,
            tuple(m.identity for m in ms),
            tuple(
                sorted(
                    set(refs)
                    | {digest(asdict(m.evidence)) for m in ms if m.evidence is not None}
                    | {
                        ref
                        for asset_id in asset_ids
                        for ref in by_id[asset_id].evidence_refs
                    }
                )
            ),
            tuple(sorted({m.correlation_group for m in ms})),
            tuple(sorted({r for m in ms for r in m.underlying_resources})),
            atomicity,
        )
        result[relation.identity] = relation
        return True

    pairs: dict[tuple[str, str, str], list[MarketIdentity]] = defaultdict(list)
    hub_markets: dict[tuple[str, str], list[MarketIdentity]] = defaultdict(list)
    for m in active:
        left_asset, right_asset = by_identity.get((m.chain, m.base)), by_identity.get(
            (m.chain, m.quote)
        )
        if left_asset is None or right_asset is None:
            continue
        if not emit("DIRECT_MARKET", (left_asset.asset_id, right_asset.asset_id), (m,)):
            break
        pairs[(m.chain, min(m.base, m.quote), max(m.base, m.quote))].append(m)
        for hub in (m.base, m.quote):
            if hub in hubs:
                hub_markets[(m.chain, hub)].append(m)
    for pair, venues in sorted(pairs.items()):
        limited = venues[:max_neighbors]
        truncated |= len(venues) > max_neighbors
        for left, right in combinations(limited, 2):
            # Shared liquidity does not become an independent confirmation.
            if left.correlation_group == right.correlation_group or set(
                left.underlying_resources
            ) & set(right.underlying_resources):
                continue
            ids = tuple(
                by_identity[(pair[0], identifier)].asset_id for identifier in pair[1:]
            )
            if not emit("VENUE_FRAGMENTATION", ids, (left, right)):
                break
        if truncated and (work >= max_work or len(result) >= max_relations):
            break
    for (chain, hub), venues in sorted(hub_markets.items()):
        limited = venues[:max_neighbors]
        truncated |= len(venues) > max_neighbors
        for left, right in combinations(limited, 2):
            left_id = left.quote if left.base == hub else left.base
            right_id = right.quote if right.base == hub else right.base
            if left_id == right_id or set(left.underlying_resources) & set(
                right.underlying_resources
            ):
                continue
            ids = tuple(
                by_identity[(chain, ident)].asset_id
                for ident in (left_id, hub, right_id)
            )
            if not emit("SYNTHETIC_CROSS", ids, (left, right)):
                break
            for direct in pairs.get(
                (chain, min(left_id, right_id), max(left_id, right_id)), ()
            )[:max_neighbors]:
                if set(direct.underlying_resources) & (
                    set(left.underlying_resources) | set(right.underlying_resources)
                ):
                    continue
                if not emit("DIRECT_SYNTHETIC_RESIDUAL", ids, (direct, left, right)):
                    break
        if work >= max_work or len(result) >= max_relations:
            break
    kinds = {
        "LST": "LST_FAIR_VALUE",
        "NAV": "NAV_BASIS",
        "USD": "STABLE_RESIDUAL",
        "WRAPPER": "WRAPPER_BASIS",
        "ORACLE": "ORACLE_MARKET",
        "PARITY": "STRUCTURAL_PARITY",
    }
    for anchor in sorted(anchors, key=lambda a: (a.asset_id, a.kind)):
        asset = by_id.get(anchor.asset_id)
        if (
            asset is None
            or anchor.kind not in kinds
            or not anchor.evidence.fresh(now=now, max_age=300, generation=generation)
        ):
            continue
        matches = tuple(
            m
            for m in active
            if m.chain == asset.chain
            and asset.canonical_identifier in (m.base, m.quote)
        )[:max_neighbors]
        for m in matches:
            if not emit(
                kinds[anchor.kind],
                (asset.asset_id,),
                (m,),
                (digest(asdict(anchor.evidence)),),
            ):
                break
    underlyings: dict[str, list[AssetIdentity]] = defaultdict(list)
    for a in sorted(by_id.values(), key=lambda a: a.asset_id):
        if a.economic_underlying != "unknown":
            underlyings[a.economic_underlying].append(a)
    for equivalent in underlyings.values():
        truncated |= len(equivalent) > max_neighbors
        for a, b in combinations(equivalent[:max_neighbors], 2):
            kind = "CROSS_CHAIN_BASIS" if a.chain != b.chain else "STRUCTURAL_PARITY"
            if not emit(
                kind, (a.asset_id, b.asset_id), (), atomicity="SIGNAL_REBALANCE_ONLY"
            ):
                break
    for edge in sorted(capital_edges, key=lambda e: e.identity):
        if (
            edge.asset_id not in by_id
            or not edge.evidence.fresh(now=now, max_age=30, generation=generation)
            or edge.max_amount_live == 0
        ):
            continue
        if not emit(
            "FLASH_CAPITAL",
            (edge.asset_id,),
            (),
            edge.evidence_refs,
            "LOCAL_ATOMIC_CANDIDATE",
        ):
            break
    return RelationBatch(tuple(result[key] for key in sorted(result)), work, truncated)


def bounded_exact_cycles(*, graph, policy, now: float):
    """Delegate exact 3/4-hop shadow cycles to the existing owner.

    The existing owner does not support five-hop canonical shadow cycles; this
    wave does not invent a second solver or relax its limits.
    """
    from src.strategy.arbitrage_graph import (
        CircularGraphCandidateDetector,
        UniversalArbitrageGraph,
    )

    if not isinstance(graph, UniversalArbitrageGraph):
        raise ValueError("research relations cannot enter the exact cycle solver")
    return CircularGraphCandidateDetector(policy).detect(graph, now=now)


def shortlist_verified_cycles(
    graph,
    boundary,
    receipts,
    *,
    start_asset: str,
    now: float,
    max_expansions: int = 4096,
    max_routes: int = 128,
):
    """Reuse the 3..5-hop multihop owner for topology research only.

    Amount-specific rate projections shortlist; they do not establish coupled
    exact economics or extend CircularShadowRoute's 3/4-hop paper contract.
    """
    from src.strategy.arbitrage_graph import UniversalArbitrageGraph
    from src.strategy.multihop_solver import SearchEdge, search_bounded_cycles

    if (
        not isinstance(graph, UniversalArbitrageGraph)
        or not graph.batch.admissible
        or not boundary.readiness()
    ):
        raise ValueError("QPR and complete canonical graph required")
    by_observation = {r.observation_id: r for r in receipts}
    projected = []
    for edge in graph.edges:
        quote = edge.observation
        receipt = by_observation.get(quote.observation_id)
        if receipt is None:
            raise ValueError("missing exact edge receipt")
        payload = boundary.store.replay(receipt.durable_ref)["payload"]
        if (
            payload["stage"] != "RPC_EXACT"
            or payload["generation"] != boundary.generation
            or payload["reasons"]
            or payload["observation_id"] != quote.observation_id
            or quote.observed_at > now
            or not quote.is_fresh(now=now, max_age_seconds=5)
            or quote.guaranteed_output <= 0
        ):
            raise ValueError("edge is not currently exact verified")
        projected.append(
            SearchEdge(
                edge.identity,
                quote.input_mint,
                quote.output_mint,
                digest(asdict(edge.venue)),
                quote.guaranteed_output,
                quote.input_amount,
                quote.generation.identity,
            )
        )
    return search_bounded_cycles(
        projected,
        start_asset=start_asset,
        min_hops=3,
        max_hops=5,
        max_expansions=max_expansions,
        max_routes=max_routes,
    )
