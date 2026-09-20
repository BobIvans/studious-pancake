from dataclasses import replace
from fractions import Fraction
import inspect

import pytest

from src.agg06_solana_venues import (
    NF_IDS,
    Agg06Error,
    Evidence,
    Family,
    Level,
    Stage,
    Token2022,
    apply_token2022_fee,
    coverage_manifest,
    package_status,
    qualify_basket,
    qualify_clob_amm,
    qualify_lifecycle,
    qualify_lp_parity,
    qualify_lst_conversion,
    qualify_migration,
    qualify_post_swap,
    qualify_redemption,
    qualify_time_fee,
    quote_clmm,
    quote_clob,
    quote_dynamic_fee,
    validate_clob_window,
)
from src.mpr2621_lst_atomic_exit import (
    AcquisitionProof,
    CandidateLimits,
    CostProof,
    ExitProof,
    LstAtomicExitCandidate,
    LstCapability,
    Mechanism,
    NavState,
    SCHEMA_VERSION as LST_SCHEMA,
)
from src.providers.orderbook.models import TradeDirection, VenueKind
from src.strategies.stable_peg.math import LiquidityBand
from tests.orderbook_fixture_helpers import fixture_snapshot

H1 = "1" * 64
H2 = "2" * 64
MINT = "Lst111111111111111111111111111111111111111"


def evidence(**overrides):
    value = Evidence(
        "gen-1",
        H1,
        100,
        1_000,
        H2,
        "APPROVED",
    )
    return replace(value, **overrides)


def lst_candidate():
    cap = LstCapability(
        "lst:test:gen1",
        MINT,
        "Tokenkeg",
        9,
        "qualified-test-protocol",
        "Pool111",
        "gen1",
        Mechanism.STAKEDEX_WITHDRAW_SOL,
        "mainnet-beta",
        "genesis",
        H1,
        "reviewed_executable",
        route_program_ids=("Pool111",),
        route_account_hash=H2,
        source_pins=("stakedex-sdk@reviewed",),
    )
    return LstAtomicExitCandidate(
        schema_version=LST_SCHEMA,
        candidate_id="cand-agg06",
        capability=cap,
        nav=NavState(
            900,
            123456,
            "gen1",
            1_050_000_000,
            1_000_000_000,
            2_000_000_000,
            H1,
            True,
            True,
        ),
        acquisition=AcquisitionProof(
            "governed-jupiter",
            1_000_000_000,
            1_000_000_000,
            ("Dex111",),
            H1,
            "req-agg06",
            250,
        ),
        exit=ExitProof(
            "governed-stakedex",
            Mechanism.STAKEDEX_WITHDRAW_SOL,
            1_000_000_000,
            1_020_000_000,
            True,
            ("Pool111",),
            H2,
            2_000_000_000,
        ),
        costs=CostProof(1_000_000, 1_000_000, 1_000_000, 5_000, 5_000, 0, 0, 100_000),
        limits=CandidateLimits(
            2_000_000_000,
            2_000_000_000,
            2_000_000_000,
            1_500_000_000,
            10_000_000,
            64,
            24,
        ),
        flash_repayment_lamports=1_001_000_000,
        minimum_surplus_lamports=1_000_000,
        final_message_hash=H1,
        final_simulation_hash=H2,
        simulation_success=True,
        decoded_acquired_lst_atomic=1_000_000_000,
        decoded_consumed_lst_atomic=1_000_000_000,
        decoded_returned_sol_lamports=1_020_000_000,
        decoded_flash_repaid_lamports=1_001_000_000,
        residual_assets={MINT: 0, "WSOL": 0},
    )


def redemption(
    *,
    immediate=True,
    capacity=2_000_000_000,
    amount=1_020_000_000,
    generation="gen1",
    state_hash=H2,
):
    return qualify_redemption(
        immediate=immediate,
        permissioned=False,
        capacity=capacity,
        fee=0,
        paused=False,
        evidence=evidence(generation=generation, state_hash=state_hash),
        amount=amount,
        now=200,
    )


