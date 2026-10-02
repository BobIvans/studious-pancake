"""Deterministic offline demonstration; all market data is synthetic.

Run: python -m scripts.shadow_market_graph_demo
No network, signer, subscriptions or execution capability is constructed.
"""

from __future__ import annotations

from dataclasses import asdict
import json

from solders.pubkey import Pubkey

from src.config.chain_registry import ChainRegistry
from src.market.observations import (
    MarketObservationV2,
    ObservationGeneration,
    SourceCursor,
)
from src.market.source_catalog import load_market_source_catalog
from src.strategy.arbitrage_graph import (
    CircularGraphCandidateDetector,
    CircularGraphPolicy,
    VenueIdentity,
)
from src.strategy.market_graph_ingest import (
    ShadowMarketBinding,
    ShadowMarketGraphIngest,
)


def main() -> None:
    catalog = load_market_source_catalog()
    now = 1000.0
    assets = tuple(str(Pubkey.from_bytes(bytes([i]) * 32)) for i in (1, 2, 3))
    program = str(Pubkey.from_bytes(bytes([20]) * 32))
    generation = ObservationGeneration(
        genesis_hash=ChainRegistry.load_default().canonical_genesis_hashes[
            "mainnet-beta"
        ],
        provider_generation="synthetic-offline.v1",
    )
    bindings = tuple(
        ShadowMarketBinding(
            f"fixture-{i}",
            source,
            "recorded-fixture-feed",
            VenueIdentity(program, str(Pubkey.from_bytes(bytes([10 + i]) * 32))),
            (assets[i], assets[(i + 1) % 3]),
            "synthetic-fixture.v1",
        )
        for i, source in enumerate(("raydium", "orca", "meteora-dlmm"))
    )
    ingest = ShadowMarketGraphIngest(catalog, bindings)
    for i, binding in enumerate(bindings):
        observation = MarketObservationV2(
            provider=binding.source_id,
            source="synthetic-offline-fixture",
            input_mint=assets[i],
            output_mint=assets[(i + 1) % 3],
            input_amount=10 + i,
            expected_output=30,
            guaranteed_output=11 + i if i < 2 else 15,
            slot=100,
            observed_at=now - 1,
            expires_at=now + 1,
            confidence="recorded",
            generation=generation,
            cursor=SourceCursor(binding.cursor_source, binding.binding_id, 0, 100),
            request_fingerprint=f"fixture-request-{i}",
            response_hash=f"fixture-response-{i}",
        )
        ingest.ingest(binding.binding_id, observation)
    ingest.mark_backfill_complete("recorded-fixture-feed")
    snapshot = ingest.publish(now=now)
    detection = CircularGraphCandidateDetector(
        CircularGraphPolicy(assets[0], 10, 10)
    ).detect(snapshot.graph, now=now)
    print(
        json.dumps(
            {
                "schema_version": "shadow.market-graph-demo.v1",
                "mode": "synthetic-offline-shadow-only",
                "coverage": asdict(snapshot.coverage),
                "nodes": [asdict(node) for node in snapshot.graph.nodes],
                "edges": [
                    {
                        "identity": edge.identity,
                        "venue": asdict(edge.venue),
                        "observation": asdict(edge.observation),
                    }
                    for edge in snapshot.graph.edges
                ],
                "traces": [asdict(trace) for trace in snapshot.traces],
                "candidates": [
                    {
                        "identity": route.identity,
                        "amounts_base_units": route.amounts_base_units,
                        "gross_profit_base_units_before_costs": route.gross_profit_base_units,
                        "ordered_edge_identities": [
                            edge.identity for edge in route.edges
                        ],
                    }
                    for route in detection.candidates
                ],
                "stop_reason": detection.stop_reason,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
