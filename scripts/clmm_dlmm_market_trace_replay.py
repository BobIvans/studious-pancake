"""CLMM/DLMM deterministic mixed-route market-trace qualification replay.

Runs the offline mixed CPMM/CLMM/DLMM route qualification replay (fixture
account builders + the exact venue quote owners) and writes the combined
report JSON with its deterministic digest. All inputs and outputs are
fixture/replay evidence; no live API call, signing, sending, borrowing or
provider activation occurs. Run with the repository interpreter:

    .venv/Scripts/python.exe scripts/clmm_dlmm_market_trace_replay.py \
        --output docs/roadmap/clmm-dlmm-market-trace-qualification-2026-11-15/replay_report_2026-11-21.json
"""

from __future__ import annotations

import argparse
from pathlib import Path
import json
import struct
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solders.pubkey import Pubkey

from src.durability import DurableLifecycleStore
from src.economics.capital import CapitalPolicy, NativeCostBreakdown
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)
from src.execution.quote_build_kernel import PoolIdentity, PoolIdentityKind
from src.market.observations import ObservationGeneration
from src.strategy.arbitrage_graph import VenueIdentity
from src.providers.meteora_dlmm_native import decode_bin_array, decode_lb_pair
from src.providers.raydium_clmm_native import (
    decode_clmm_amm_config,
    decode_clmm_pool_state,
    decode_clmm_tick_array,
)
from src.providers.raydium_cpmm_native import NativeAccount
from src.strategy.clmm_dlmm_binding import (
    QualifiedClmmState,
    QualifiedDlmmState,
    run_clmm_dlmm_mixed_route_replay,
)
from src.strategy.cpmm_cycle_binding import (
    BlockedVenueCandidate,
    PaperGateInputs,
    PoolLineage,
    VenueKind,
)
from src.strategy.exact_cpmm_capacity import (
    CapacityEconomics,
    QualifiedCpmmState,
    SolanaAssetIdentity,
)