def test_manifest_is_15_nf_sender_free_and_unqualified():
    manifest = coverage_manifest()
    assert len(NF_IDS) == 15
    assert tuple(item["id"] for item in manifest["nf"]) == NF_IDS
    assert manifest["implementation_status"] == "IMPLEMENTED_OFFLINE"
    assert manifest["operational_status"] == "UNQUALIFIED"
    assert manifest["live_enabled"] is False

    import src.agg06_solana_venues as module

    source = inspect.getsource(module)
    for forbidden in (
        "sendTransaction",
        "sendRawTransaction",
        "send_bundle",
        "Keypair(",
        "private_key",
        "aiohttp",
        "requests.",
    ):
        assert forbidden not in source


def test_clob_gap_and_l2_only_semantics():
    gap = validate_clob_window(10, 12, snapshot_complete=True, l3_available=False)
    assert not gap.accepted
    assert "CLOB_SEQUENCE_GAP_REQUIRES_RESYNC" in gap.blockers
    ok = validate_clob_window(10, 11, snapshot_complete=True, l3_available=False)
    assert ok.accepted and ok.value == "L2_ONLY"


def test_clmm_exact_tick_arrays_reference_and_orca_license():
    bands = (
        ("ta-1", LiquidityBand(500, 2, 1, H1)),
        ("ta-2", LiquidityBand(500, 3, 2, H2)),
    )
    result = quote_clmm(
        Family.RAYDIUM_CLMM,
        bands,
        required_arrays=("ta-1", "ta-2"),
        loaded_arrays=("ta-1", "ta-2"),
        fee_ppm=0,
        evidence=evidence(),
        market_id="pool-1",
        direction="a-to-b",
        amount_in=750,
        now=200,
        reference_out=1_375,
    )
    assert result.amount_out == 1_375
    assert result.touched == ("ta-1", "ta-2")
    assert result.level is Level.OFFLINE_VERIFIED

    with pytest.raises(Agg06Error) as missing:
        quote_clmm(
            Family.RAYDIUM_CLMM,
            bands,
            required_arrays=("ta-1", "ta-2"),
            loaded_arrays=("ta-1",),
            fee_ppm=0,
            evidence=evidence(),
            market_id="pool-1",
            direction="a-to-b",
            amount_in=750,
            now=200,
            reference_out=1_375,
        )
    assert missing.value.code == "CLMM_TICK_ARRAY_MISSING"

    with pytest.raises(Agg06Error) as license_error:
        quote_clmm(
            Family.ORCA,
            bands,
            required_arrays=("ta-1", "ta-2"),
            loaded_arrays=("ta-1", "ta-2"),
            fee_ppm=0,
            evidence=evidence(license_decision=None),
            market_id="pool-1",
            direction="a-to-b",
            amount_in=750,
            now=200,
            reference_out=1_375,
        )
    assert license_error.value.code == "ORCA_LICENSE_BLOCKED"


def test_clmm_reference_mismatch_is_research_not_fake_verified():
    result = quote_clmm(
        Family.RAYDIUM_CLMM,
        (("ta-1", LiquidityBand(100, 1, 1, H1)),),
        required_arrays=("ta-1",),
        loaded_arrays=("ta-1",),
        fee_ppm=0,
        evidence=evidence(),
        market_id="pool-1",
        direction="a-to-b",
        amount_in=100,
        now=200,
        reference_out=99,
    )
    assert result.level is Level.RESEARCH
    assert result.blockers == ("CLMM_INDEPENDENT_VECTOR_REQUIRED",)


def test_token2022_fee_cap_and_unknown_hooks():
    out, fee = apply_token2022_fee(10_000, Token2022(fee_bps=100, max_fee=50))
    assert (out, fee) == (9_950, 50)
    zero_capped_out, zero_capped_fee = apply_token2022_fee(
        10_000, Token2022(fee_bps=100, max_fee=0)
    )
    assert (zero_capped_out, zero_capped_fee) == (10_000, 0)
    with pytest.raises(Agg06Error) as hook:
        apply_token2022_fee(10_000, Token2022(unsupported_hooks=("x",)))
    assert hook.value.code == "TOKEN2022_UNSUPPORTED_HOOK"


