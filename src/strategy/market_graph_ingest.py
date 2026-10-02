"""Shadow-only bridge from bound canonical observations into the PR559 graph.

Reuses the MPR042 stream/completeness authority. Discovery never auto-binds a
venue, prices never become quotes, and fixture-only orderbooks remain blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType

from src.config.chain_registry import ChainRegistry, validate_pubkey
from src.market.discovery import DiscoveryBatch
from src.market.observations import (
    CompletenessState,
    MarketObservationV2,
    ObservationBatch,
    ObservationWatermark,
)
from src.market.source_catalog import MarketSourceCatalog, SourceFamily
from src.market.streams import (
    DurableCursorStore,
    FanoutMatrix,
    WatermarkedObservationBuffer,
)

from .arbitrage_graph import DirectedQuoteEdge, UniversalArbitrageGraph, VenueIdentity


@dataclass(frozen=True, slots=True)
class ShadowMarketBinding:
    binding_id: str
    source_id: str
    cursor_source: str
    venue: VenueIdentity
    mints: tuple[str, str]
    decoder_revision: str
    domain: str = "solana-mainnet"

    def __post_init__(self) -> None:
        for text in (
            self.binding_id,
            self.source_id,
            self.cursor_source,
            self.decoder_revision,
        ):
            if not isinstance(text, str) or not text or text != text.strip():
                raise ValueError("binding identity and decoder provenance are required")
        if self.domain != "solana-mainnet":
            raise ValueError("cross-domain bindings are not Solana-atomic")
        validate_pubkey(self.venue.program_id)
        validate_pubkey(self.venue.market_id)
        if len(self.mints) != 2 or self.mints[0] == self.mints[1]:
            raise ValueError("binding needs two distinct mint addresses")
        for mint in self.mints:
            validate_pubkey(mint)
        object.__setattr__(self, "mints", tuple(sorted(self.mints)))


@dataclass(frozen=True, slots=True)
class GraphSourceTrace:
    edge_identity: str
    observation_id: str
    binding_id: str
    catalog_source_id: str
    decoder_revision: str
    cursor_key: str
    cursor_offset: int
    response_hash: str
    request_fingerprint: str


@dataclass(frozen=True, slots=True)
class MarketGraphCoverage:
    catalog_sources: int
    discovered_markets: int
    bound_markets: int
    exact_quoted_markets: int
    fresh_quoted_markets: int
    missing_bindings: tuple[str, ...]
    batch_complete: bool
    discovery_truncated: bool
    discovery_errors: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ShadowMarketGraphSnapshot:
    graph: UniversalArbitrageGraph
    traces: tuple[GraphSourceTrace, ...]
    coverage: MarketGraphCoverage


class ShadowMarketGraphIngest:
    """Explicit closed set of AMM bindings, maximum 512 events per epoch.

    The binding's decoder revision is caller-supplied provenance, not a decoder
    certification or live authorization. Only existing verified normalizers or
    labelled offline fixtures may produce the canonical observations. All
    output remains shadow evidence, including gross-profit candidates.
    """

    _CONSUMER = "universal_graph_shadow"

    def __init__(
        self,
        catalog: MarketSourceCatalog,
        bindings: tuple[ShadowMarketBinding, ...],
        *,
        cursor_store: DurableCursorStore | None = None,
        max_events: int = 512,
    ) -> None:
        if not 1 <= len(bindings) <= 512 or len(
            {b.binding_id for b in bindings}
        ) != len(bindings):
            raise ValueError("require 1..512 unique explicit bindings")
        if type(max_events) is not int or not 1 <= max_events <= 512:
            raise ValueError("event cap outside 1..512")
        for binding in bindings:
            source = catalog.require(binding.source_id)
            if (
                source.family is not SourceFamily.AMM
                or "solana-mainnet" not in source.domains
            ):
                raise ValueError(
                    "source is not an admitted Solana AMM; orderbook subscriptions/decoders remain unverified"
                )
        self.catalog = catalog
        self.bindings = MappingProxyType(
            {binding.binding_id: binding for binding in bindings}
        )
        self.genesis_hash = ChainRegistry.load_default().canonical_genesis_hashes[
            "mainnet-beta"
        ]
        self.max_events = max_events
        self._event_count = 0
        required = tuple(sorted({binding.cursor_source for binding in bindings}))
        self._buffer = WatermarkedObservationBuffer(
            fanout=FanoutMatrix({self._CONSUMER: required}),
            cursor_store=cursor_store,
        )
        self._edges: dict[str, DirectedQuoteEdge] = {}
        self._traces: dict[str, GraphSourceTrace] = {}

    @property
    def reconnect_epoch(self) -> int:
        return self._buffer.reconnect_epoch

    def begin_reconnect(self) -> int:
        epoch = self._buffer.begin_reconnect()
        self._edges.clear()
        self._traces.clear()
        self._event_count = 0
        return epoch

    def ingest(self, binding_id: str, observation: MarketObservationV2) -> bool:
        if not isinstance(observation, MarketObservationV2):
            raise ValueError("discovery/reference records cannot become graph quotes")
        try:
            binding = self.bindings[binding_id]
        except KeyError as exc:
            raise ValueError("unregistered market binding") from exc
        cursor = observation.cursor
        if (
            observation.provider != binding.source_id
            or cursor is None
            or cursor.source != binding.cursor_source
            or cursor.partition != binding_id
        ):
            raise ValueError(
                "quote provider/cursor does not match the explicit binding"
            )
        if (
            tuple(sorted((observation.input_mint, observation.output_mint)))
            != binding.mints
        ):
            raise ValueError("quote mints do not match bound market")
        if observation.generation.genesis_hash != self.genesis_hash:
            raise ValueError("quote belongs to a foreign or unknown settlement domain")
        if not observation.response_hash or not observation.request_fingerprint:
            raise ValueError("canonical quote requires request/response provenance")
        edge = DirectedQuoteEdge(binding.venue, observation)
        previous_edge = self._edges.get(observation.observation_id)
        if previous_edge is not None and previous_edge != edge:
            raise ValueError("observation identity reused for different edge evidence")
        if previous_edge is not None:
            return self._buffer.ingest(observation)
        if observation.supersedes_id is not None:
            previous_trace = self._traces.get(observation.supersedes_id)
            if previous_trace is None or previous_trace.binding_id != binding_id:
                raise ValueError(
                    "correction must supersede evidence in the same binding"
                )
        # Validate/serialize full edge evidence before canonical state mutates.
        trace = GraphSourceTrace(
            edge.identity,
            observation.observation_id,
            binding_id,
            binding.source_id,
            binding.decoder_revision,
            cursor.key,
            cursor.offset,
            observation.response_hash,
            observation.request_fingerprint,
        )
        # Do not mutate canonical state after reaching the bounded window.
        if self._event_count == self.max_events:
            raise ValueError(
                "shadow event window full; publish/checkpoint then reconnect/backfill"
            )
        if not self._buffer.ingest(observation):
            return False
        self._event_count += 1
        if observation.supersedes_id is not None:
            self._edges.pop(observation.supersedes_id, None)
            self._traces.pop(observation.supersedes_id, None)
        self._traces[observation.observation_id] = trace
        # Retraction evidence stays bounded/internal for idempotent replay;
        # canonical active_observations excludes it from graph publication.
        self._edges[observation.observation_id] = edge
        return True

    def mark_backfill_complete(self, source: str) -> None:
        if source not in {binding.cursor_source for binding in self.bindings.values()}:
            raise ValueError("source is outside the graph fanout contract")
        self._buffer.mark_backfill_complete(source)

    def invalidate_generation(self, generation_identity: str) -> tuple[str, ...]:
        invalidated = self._buffer.invalidate_generation(generation_identity)
        for observation_id in invalidated:
            self._edges.pop(observation_id, None)
            self._traces.pop(observation_id, None)
        return invalidated

    def publish(
        self,
        *,
        now: float,
        max_age_seconds: float = 5.0,
        max_slot_skew: int = 0,
        discovery: DiscoveryBatch | None = None,
    ) -> ShadowMarketGraphSnapshot:
        if (
            not math.isfinite(now)
            or now <= 0
            or not math.isfinite(max_age_seconds)
            or max_age_seconds <= 0
        ):
            raise ValueError("coverage timestamps/age must be finite and positive")
        if type(max_slot_skew) is not int or max_slot_skew < 0:
            raise ValueError("slot skew must be a non-negative integer")
        batch = self._buffer.publish(self._CONSUMER, max_slot_skew=max_slot_skew)
        edges = tuple(
            self._edges[item.observation_id] for item in batch.active_observations()
        )
        traces = tuple(
            sorted(
                (self._traces[edge.observation.observation_id] for edge in edges),
                key=lambda trace: trace.edge_identity,
            )
        )
        quoted = {trace.binding_id for trace in traces}
        missing = tuple(sorted(set(self.bindings) - quoted))
        batch = ObservationBatch(
            tuple(sorted(batch.observations, key=lambda item: item.observation_id)),
            watermark=ObservationWatermark(
                tuple(sorted(batch.watermark.cursors, key=lambda cursor: cursor.key)),
                batch.watermark.minimum_slot,
                batch.watermark.maximum_slot,
                batch.watermark.reconnect_epoch,
            ),
            policy=batch.policy,
            completeness=CompletenessState.BLOCKED if missing else batch.completeness,
            degraded_reasons=batch.degraded_reasons
            + tuple(f"missing_binding:{name}" for name in missing),
            published_at=now,
        )
        fresh = {
            edge.venue
            for edge in edges
            if edge.observation.observed_at <= now
            and edge.observation.is_fresh(now=now, max_age_seconds=max_age_seconds)
        }
        coverage = MarketGraphCoverage(
            len(self.catalog.sources),
            0 if discovery is None else discovery.market_count,
            len({binding.venue for binding in self.bindings.values()}),
            len({edge.venue for edge in edges}),
            len(fresh),
            missing,
            batch.completeness is CompletenessState.COMPLETE,
            False if discovery is None else discovery.truncated,
            () if discovery is None else discovery.rejections,
        )
        return ShadowMarketGraphSnapshot(
            UniversalArbitrageGraph(batch, edges), traces, coverage
        )