NOW = 1_000.0
GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
CLMM_PROGRAM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"
DLMM_PROGRAM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
WSOL_MINT = "So11111111111111111111111111111111111111112"
TOKEN_B = str(Pubkey.from_bytes(bytes([1]) * 32))
TOKEN_C = str(Pubkey.from_bytes(bytes([2]) * 32))
GENERATION = ObservationGeneration(
    genesis_hash=GENESIS,
    provider_generation="fixture-provider-v1",
    asset_generation="fixture-assets-v1",
    policy_generation="shadow-only-v1",
    code_generation="clmm-dlmm-binding-v1",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from tests.meteora_dlmm_fixtures import bin_array_bytes, lb_pair_bytes_v2  # noqa: E402
from tests.raydium_clmm_fixtures import (  # noqa: E402
    clmm_amm_config_bytes,
    clmm_pool_bytes,
    clmm_tick_array_bytes,
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


WSOL = _asset(WSOL_MINT)
B_ASSET = _asset(TOKEN_B)
C_ASSET = _asset(TOKEN_C)


def _native(entry: dict) -> NativeAccount:
    return NativeAccount.from_rpc(entry["address"], entry)


def _address(seed: int) -> str:
    return str(Pubkey.from_bytes(bytes([seed]) * 32))


def _build_clmm(
    market_id: str, mints: tuple[str, str], ticks: dict
) -> QualifiedClmmState:
    pool_bytes, pool_id, _ = clmm_pool_bytes(
        config_address=_address(12),
        mints=mints,
        liquidity=10_000_000_000_000,
        tick_current=0,
        bitmap_bits=tuple(start // 60 + 512 for start in ticks),
    )
    config = decode_clmm_amm_config(
        _native(
            {
                "address": _address(12),
                "executable": False,
                "owner": CLMM_PROGRAM,
                "lamports": 1,
                "data": [
                    __import__("base64").b64encode(clmm_amm_config_bytes()).decode(),
                    "base64",
                ],
            }
        )
    )
    pool = decode_clmm_pool_state(
        _native(
            {
                "address": pool_id,
                "executable": False,
                "owner": CLMM_PROGRAM,
                "lamports": 1,
                "data": [
                    __import__("base64").b64encode(pool_bytes).decode(),
                    "base64",
                ],
            }
        )
    )
    arrays = []
    for start, layout in ticks.items():
        data = clmm_tick_array_bytes(pool_id, start, initialized=layout)
        pda, _ = Pubkey.find_program_address(
            [
                b"tick_array",
                bytes(Pubkey.from_string(pool_id)),
                start.to_bytes(4, "big", signed=True),
            ],
            Pubkey.from_string(CLMM_PROGRAM),
        )
        arrays.append(
            decode_clmm_tick_array(
                _native(
                    {
                        "address": str(pda),
                        "executable": False,
                        "owner": CLMM_PROGRAM,
                        "lamports": 1,
                        "data": [
                            __import__("base64").b64encode(data).decode(),
                            "base64",
                        ],
                    }
                ),
                expected_pool=pool_id,
                expected_start=start,
            )
        )
    return QualifiedClmmState(
        venue=VenueIdentity(CLMM_PROGRAM, market_id),
        asset_a=_asset(mints[0]),
        asset_b=_asset(mints[1]),
        pool=pool,
        config=config,
        tick_arrays=tuple(arrays),
        bitmap_extension=None,
        block_timestamp=None,
        slot=100,
        observed_at=NOW - 1,
        expires_at=NOW + 1,
        generation=GENERATION,
        account_hashes=(f"pool:{pool_id[:8]}", f"config:{config.address[:8]}"),
    )


def _build_dlmm(
    market_id: str, mints: tuple[str, str], bins: dict
) -> QualifiedDlmmState:
    def q64(bin_id: int) -> int:
        return round((1.001**bin_id) * (1 << 64))

    pair_bytes, pair_id, _ = lb_pair_bytes_v2(
        active_id=5, mints=mints, min_bin_id=-7000, max_bin_id=7000
    )
    buffer = bytearray(pair_bytes)
    for index in bins:
        bit = index + 512
        if 0 <= bit < 1024:
            word = bit // 64
            current = int.from_bytes(buffer[584 + 8 * word : 592 + 8 * word], "little")
            struct.pack_into("<Q", buffer, 584 + 8 * word, current | (1 << (bit % 64)))
    pair = decode_lb_pair(
        _native(
            {
                "address": pair_id,
                "executable": False,
                "owner": DLMM_PROGRAM,
                "lamports": 1,
                "data": [
                    __import__("base64").b64encode(bytes(buffer)).decode(),
                    "base64",
                ],
            }
        )
    )
    arrays = []
    for index, layout in bins.items():
        data = bin_array_bytes(pair_id, index, bins=layout)
        pda, _ = Pubkey.find_program_address(
            [
                b"bin_array",
                bytes(Pubkey.from_string(pair_id)),
                struct.pack("<q", index),
            ],
            Pubkey.from_string(DLMM_PROGRAM),
        )
        arrays.append(
            decode_bin_array(
                _native(
                    {
                        "address": str(pda),
                        "executable": False,
                        "owner": DLMM_PROGRAM,
                        "lamports": 1,
                        "data": [
                            __import__("base64").b64encode(data).decode(),
                            "base64",
                        ],
                    }
                ),
                expected_pair=pair_id,
            )
        )
    return QualifiedDlmmState(
        venue=VenueIdentity(DLMM_PROGRAM, market_id),
        asset_a=_asset(mints[0]),
        asset_b=_asset(mints[1]),
        lb_pair=pair,
        bin_arrays=tuple(arrays),
        bitmap_extension=None,
        clock_epoch=700,
        current_timestamp=1_800_000_000,
        slot=100,
        observed_at=NOW - 1,
        expires_at=NOW + 1,
        generation=GENERATION,
        account_hashes=(f"lbpair:{pair_id[:8]}",),
    )


def _build_cpmm(
    market_id: str, asset_a: SolanaAssetIdentity, asset_b: SolanaAssetIdentity
) -> QualifiedCpmmState:
    return QualifiedCpmmState(
        venue=VenueIdentity("CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C", market_id),
        asset_a=asset_a,
        asset_b=asset_b,
        reserve_a=50_000_000_000,
        reserve_b=50_000_000_000,
        fee_bps=25,
        slot=100,
        observed_at=NOW - 1,
        expires_at=NOW + 1,
        generation=GENERATION,
    )


def _lineage(market_id: str) -> PoolLineage:
    return PoolLineage(
        correlation_group=f"venue:{market_id}",
        aggregator_lineage=(),
        pool_ids=(PoolIdentity(PoolIdentityKind.POOL_ADDRESS, market_id),),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/roadmap/clmm-dlmm-market-trace-qualification-2026-11-15/"
            "replay_report_2026-11-21.json"
        ),
    )
    args = parser.parse_args()

    dlmm = _build_dlmm(
        "dlmm-sol-b",
        (WSOL_MINT, TOKEN_B),
        {0: {5: (700, 10_000_000, round(1.005 * (1 << 64)), 1)}},
    )
    clmm = _build_clmm(
        "clmm-b-sol", (TOKEN_B, WSOL_MINT), {-60: {59: (10**12, 2 * 10**12)}, 0: {}}
    )
    clmm_bc = _build_clmm(
        "clmm-b-c",
        (TOKEN_B, TOKEN_C),
        {-60: {59: (10**12, 2 * 10**12)}, 0: {}},
    )
    cpmm = _build_cpmm("cpmm-c-sol", C_ASSET, WSOL)
    pools = [dlmm, clmm, clmm_bc, cpmm]
    lineage = {pool.venue.market_id: _lineage(pool.venue.market_id) for pool in pools}

    policy = CapitalPolicy(
        protected_reserve_lamports=0,
        minimum_net_profit_lamports=1,
        maximum_priority_fee_lamports=10_000,
        maximum_jito_tip_lamports=10_000,
        maximum_peak_rent_lamports=10_000,
        contingency_lamports=0,
        maximum_flash_loan_lamports=1_000_000_000,
    )
    economics = CapacityEconomics(
        settlement_asset_id="WSOL",
        flash_fee_bps=0,
        protocol_rounding_atoms=0,
        native_costs=NativeCostBreakdown(base_network_fee_lamports=0),
    )

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        report = run_clmm_dlmm_mixed_route_replay(
            pools=pools,
            lineage_by_market=lineage,
            settlement_asset=WSOL,
            now=NOW,
            probe_amount=1_000_000,
            economics=economics,
            coordinator=DurableCapitalCoordinator(
                store=DurableLifecycleStore(Path(tmp) / "capital.db"),
                policy=policy,
            ),
            wallet_snapshot=WalletBalanceSnapshot(
                wallet_pubkey="wallet111111111111111111111111111111111111",
                native_lamports=10_000_000,
                context_slot=100,
                captured_at_ns=time.time_ns(),
                cluster_genesis=GENESIS,
            ),
            paper_gate=PaperGateInputs(),
        )

    payload = {
        "schema": "studious-pancake.clmm-dlmm-mixed-route-replay.v1",
        "generated_at": "2026-11-21",
        "evidence_scope": report.evidence_scope,
        "contains_live_evidence": report.contains_live_evidence,
        "venue_models": {
            "raydium_clmm": {
                "source_revision": "6d7a0f82d2f293c553c69aaf943377367c6c4cc6",
                "decoder_revision": "raydium-clmm-state.v1",
                "state": "exact_in_quote_with_bitmap_extension_and_dynamic_fee",
            },
            "meteora_dlmm": {
                "source_revision": "1532e540db41ac405dbf4c5bb2ddfceaa1f98ff1",
                "decoder_revision": "meteora-dlmm-state.v1",
                "quote_revision": "meteora-dlmm-quote-sdk1532e54.v1",
                "state": "exact_in_quote_from_pinned_sdk_closure",
            },
        },
        "stage_metrics": report.metrics,
        "records": [
            {
                "route_kind": record.route_kind,
                "semantic_route_id": record.semantic_route_id,
                "support": record.support.value,
                "status": record.status.value,
                "hop_count": record.hop_count,
                "rejection": record.rejection.value if record.rejection else None,
                "detail": record.detail,
                "ordered_venues": list(record.ordered_venues),
            }
            for record in report.records
        ],
        "replay_digest": report.replay_digest,
        "notes": [
            "Fixture/replay evidence only; no live source, RPC or credential was touched.",
            "Jupiter Lend connects only as the R02 capacity / R03 unsigned-plan gate; "
            "paper stays typed fail-closed (no qualified lender edge offline).",
            "No signer, private key, signing, sending, borrowing, spending, provider "
            "activation or production promotion is performed or enabled by this run.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"WROTE {args.output}")
    print(f"REPLAY_DIGEST {report.replay_digest}")
    print(
        "STAGES "
        + json.dumps(
            {
                key: report.metrics[key]
                for key in (
                    "topology_route_count",
                    "unique_semantic_route_count",
                    "exact_quote_route_count",
                    "exact_qualified_route_count",
                    "net_positive_route_count",
                    "paper_rejected_count",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
