"""Mixed CPMM/CLMM/DLMM exact route binding and deterministic replay.

Extends the R10-1 owner with the CLMM/DLMM qualified evaluators. All evidence
is offline fixture/replay class; no signer, sender, borrowing, submission or
live source appears anywhere. Jupiter Lend connects only as the R02/R03
fail-closed evidence seam.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import struct
import time

import pytest
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
from src.strategy.clmm_dlmm_binding import (
    QualifiedClmmAdapter,
    QualifiedClmmState,
    QualifiedDlmmAdapter,
    QualifiedDlmmState,
    evaluate_exact_mixed_route,
    run_clmm_dlmm_mixed_route_replay,
)
from src.strategy.cpmm_cycle_binding import (
    BlockedVenueCandidate,
    CpmmBindingError,
    CpmmBindingRejection,
    PaperGateInputs,
    PoolLineage,
    RouteQualificationStatus,
    RouteSupport,
    VenueKind,
    classify_route_support,
    evaluate_exact_two_leg_route,
    evaluate_paper_gate,
)
from src.strategy.exact_cpmm_capacity import (
    CapacityEconomics,
    QualifiedCpmmState,
    SolanaAssetIdentity,
)
from src.providers.meteora_dlmm_native import decode_bin_array, decode_lb_pair
from src.providers.raydium_clmm_native import (
    decode_clmm_amm_config,
    decode_clmm_pool_state,
    decode_clmm_tick_array,
    tick_array_start_index,
)
from src.providers.raydium_cpmm_native import NativeAccount

from tests.meteora_dlmm_fixtures import (
    bin_array_bytes,
    lb_pair_bytes_v2,
    rpc_account as dlmm_account,
)
from tests.raydium_clmm_fixtures import (
    clmm_amm_config_bytes,
    clmm_pool_bytes,
    clmm_tick_array_bytes,
    rpc_account,
)

pytestmark = pytest.mark.unit

NOW = 1_000.0
GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
WSOL_MINT = "So11111111111111111111111111111111111111112"
GENERATION = ObservationGeneration(
    genesis_hash=GENESIS,
    provider_generation="fixture-provider-v1",
    asset_generation="fixture-assets-v1",
    policy_generation="shadow-only-v1",
    code_generation="clmm-dlmm-binding-v1",
)


def _asset(mint: str, **changes: object) -> SolanaAssetIdentity:
    values: dict[str, object] = {
        "domain": "solana-mainnet",
        "genesis_hash": GENESIS,
        "mint": mint,
        "token_program": TOKEN_PROGRAM,
        "token_revision": "spl-token-v1",
        "decimals": 9,
    }
    values.update(changes)
    return SolanaAssetIdentity(**values)  # type: ignore[arg-type]


TOKEN_B = str(Pubkey.from_bytes(bytes([1]) * 32))
TOKEN_C = str(Pubkey.from_bytes(bytes([2]) * 32))
WSOL = _asset(WSOL_MINT)
B_ASSET = _asset(TOKEN_B)
C_ASSET = _asset(TOKEN_C)


def _native(entry: dict) -> NativeAccount:
    return NativeAccount.from_rpc(entry["address"], entry)


def _clmm_state(
    market_id: str,
    mints: tuple[str, str],
    *,
    liquidity: int = 10_000_000_000_000,
    tick_current: int = 0,
    ticks: dict[int, dict[int, tuple[int, int]]] | None = None,
    slot: int = 100,
    **state_changes: object,
) -> QualifiedClmmState:
    pool_bytes, pool_id, _ = clmm_pool_bytes(
        config_address=address(12),
        mints=mints,
        liquidity=liquidity,
        tick_current=tick_current,
        bitmap_bits=tuple(start // (60 * 1) + 512 for start in (ticks or {})),
    )
    config_entry = rpc_account(
        address(12),
        "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
        clmm_amm_config_bytes(),
    )
    config = decode_clmm_amm_config(_native(config_entry))
    pool = decode_clmm_pool_state(
        _native(
            rpc_account(
                pool_id, "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK", pool_bytes
            )
        )
    )
    arrays = []
    for start, layout in (ticks or {}).items():
        data = clmm_tick_array_bytes(pool_id, start, initialized=layout)
        arrays.append(
            decode_clmm_tick_array(
                _native(
                    rpc_account(
                        clmm_tick_array_pda(pool_id, start),
                        "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
                        data,
                    )
                ),
                expected_pool=pool_id,
                expected_start=start,
            )
        )
    values: dict[str, object] = {
        "venue": VenueIdentity(
            "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK", market_id
        ),
        "asset_a": _asset(mints[0]),
        "asset_b": _asset(mints[1]),
        "pool": pool,
        "config": config,
        "tick_arrays": tuple(arrays),
        "bitmap_extension": None,
        "block_timestamp": None,
        "slot": slot,
        "observed_at": NOW - 1,
        "expires_at": NOW + 1,
        "generation": GENERATION,
        "account_hashes": (
            f"pool:{pool_id[:8]}",
            f"config:{config.address[:8]}",
        ),
    }
    values.update(state_changes)
    return QualifiedClmmState(**values)  # type: ignore[arg-type]


def clmm_tick_array_pda(pool_id: str, start: int) -> str:
    from src.providers.raydium_clmm_native import clmm_tick_array_pda as _pda

    return _pda(pool_id, start)


def address(seed: int) -> str:  # noqa: D103 - fixture helper
    return str(Pubkey.from_bytes(bytes([seed]) * 32))


def _dlmm_state(
    market_id: str,
    mints: tuple[str, str],
    *,
    bins: dict[int, dict[int, tuple[int, int, int, int]]] | None = None,
    slot: int = 100,
    **state_changes: object,
) -> QualifiedDlmmState:
    def q64(bin_id: int) -> int:
        return round((1.001**bin_id) * (1 << 64))

    pair_bytes, pair_id, _ = lb_pair_bytes_v2(
        active_id=5, mints=mints, min_bin_id=-7000, max_bin_id=7000
    )
    # The SDK bin-array search consults the LbPair bitmap; mark every
    # supplied default-window array as initialized (bit = index + 512).
    buffer = bytearray(pair_bytes)
    for index in bins or {}:
        bit = index + 512
        if 0 <= bit < 1024:
            word = bit // 64
            current = int.from_bytes(buffer[584 + 8 * word : 592 + 8 * word], "little")
            struct.pack_into("<Q", buffer, 584 + 8 * word, current | (1 << (bit % 64)))
    pair_bytes = bytes(buffer)
    pair = decode_lb_pair(
        _native(
            dlmm_account(
                pair_id, "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo", pair_bytes
            )
        )
    )
    arrays = []
    for index, layout in (bins or {}).items():
        data = bin_array_bytes(pair_id, index, bins=layout)
        arrays.append(
            decode_bin_array(
                _native(
                    dlmm_account(
                        derive_bin_array_pda(pair_id, index),
                        "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
                        data,
                    )
                ),
                expected_pair=pair_id,
            )
        )
    values: dict[str, object] = {
        "venue": VenueIdentity(
            "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo", market_id
        ),
        "asset_a": _asset(mints[0]),
        "asset_b": _asset(mints[1]),
        "lb_pair": pair,
        "bin_arrays": tuple(arrays),
        "bitmap_extension": None,
        "clock_epoch": 700,
        "current_timestamp": 1_800_000_000,
        "slot": slot,
        "observed_at": NOW - 1,
        "expires_at": NOW + 1,
        "generation": GENERATION,
        "account_hashes": (f"lbpair:{pair_id[:8]}",),
    }
    values.update(state_changes)
    return QualifiedDlmmState(**values)  # type: ignore[arg-type]


def derive_bin_array_pda(pair_id: str, index: int) -> str:
    derived, _ = Pubkey.find_program_address(
        [b"bin_array", bytes(Pubkey.from_string(pair_id)), struct.pack("<q", index)],
        Pubkey.from_string("LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"),
    )
    return str(derived)


def _cpmm_state(
    market_id: str,
    asset_a: SolanaAssetIdentity,
    asset_b: SolanaAssetIdentity,
    reserves: tuple[int, int],
    slot: int = 100,
) -> QualifiedCpmmState:
    return QualifiedCpmmState(
        venue=VenueIdentity("CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C", market_id),
        asset_a=asset_a,
        asset_b=asset_b,
        reserve_a=reserves[0],
        reserve_b=reserves[1],
        fee_bps=25,
        slot=slot,
        observed_at=NOW - 1,
        expires_at=NOW + 1,
        generation=GENERATION,
    )


def _lineage(market_id: str, **changes: object) -> PoolLineage:
    values: dict[str, object] = {
        "correlation_group": f"venue:{market_id}",
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
        maximum_flash_loan_lamports=1_000_000_000,
    )


def _coordinator(tmp_path: Path, name: str) -> DurableCapitalCoordinator:
    return DurableCapitalCoordinator(
        store=DurableLifecycleStore(tmp_path / f"capital-{name}.db"),
        policy=_policy(),
    )


def _wallet() -> WalletBalanceSnapshot:
    return WalletBalanceSnapshot(
        wallet_pubkey="wallet111111111111111111111111111111111111",
        native_lamports=10_000_000,
        context_slot=100,
        captured_at_ns=time.time_ns(),
        cluster_genesis=GENESIS,
    )


def _economics() -> CapacityEconomics:
    return CapacityEconomics(
        settlement_asset_id="WSOL",
        flash_fee_bps=0,
        protocol_rounding_atoms=0,
        native_costs=NativeCostBreakdown(base_network_fee_lamports=0),
    )


# Cross-venue scene: CLMM (B->WSOL direction pool) and DLMM (WSOL->B pool)
# sharing the exact same canonical WSOL / TOKEN_B identities.
CLMM_MINTS = (TOKEN_B, WSOL_MINT)  # mint0 < mint1 required by the fixture
DLMM_MINTS = (WSOL_MINT, TOKEN_B)


def _clmm_scene_state(market_id="clmm-b-sol", **changes) -> QualifiedClmmState:
    # B -> WSOL walks the price DOWN from tick 0; the only initialized tick
    # below (-1) lives in array -60 (in-pool bit 511).
    return _clmm_state(
        market_id,
        CLMM_MINTS,
        tick_current=0,
        ticks={0: {}, -60: {59: (1_000_000_000_000, 2_000_000_000_000)}},
        **changes,
    )


def _dlmm_scene_state(
    market_id="dlmm-sol-b",
    bins=None,
    **changes,
) -> QualifiedDlmmState:
    return _dlmm_state(
        market_id,
        DLMM_MINTS,
        bins=bins or {0: {5: (700, 10_000_000, round((1.005) * (1 << 64)), 1)}},
        **changes,
    )


def test_mixed_two_leg_cross_venue_route_exact():
    dlmm = _dlmm_scene_state()
    clmm = _clmm_scene_state()
    route_id, legs = evaluate_exact_mixed_route(
        (dlmm, clmm),
        settlement_asset=WSOL,
        input_amount=1_000_000,
        now=NOW,
    )
    assert len(legs) == 2
    assert legs[0].input_asset == WSOL and legs[0].output_asset == B_ASSET
    assert legs[1].input_asset == B_ASSET and legs[1].output_asset == WSOL
    assert legs[0].requested_input == 1_000_000
    assert legs[1].requested_input == legs[0].conservative_output
    assert route_id


def test_mixed_two_leg_route_support_matrix():
    # CLMM/DLMM are exact-supported for 2/3/4 hops once registered.
    assert (
        classify_route_support(
            venue_kind=VenueKind.RAYDIUM_CLMM,
            hop_count=2,
            exact_venues=(VenueKind.RAYDIUM_CLMM, VenueKind.METEORA_DLMM),
        )
        is RouteSupport.EXACT_SUPPORTED
    )
    assert (
        classify_route_support(venue_kind=VenueKind.RAYDIUM_CLMM, hop_count=2)
        is RouteSupport.BLOCKED
    )
    assert (
        classify_route_support(
            venue_kind=VenueKind.METEORA_DLMM,
            hop_count=5,
            exact_venues=(VenueKind.METEORA_DLMM,),
        )
        is RouteSupport.SHORTLIST_ONLY
    )


def test_mixed_two_leg_via_owner_two_leg_entry():
    # The #659 owner entry point accepts the CLMM/DLMM adapters directly.
    dlmm = _dlmm_scene_state()
    clmm = _clmm_scene_state()
    evaluation = evaluate_exact_two_leg_route(
        dlmm,
        clmm,
        settlement_asset=WSOL,
        input_amount=1_000_000,
        now=NOW,
        adapters={
            VenueKind.RAYDIUM_CLMM: QualifiedClmmAdapter(),
            VenueKind.METEORA_DLMM: QualifiedDlmmAdapter(),
        },
    )
    assert evaluation.gross_profit != 0 or evaluation.conservative_output > 0


def test_mixed_route_rejects_unregistered_and_repeat_venues():
    dlmm = _dlmm_scene_state()
    clmm = _clmm_scene_state()
    with pytest.raises(CpmmBindingError, match="unsupported-venue-kind"):
        evaluate_exact_mixed_route(
            (dlmm, clmm),
            settlement_asset=WSOL,
            input_amount=1_000,
            now=NOW,
            adapters={VenueKind.RAYDIUM_CLMM: QualifiedClmmAdapter()},
        )
    with pytest.raises(CpmmBindingError, match="non-unique-physical-pool"):
        evaluate_exact_mixed_route(
            (dlmm, dlmm),
            settlement_asset=WSOL,
            input_amount=1_000,
            now=NOW,
        )


def test_mixed_route_rejects_generation_skew_and_staleness():
    dlmm = _dlmm_scene_state()
    stale_clmm = _clmm_scene_state(slot=10_000)
    with pytest.raises(CpmmBindingError, match="slot-skew-exceeded"):
        evaluate_exact_mixed_route(
            (dlmm, stale_clmm), settlement_asset=WSOL, input_amount=1_000, now=NOW
        )
    mixed_gen = _clmm_scene_state(
        generation=ObservationGeneration(
            genesis_hash=GENESIS,
            provider_generation="other",
            asset_generation="fixture-assets-v1",
            policy_generation="shadow-only-v1",
            code_generation="clmm-dlmm-binding-v1",
        )
    )
    with pytest.raises(CpmmBindingError, match="mixed-generation"):
        evaluate_exact_mixed_route(
            (dlmm, mixed_gen), settlement_asset=WSOL, input_amount=1_000, now=NOW
        )
    future = _clmm_scene_state(observed_at=NOW + 10, expires_at=NOW + 20)
    with pytest.raises(CpmmBindingError, match="stale-or-future-state"):
        evaluate_exact_mixed_route(
            (dlmm, future), settlement_asset=WSOL, input_amount=1_000, now=NOW
        )


def test_mixed_replay_two_venue_cycle_positive_and_deterministic(tmp_path: Path):
    dlmm = _dlmm_scene_state()
    clmm = _clmm_scene_state()
    pools = [dlmm, clmm]
    lineage = {pool.venue.market_id: _lineage(pool.venue.market_id) for pool in pools}
    report_one = run_clmm_dlmm_mixed_route_replay(
        pools=pools,
        lineage_by_market=lineage,
        settlement_asset=WSOL,
        now=NOW,
        probe_amount=1_000_000,
        economics=_economics(),
        coordinator=_coordinator(tmp_path, "one"),
        wallet_snapshot=_wallet(),
    )
    report_two = run_clmm_dlmm_mixed_route_replay(
        pools=pools,
        lineage_by_market=lineage,
        settlement_asset=WSOL,
        now=NOW,
        probe_amount=1_000_000,
        economics=_economics(),
        coordinator=_coordinator(tmp_path, "two"),
        wallet_snapshot=_wallet(),
    )
    assert report_one.replay_digest == report_two.replay_digest
    metrics = report_one.metrics
    assert metrics["contains_live_evidence"] is False
    assert metrics["exact_quote_route_count"] >= 1
    # The paper seam stays typed fail-closed in offline replay.
    assert metrics["paper_complete_count"] == 0
    assert metrics["paper_rejected_count"] == metrics["paper_attempt_count"]
    final = [
        record
        for record in report_one.records
        if record.status is RouteQualificationStatus.PAPER_BLOCKED
    ]
    assert final and all(
        record.rejection is CpmmBindingRejection.NO_QUALIFIED_LENDER_EDGE
        for record in final
    )


def test_mixed_replay_dedups_correlated_pools(tmp_path: Path):
    dlmm = _dlmm_scene_state()
    clmm = _clmm_scene_state()
    shared = "shared-pool-id"
    lineage = {
        "dlmm-sol-b": _lineage(
            "dlmm-sol-b",
            pool_ids=(PoolIdentity(PoolIdentityKind.POOL_ADDRESS, shared),),
        ),
        "clmm-b-sol": _lineage(
            "clmm-b-sol",
            pool_ids=(PoolIdentity(PoolIdentityKind.POOL_ADDRESS, shared),),
        ),
    }
    report = run_clmm_dlmm_mixed_route_replay(
        pools=[dlmm, clmm],
        lineage_by_market=lineage,
        settlement_asset=WSOL,
        now=NOW,
        probe_amount=1_000_000,
        economics=_economics(),
        coordinator=_coordinator(tmp_path, "alias"),
        wallet_snapshot=_wallet(),
    )
    assert report.metrics["aliased_or_correlated_route_count"] >= 1
    assert any(
        record.rejection is CpmmBindingRejection.NON_UNIQUE_PHYSICAL_POOL
        for record in report.records
    )


def test_mixed_replay_unknown_lineage_blocks(tmp_path: Path):
    dlmm = _dlmm_scene_state()
    clmm = _clmm_scene_state()
    report = run_clmm_dlmm_mixed_route_replay(
        pools=[dlmm, clmm],
        lineage_by_market={},
        settlement_asset=WSOL,
        now=NOW,
        probe_amount=1_000_000,
        economics=_economics(),
        coordinator=_coordinator(tmp_path, "unknown"),
        wallet_snapshot=_wallet(),
    )
    assert report.metrics["exact_qualified_route_count"] == 0


def test_mixed_replay_blocked_candidates_excluded(tmp_path: Path):
    dlmm = _dlmm_scene_state()
    clmm = _clmm_scene_state()
    report = run_clmm_dlmm_mixed_route_replay(
        pools=[dlmm, clmm],
        lineage_by_market={
            pool.venue.market_id: _lineage(pool.venue.market_id)
            for pool in (dlmm, clmm)
        },
        settlement_asset=WSOL,
        now=NOW,
        probe_amount=1_000_000,
        economics=_economics(),
        coordinator=_coordinator(tmp_path, "blocked"),
        wallet_snapshot=_wallet(),
        blocked_candidates=(
            BlockedVenueCandidate(
                label="clmm-b-sol",
                venue_kind=VenueKind.ORDERBOOK,
                missing_evidence="fill semantics unproven",
            ),
        ),
    )
    assert all("clmm-b-sol" not in record.ordered_venues for record in report.records)


def test_mixed_three_leg_cycle(tmp_path: Path):
    dlmm = _dlmm_scene_state()  # WSOL -> B
    clmm_bc = _clmm_state(
        "clmm-b-c",
        (TOKEN_B, TOKEN_C),
        tick_current=0,
        ticks={0: {}, -60: {59: (1_000_000_000_000, 2_000_000_000_000)}},
    )
    cpmm = _cpmm_state("cpmm-c-sol", C_ASSET, WSOL, (50_000_000_000, 50_000_000_000))
    pools = [dlmm, clmm_bc, cpmm]
    lineage = {pool.venue.market_id: _lineage(pool.venue.market_id) for pool in pools}
    report = run_clmm_dlmm_mixed_route_replay(
        pools=pools,
        lineage_by_market=lineage,
        settlement_asset=WSOL,
        now=NOW,
        probe_amount=1_000_000,
        economics=_economics(),
        coordinator=_coordinator(tmp_path, "triangle"),
        wallet_snapshot=_wallet(),
    )
    assert report.metrics["topology_route_count"] >= 1
    assert any(record.hop_count == 3 for record in report.records)


def test_dlmm_partial_fill_route_is_typed_rejected(tmp_path: Path):
    # A DLMM bin with almost no liquidity forces a partial fill at size.
    tiny = _dlmm_scene_state(bins={0: {5: (700, 500, round(1.005 * (1 << 64)), 1)}})
    clmm = _clmm_scene_state()
    with pytest.raises(CpmmBindingError, match="INSUFFICIENT_LIQUIDITY|NO_EXACT"):
        evaluate_exact_mixed_route(
            (tiny, clmm),
            settlement_asset=WSOL,
            input_amount=1_000_000_000,
            now=NOW,
        )


def test_clmm_walk_exhaustion_is_typed_rejected(tmp_path: Path):
    # One initialized tick only: an oversized walk needs the next array.
    clmm = _clmm_state(
        "clmm-b-sol",
        CLMM_MINTS,
        tick_current=0,
        ticks={0: {}, -60: {59: (1_000_000_000_000, 2_000_000_000_000)}},
    )
    dlmm = _dlmm_scene_state()
    with pytest.raises(CpmmBindingError):
        evaluate_exact_mixed_route(
            (dlmm, clmm),
            settlement_asset=WSOL,
            input_amount=10**12,
            now=NOW,
        )


def test_jupiter_lend_r02_r03_seam_stays_fail_closed(tmp_path: Path):
    """The R02/R03 owners remain the only financing authority; the mixed
    replay consumes their typed blockers without any signer or send."""
    from src.lending.jupiter_lend import reserve_capital_edge_gate

    observation = _reserve_observation()
    gate = reserve_capital_edge_gate(observation)
    assert gate.blockers  # typed, non-empty, no edge
    paper = evaluate_paper_gate(PaperGateInputs())
    assert paper is CpmmBindingRejection.NO_QUALIFIED_LENDER_EDGE
    # builder-conformant paper inputs still refuse paper completion offline
    paper2 = evaluate_paper_gate(
        PaperGateInputs(qualified_lender_edge_count=1, builder_conformance_passed=True)
    )
    assert paper2 is CpmmBindingRejection.SIMULATION_SOURCE_BLOCKED


def _reserve_observation():
    """The real R02 CAP-A offline fixture observation (no fabrication)."""
    from tests.test_r02_cap_a_reader import Fixture

    return Fixture().observation
