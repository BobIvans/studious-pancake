"""R10-1 deterministic pre-API market -> route -> paper qualification replay.

Runs the offline end-to-end binding replay over a fixed fixture set (two-leg,
3-pool triangle, 4-pool cycle, alias, unknown lineage, blocked venue families)
and writes the combined report JSON with its deterministic digest.  All inputs
and outputs are fixture/replay evidence; no live API call, signing, sending or
borrowing occurs.  Run with the repository interpreter:

    .venv/Scripts/python.exe scripts/r10_1_pre_api_route_replay.py \
        --output docs/roadmap/pre-api-market-route-qualification-2026-11-15/replay_report_2026-11-15.json
"""

from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
import tempfile
import time
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solders.pubkey import Pubkey

from src.economics.capital import CapitalPolicy, NativeCostBreakdown
from src.durability import DurableLifecycleStore
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)
from src.economics.non_monotonic_sizing import (
    PR118AssetAmount,
    PR118CostComponentKind,
    PR118CostLedgerEntry,
    PR118FlashRepaymentTerms,
    PR118TypedCostLedger,
)
from src.execution.quote_build_kernel import PoolIdentity, PoolIdentityKind
from src.market.observations import ObservationGeneration
from src.strategy.arbitrage_graph import VenueIdentity
from src.strategy.cpmm_cycle_binding import (
    BlockedVenueCandidate,
    CpmmBindingError,
    CpmmBindingRejection,
    PoolLineage,
    VenueKind,
    conservative_net_for_ledger,
    run_pre_api_route_qualification_replay,
)
from src.strategy.exact_cpmm_capacity import (
    CapacityEconomics,
    QualifiedCpmmState,
    RAYDIUM_CPMM_PROGRAM_ID,
    SolanaAssetIdentity,
)

NOW = 1_000.0
GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
GENERATION = ObservationGeneration(
    genesis_hash=GENESIS,
    provider_generation="fixture-provider-v1",
    asset_generation="fixture-assets-v1",
    policy_generation="shadow-only-v1",
    code_generation="r10-1-binding-v1",
)


def _asset(mint: str) -> SolanaAssetIdentity:
    return SolanaAssetIdentity(
        domain="solana-mainnet",
        genesis_hash=GENESIS,
        mint=mint,
        token_program=TOKEN_PROGRAM,
        token_revision="spl-token-v1",
        decimals=9,
    )


WSOL = _asset("So11111111111111111111111111111111111111112")
B, C, D = (_asset(str(Pubkey.from_bytes(bytes([i]) * 32))) for i in (2, 3, 4))


def _pool(
    market_id: str,
    asset_a: SolanaAssetIdentity,
    asset_b: SolanaAssetIdentity,
    reserves: tuple[int, int],
    **changes: object,
) -> QualifiedCpmmState:
    values: dict[str, object] = {
        "venue": VenueIdentity(RAYDIUM_CPMM_PROGRAM_ID, market_id),
        "asset_a": asset_a,
        "asset_b": asset_b,
        "reserve_a": reserves[0],
        "reserve_b": reserves[1],
        "fee_bps": 25,
        "slot": 100,
        "observed_at": NOW - 1,
        "expires_at": NOW + 1,
        "generation": GENERATION,
    }
    values.update(changes)
    return QualifiedCpmmState(**values)  # type: ignore[arg-type]


def _lineage(market_id: str, **changes: object) -> PoolLineage:
    values: dict[str, object] = {
        "correlation_group": f"raydium-cpmm:{market_id}",
        "aggregator_lineage": (),
        "pool_ids": (PoolIdentity(PoolIdentityKind.POOL_ADDRESS, market_id),),
    }
    values.update(changes)
    return PoolLineage(**values)  # type: ignore[arg-type]


def _policy() -> CapitalPolicy:
    return CapitalPolicy(
        protected_reserve_lamports=0,
        minimum_net_profit_lamports=1,
        maximum_priority_fee_lamports=10_000,
        maximum_jito_tip_lamports=10_000,
        maximum_peak_rent_lamports=10_000,
        contingency_lamports=0,
        maximum_flash_loan_lamports=1_000_000,
    )


def _economics(network_fee: int) -> CapacityEconomics:
    return CapacityEconomics(
        settlement_asset_id="WSOL",
        flash_fee_bps=0,
        protocol_rounding_atoms=0,
        native_costs=NativeCostBreakdown(base_network_fee_lamports=network_fee),
    )