def test_clob_reuses_integer_lot_engine_and_settlement_gate():
    _, snapshot = fixture_snapshot(VenueKind.PHOENIX_LEGACY_SPOT)
    quote = quote_clob(
        snapshot,
        TradeDirection.SELL_BASE,
        1_500,
        account_ready=True,
        settlement_ready=True,
        reference_min_out=1_476,
        max_slot_skew=2,
    )
    assert quote.quote.min_out == 1_476
    assert quote.reference_match
    assert quote.level is Level.OFFLINE_VERIFIED

    with pytest.raises(Agg06Error) as blocked:
        quote_clob(
            snapshot,
            TradeDirection.SELL_BASE,
            1_500,
            account_ready=True,
            settlement_ready=False,
        )
    assert blocked.value.code == "CLOB_SETTLEMENT_UNPROVEN"


def test_clob_amm_atomic_net_and_negative_case():
    _, snapshot = fixture_snapshot(VenueKind.PHOENIX_LEGACY_SPOT)
    clob = quote_clob(
        snapshot,
        TradeDirection.SELL_BASE,
        1_500,
        account_ready=True,
        settlement_ready=True,
        reference_min_out=1_476,
        max_slot_skew=2,
    )
    good = qualify_clob_amm(
        clob,
        terminal_out=2_000,
        repayment=1_500,
        independent_costs=100,
        same_message=True,
        settlement_proven=True,
        repayment_asset_matches=True,
    )
    assert good.accepted and good.value == 400

    bad = qualify_clob_amm(
        clob,
        terminal_out=1_500,
        repayment=1_500,
        independent_costs=1,
        same_message=False,
        settlement_proven=False,
        repayment_asset_matches=False,
    )
    assert not bad.accepted
    assert "CLOB_AMM_NONPOSITIVE_NET" in bad.blockers


def test_lst_immediate_exit_reuses_mpr2621_authority():
    good = qualify_lst_conversion(lst_candidate(), redemption())
    assert good.decision.value == "QUALIFIED_SENDER_FREE"
    assert good.sender_allowed is False and good.live_enabled is False

    delayed = qualify_lst_conversion(lst_candidate(), redemption(immediate=False))
    assert delayed.decision.value == "BLOCKED"
    assert "REDEMPTION_NOT_IMMEDIATE" in delayed.blockers

    wrong_amount = qualify_lst_conversion(
        lst_candidate(), redemption(amount=1, capacity=2_000_000_000)
    )
    assert wrong_amount.decision.value == "BLOCKED"
    assert "REDEMPTION_EVIDENCE_IDENTITY_MISMATCH" in wrong_amount.blockers

    wrong_generation = qualify_lst_conversion(
        lst_candidate(), redemption(generation="other")
    )
    assert wrong_generation.decision.value == "BLOCKED"
    assert "REDEMPTION_EVIDENCE_IDENTITY_MISMATCH" in wrong_generation.blockers


def test_basket_and_lp_parity_use_exact_rational_rights():
    kwargs = dict(
        input_units=100,
        input_num=1,
        input_den=1,
        output_units=120,
        output_num=1,
        output_den=1,
        fee_units=5,
        immediate=True,
        complete=True,
        evidence=evidence(),
        now=200,
    )
    basket = qualify_basket(**kwargs)
    lp = qualify_lp_parity(**kwargs)
    assert basket.accepted and basket.value == Fraction(15, 1)
    assert lp.value == basket.value


