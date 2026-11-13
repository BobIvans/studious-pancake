"""Bounded dynamic-universe relation discovery.

Tightening invariants (Stream H):
- Synthetic A/HUB/B relations are emitted only when both real legs and the hub
  resolve to identity-verified assets with current evidence refs (never by
  symbol/name similarity).
- Structural parity requires a proven common economic underlying AND distinct
  proven representations; native/wrapped/bridged/issuer/yield-bearing/RWA stay
  distinct and unknown representations never produce parity (unknown is not a
  proof).
- Cross-chain edges are research/rebalance-only signals and never execution
  candidates.
- Flash-capital edges join only after explicit lender qualification flags.
- Market-derived relations always carry the venue/pool correlation group and
  underlying liquidity resource identities, so shared-pool results can never be
  counted as independent liquidity.
- Relations are research signals: they never alter execution_class,
  evidence_state, heat or any promotion boundary.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations

from src.assets.resolution.evidence import Evidence, digest
from src.assets.resolution.resolver import AssetIdentity, ResolutionState
from src.discovery.dynamic_universe.universe import MarketIdentity
from src.economics.flash_capital_graph.graph import FlashCapitalEdge

REPRESENTATION_KINDS = frozenset(
    ("native", "wrapped", "bridged", "issuer", "yield_bearing", "rwa")
)
ANCHOR_KINDS = frozenset(("LST", "NAV", "USD", "WRAPPER", "ORACLE", "PARITY"))
SYNTHETIC_LEGS_VERIFIED = "SYNTHETIC_LEGS_VERIFIED"
REPRESENTATION_DISTINCT = "REPRESENTATION_DISTINCT"
CROSS_CHAIN_RESEARCH_ONLY = "CROSS_CHAIN_RESEARCH_ONLY"
LENDER_QUALIFIED = "LENDER_QUALIFIED"
ANCHOR_UNDERLYING_PROVEN = "ANCHOR_UNDERLYING_PROVEN"


@dataclass(frozen=True)
class StructuralAnchor:
    asset_id: str
    kind: str
    underlying: str
    evidence: Evidence
    conversion_cost_known: bool
    # Proven common underlying via identity/evidence flags, never a name match.
    underlying_proven: bool = False

    def __post_init__(self) -> None:
        if self.kind not in ANCHOR_KINDS:
            raise ValueError("unknown structural anchor kind")
        if not self.underlying or self.underlying != self.underlying.strip():
            raise ValueError("structural anchor underlying required")
        if type(self.underlying_proven) is not bool:
            raise ValueError("underlying provenance must be an explicit flag")


@dataclass(frozen=True)
class ResearchRelation:
    kind: str
    asset_ids: tuple[str, ...]
    market_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    correlation_groups: tuple[str, ...]
    liquidity_resources: tuple[str, ...]
    atomicity_class: str = "RESEARCH_ONLY"
    representation_kinds: tuple[str, ...] = ()
    provenance_flags: tuple[str, ...] = ()

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
    # Identity proof gate: only resolver-verified assets with current evidence
    # participate in relations; candidates, ambiguous or unverified identities
    # are excluded (unknown is never treated as verified).
    by_identity = {
        (a.chain, a.canonical_identifier): a
        for a in assets
        if a.resolver_generation == generation
        and a.verification_state == ResolutionState.IDENTIFIER_VERIFIED
        and a.evidence_refs
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
        flags: tuple[str, ...] = (),
        representations: tuple[str, ...] = (),
    ) -> bool:
        nonlocal work, truncated
        if work >= max_work or len(result) >= max_relations:
            truncated = True
            return False
        if any(asset_id not in by_id for asset_id in asset_ids):
            raise ValueError("relation references an unverified asset identity")
        groups = tuple(sorted({m.correlation_group for m in ms}))
        resources = tuple(sorted({r for m in ms for r in m.underlying_resources}))
        # Aggregator/venue overlap provenance: market-derived relations must
        # carry their correlation group and underlying venue/pool identity so
        # shared-pool results are never counted as independent liquidity.
        if ms and (not groups or not resources):
            raise ValueError("market relations require liquidity provenance")
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
            groups,
            resources,
            atomicity,
            tuple(sorted(set(representations))),
            tuple(sorted(set(flags))),
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
            # The hub itself must be an identity-verified asset; a hub that
            # only appears inside market pairs is not a proven leg.
            if hub in hubs and by_identity.get((m.chain, hub)) is not None:
                hub_markets[(m.chain, hub)].append(m)
    for pair, venues in sorted(pairs.items()):
        limited = venues[:max_neighbors]
        truncated |= len(venues) > max_neighbors
        for left, right in combinations(limited, 2):
            # Shared liquidity or a shared correlation group does not become an
            # independent confirmation.
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
            # Both real legs must be identity-verified assets; aggregator
            # aliases (same correlation group) or shared pools are not
            # independent legs for a synthetic path.
            if (
                left_id == right_id
                or left.correlation_group == right.correlation_group
                or set(left.underlying_resources) & set(right.underlying_resources)
            ):
                continue
            ids = tuple(
                by_identity[(chain, ident)].asset_id
                for ident in (left_id, hub, right_id)
            )
            if not emit(
                "SYNTHETIC_CROSS",
                ids,
                (left, right),
                flags=(SYNTHETIC_LEGS_VERIFIED,),
            ):
                break
            for direct in pairs.get(
                (chain, min(left_id, right_id), max(left_id, right_id)), ()
            )[:max_neighbors]:
                shared = set(left.underlying_resources) | set(
                    right.underlying_resources
                )
                if set(direct.underlying_resources) & shared or any(
                    direct.correlation_group == leg.correlation_group
                    for leg in (left, right)
                ):
                    continue
                if not emit(
                    "DIRECT_SYNTHETIC_RESIDUAL",
                    ids,
                    (direct, left, right),
                    flags=(SYNTHETIC_LEGS_VERIFIED,),
                ):
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
            or not anchor.underlying_proven
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
                flags=(ANCHOR_UNDERLYING_PROVEN,),
            ):
                break
    underlyings: dict[str, list[AssetIdentity]] = defaultdict(list)
    for a in sorted(by_id.values(), key=lambda a: a.asset_id):
        if a.economic_underlying != "unknown":
            underlyings[a.economic_underlying].append(a)
    for equivalent in underlyings.values():
        truncated |= len(equivalent) > max_neighbors
        for a, b in combinations(equivalent[:max_neighbors], 2):
            # Parity needs a proven common underlying AND distinct proven
            # representations; unknown representations and same-kind/same-
            # program aliases are refused (unknown is not a proof, aliases are
            # not parity).
            if a.representation_kind not in REPRESENTATION_KINDS or (
                b.representation_kind not in REPRESENTATION_KINDS
            ):
                continue
            if (
                a.chain == b.chain
                and a.representation_kind == b.representation_kind
                and a.program_or_package == b.program_or_package
            ):
                continue
            cross_chain = a.chain != b.chain
            kind = "CROSS_CHAIN_BASIS" if cross_chain else "STRUCTURAL_PARITY"
            flags: tuple[str, ...] = (REPRESENTATION_DISTINCT,)
            if cross_chain:
                flags = flags + (CROSS_CHAIN_RESEARCH_ONLY,)
            if not emit(
                kind,
                (a.asset_id, b.asset_id),
                (),
                atomicity="SIGNAL_REBALANCE_ONLY",
                flags=flags,
                representations=(a.representation_kind, b.representation_kind),
            ):
                break
    for edge in sorted(capital_edges, key=lambda e: e.identity):
        # Lender qualification flags: qualified provider (enforced by the
        # FlashCapitalEdge owner), verified asset identity, current observed
        # capacity and positive live capacity are all required before a
        # capital edge joins the relation set.
        if (
            edge.asset_id not in by_id
            or edge.atomicity_class != "LOCAL_ATOMIC_CANDIDATE"
            or not edge.evidence_refs
            or not edge.evidence.fresh(now=now, max_age=30, generation=generation)
            or edge.max_amount_live <= 0
        ):
            continue
        if not emit(
            "FLASH_CAPITAL",
            (edge.asset_id,),
            (),
            edge.evidence_refs,
            "LOCAL_ATOMIC_CANDIDATE",
            flags=(LENDER_QUALIFIED,),
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


def edge_cycle_proof(edge, receipt, *, boundary, now: float):
    """Per-edge state/quote-proof flags for bounded-cycle research routes.

    Returns (search_edge, exclusion_reason). An edge without a current exact
    RPC_EXACT receipt, complete QPR boundary replay, positive guaranteed output
    and 5-second freshness is excluded (typed reason), never projected.
    """
    from src.strategy.multihop_solver import SearchEdge

    quote = edge.observation
    try:
        payload = boundary.store.replay(receipt.durable_ref)["payload"]
    except (OSError, ValueError, KeyError):
        return None, "receipt_unreplayable"
    if (
        payload["stage"] != "RPC_EXACT"
        or payload["generation"] != boundary.generation
        or payload["reasons"]
        or payload["observation_id"] != quote.observation_id
        or receipt.observation_id != quote.observation_id
    ):
        return None, "edge_state_not_exact_verified"
    if (
        quote.observed_at > now
        or not quote.is_fresh(now=now, max_age_seconds=5)
        or quote.guaranteed_output <= 0
        or quote.input_amount <= 0
    ):
        return None, "edge_quote_not_current"
    return (
        SearchEdge(
            edge.identity,
            quote.input_mint,
            quote.output_mint,
            digest(asdict(edge.venue)),
            quote.guaranteed_output,
            quote.input_amount,
            quote.generation.identity,
        ),
        None,
    )


def shortlist_verified_cycles(
    graph,
    boundary,
    receipts,
    *,
    start_asset: str,
    now: float,
    max_expansions: int = 4096,
    max_routes: int = 128,
    exclusions: list[tuple[str, str]] | None = None,
):
    """Reuse the 3..5-hop multihop owner for topology research only.

    Amount-specific rate projections shortlist; they do not establish coupled
    exact economics or extend CircularShadowRoute's 3/4-hop paper contract.
    Edges lacking per-edge state/quote-proof flags are excluded with typed
    reasons; unproven edges never enter the bounded-cycle projection.
    """
    from src.strategy.arbitrage_graph import UniversalArbitrageGraph
    from src.strategy.multihop_solver import search_bounded_cycles

    if (
        not isinstance(graph, UniversalArbitrageGraph)
        or not graph.batch.admissible
        or not boundary.readiness()
    ):
        raise ValueError("QPR and complete canonical graph required")
    by_observation = {r.observation_id: r for r in receipts}
    projected = []
    for edge in graph.edges:
        receipt = by_observation.get(edge.observation.observation_id)
        if receipt is None:
            if exclusions is not None:
                exclusions.append((edge.identity, "missing_exact_edge_receipt"))
            continue
        search_edge, reason = edge_cycle_proof(
            edge, receipt, boundary=boundary, now=now
        )
        if search_edge is None:
            if exclusions is not None:
                exclusions.append((edge.identity, reason))
            continue
        projected.append(search_edge)
    return search_bounded_cycles(
        projected,
        start_asset=start_asset,
        min_hops=3,
        max_hops=5,
        max_expansions=max_expansions,
        max_routes=max_routes,
    )