def _run(
    pools: Sequence[QualifiedCpmmState],
    *,
    tmp: Path,
    name: str,
    stores: list[DurableLifecycleStore],
    **changes: object,
):
    lineage = {pool.venue: _lineage(pool.venue.market_id) for pool in pools}
    lineage.update(changes.pop("lineage_by_venue", {}))
    store = DurableLifecycleStore(tmp / f"capital-{name}.db")
    stores.append(store)
    return run_pre_api_route_qualification_replay(
        pools=pools,
        settlement_asset=WSOL,
        now=NOW,
        probe_amount=changes.pop("probe_amount", 100),
        economics=changes.pop("economics", _economics(0)),
        coordinator=DurableCapitalCoordinator(store=store, policy=_policy()),
        wallet_snapshot=WalletBalanceSnapshot(
            wallet_pubkey="wallet111111111111111111111111111111111111",
            native_lamports=10_000_000,
            context_slot=100,
            captured_at_ns=time.time_ns(),
            cluster_genesis=GENESIS,
        ),
        lineage_by_venue=lineage,
        **changes,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path of the combined fixture replay report JSON",
    )
    args = parser.parse_args()

    scenarios: list[tuple[str, object]] = []
    stores: list[DurableLifecycleStore] = []
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)

        two_leg = (
            _pool("pool-1", WSOL, B, (1_000, 2_000)),
            _pool("pool-2", B, WSOL, (1_000, 2_000)),
        )
        scenarios.append(
            ("two-leg-positive", _run(two_leg, tmp=tmp, stores=stores, name="two-leg"))
        )

        triangle = (
            _pool("pool-1", WSOL, B, (333, 9_170)),
            _pool("pool-2", B, C, (2_350, 6_118)),
            _pool("pool-3", C, WSOL, (8_573, 266)),
        )
        scenarios.append(
            (
                "three-pool-triangle-non-monotonic",
                _run(
                    triangle,
                    tmp=tmp,
                    stores=stores,
                    name="triangle",
                    amount_grid=(30, 10, 20),
                    economics=_economics(7),
                ),
            )
        )

        four_cycle = (
            _pool("pool-1", WSOL, B, (1_000, 2_000)),
            _pool("pool-2", B, C, (1_000, 2_000)),
            _pool("pool-3", C, D, (1_000, 2_000)),
            _pool("pool-4", D, WSOL, (1_000, 2_000)),
        )
        scenarios.append(
            (
                "four-pool-cycle",
                _run(
                    four_cycle, tmp=tmp, stores=stores, name="four", amount_grid=(10,)
                ),
            )
        )

        alias_pools = (
            _pool("agg-jupiter-view", WSOL, B, (1_000, 2_000)),
            _pool("agg-0x-view", WSOL, B, (1_000, 2_000)),
        )
        shared = PoolIdentity(PoolIdentityKind.POOL_ADDRESS, "shared-physical-pool")
        scenarios.append(
            (
                "pool-alias-across-aggregators",
                _run(
                    alias_pools,
                    tmp=tmp,
                    stores=stores,
                    name="alias",
                    lineage_by_venue={
                        alias_pools[0].venue: PoolLineage(
                            correlation_group="jupiter-aggregator",
                            pool_ids=(shared,),
                        ),
                        alias_pools[1].venue: PoolLineage(
                            correlation_group="zero-x-aggregator",
                            pool_ids=(shared,),
                        ),
                    },
                ),
            )
        )

        unknown_lineage_pools = (
            _pool("pool-1", WSOL, B, (1_000, 2_000)),
            _pool("pool-2", B, WSOL, (1_000, 2_000)),
        )
        scenarios.append(
            (
                "unknown-lineage",
                _run(
                    unknown_lineage_pools,
                    tmp=tmp,
                    stores=stores,
                    name="unknown-lineage",
                    lineage_by_venue={
                        unknown_lineage_pools[0].venue: _lineage("pool-1"),
                        unknown_lineage_pools[1].venue: PoolLineage(
                            correlation_group="raydium-cpmm:pool-2"
                        ),
                    },
                ),
            )
        )

        scenarios.append(
            (
                "blocked-venue-families",
                _run(
                    (_pool("pool-1", WSOL, B, (1_000, 2_000)),),
                    tmp=tmp,
                    stores=stores,
                    name="blocked",
                    blocked_candidates=(
                        BlockedVenueCandidate(
                            label="clmm-position",
                            venue_kind=VenueKind.RAYDIUM_CLMM,
                            missing_evidence="missing tick-array/bitmap state for exact math",
                        ),
                        BlockedVenueCandidate(
                            label="dlmm-position",
                            venue_kind=VenueKind.METEORA_DLMM,
                            missing_evidence="missing direction-specific bin arrays",
                        ),
                        BlockedVenueCandidate(
                            label="clob-market",
                            venue_kind=VenueKind.ORDERBOOK,
                            missing_evidence="no verified sequence/depth fill semantics",
                        ),
                    ),
                ),
            )
        )

        # Determinism proof: run the triangle twice, digests must match.
        first = _run(
            triangle,
            tmp=tmp,
            stores=stores,
            name="det-1",
            amount_grid=(30, 10, 20),
            economics=_economics(7),
        )
        second = _run(
            triangle,
            tmp=tmp,
            stores=stores,
            name="det-2",
            amount_grid=(30, 10, 20),
            economics=_economics(7),
        )
        assert first.replay_digest == second.replay_digest, "replay diverged"
        scenarios.append(("determinism-proof-triangle", first))

        for store in stores:
            store.close()

    combined = {
        "schema_version": "r10-1.pre-api-route-replay.v1",
        "evidence_scope": "fixture-replay",
        "contains_live_evidence": False,
        "sign_enabled": False,
        "send_enabled": False,
        "live_mode": False,
        "scenarios": [
            {"scenario": name, "report": report.to_json()} for name, report in scenarios
        ],
        "determinism_verified": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(combined, sort_keys=True, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    summary = combined["scenarios"]
    print(f"replay scenarios: {len(summary)}")
    for entry in summary:
        metrics = entry["report"]["metrics"]
        print(
            f"  {entry['scenario']}: "
            f"topology={metrics['topology_route_count']} "
            f"exact_qualified={metrics['exact_qualified_route_count']} "
            f"net_positive={metrics['net_positive_route_count']} "
            f"paper_complete={metrics['paper_complete_count']} "
            f"digest={entry['report']['replay_digest'][:16]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