def test_dynamic_fee_clock_token2022_and_time_crossing():
    first = quote_dynamic_fee(
        base_fee_ppm=10_000,
        variable_fee_ppm=10_000,
        valid_until=300,
        evidence=evidence(),
        market_id="dlmm-1",
        direction="a-to-b",
        amount=100,
        bands=(LiquidityBand(100, 2, 1, H1),),
        now=200,
        token2022=Token2022(fee_bps=100, max_fee=5),
    )
    assert first.fee == 2
    assert first.transfer_fee == 2
    assert first.amount_out == 194

    later = replace(first, amount_out=200)
    signal = qualify_time_fee(
        first,
        later,
        elapsed_seconds=5,
        loan_held_across_wait=False,
    )
    assert signal.accepted and signal.level is Level.RECORDED_OFFLINE
    unrelated = qualify_time_fee(
        first,
        replace(later, market_id="other-market"),
        elapsed_seconds=5,
        loan_held_across_wait=False,
    )
    assert not unrelated.accepted
    assert "TIME_FEE_PROVENANCE_MISMATCH" in unrelated.blockers

    held = qualify_time_fee(
        first,
        later,
        elapsed_seconds=5,
        loan_held_across_wait=True,
    )
    assert not held.accepted

    with pytest.raises(Agg06Error) as stale:
        quote_dynamic_fee(
            base_fee_ppm=0,
            variable_fee_ppm=0,
            valid_until=150,
            evidence=evidence(),
            market_id="dlmm-1",
            direction="a-to-b",
            amount=100,
            bands=(LiquidityBand(100, 1, 1, H1),),
            now=200,
        )
    assert stale.value.code == "DLMM_FEE_CLOCK_STALE"


def test_lifecycle_migration_and_post_swap_fail_closed():
    assert qualify_lifecycle(
        stage=Stage.TRADING,
        fee_ppm=1_000,
        evidence=evidence(),
        now=200,
    ).accepted
    assert not qualify_lifecycle(
        stage=Stage.GRADUATED,
        fee_ppm=1_000,
        evidence=evidence(),
        now=200,
    ).accepted

    migration = qualify_migration(
        event_id="m1",
        seen_event_ids=frozenset(),
        old_generation="g1",
        new_generation="g2",
        finalized=True,
        old_stage=Stage.GRADUATED,
        new_stage=Stage.TRADING,
        evidence=evidence(),
        now=200,
    )
    assert migration.accepted and migration.value == "g2"
    split = qualify_migration(
        event_id="m1",
        seen_event_ids=frozenset(),
        old_generation="g1",
        new_generation="g2",
        finalized=True,
        old_stage=Stage.TRADING,
        new_stage=Stage.TRADING,
        evidence=evidence(),
        now=200,
    )
    assert not split.accepted

    post = qualify_post_swap(
        pre_hash=H1,
        post_hash=H2,
        event_slot=100,
        post_slot=101,
        complete=True,
        evidence=evidence(),
        now=200,
    )
    assert post.accepted and post.value == H2


def test_package_status_keeps_code_and_operational_truth_separate():
    missing = package_status({}, {})
    assert missing["implementation_status"] == "IMPLEMENTED_OFFLINE"
    assert missing["operational_status"] == "UNQUALIFIED"
    assert missing["live_enabled"] is False
    assert set(missing["missing_prerequisites"]) == {
        "AGG-01",
        "AGG-02",
        "AGG-04",
        "AGG-05",
    }

    ready = package_status(
        {name: True for name in ("AGG-01", "AGG-02", "AGG-04", "AGG-05")},
        {family: True for family in Family},
    )
    assert ready["operational_status"] == "EXTERNALLY_QUALIFIED_FOR_PROFILE"
    assert ready["live_enabled"] is False


def test_future_evidence_rejected_before_qualification():
    with pytest.raises(Agg06Error) as future:
        qualify_lifecycle(
            stage=Stage.TRADING,
            fee_ppm=1_000,
            evidence=evidence(observed_at=900, expires_at=1_000),
            now=200,
        )
    assert future.value.code == "EVIDENCE_FROM_FUTURE"


def test_clmm_repeated_band_digest_preserves_tick_array_identity():
    shared_digest = H1
    result = quote_clmm(
        Family.RAYDIUM_CLMM,
        (
            ("ta-1", LiquidityBand(50, 1, 1, shared_digest)),
            ("ta-2", LiquidityBand(50, 1, 1, shared_digest)),
        ),
        required_arrays=("ta-1", "ta-2"),
        loaded_arrays=("ta-1", "ta-2"),
        fee_ppm=0,
        evidence=evidence(),
        market_id="pool-repeat",
        direction="a-to-b",
        amount_in=100,
        now=200,
        reference_out=100,
    )
    assert result.touched == ("ta-1", "ta-2")
