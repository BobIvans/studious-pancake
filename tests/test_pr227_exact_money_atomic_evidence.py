from __future__ import annotations

from dataclasses import replace

import pytest

from src.pr227_exact_money_atomic_evidence import (
    AltSnapshotEvidence,
    AssetIdentity,
    AtomicPlanEvidence,
    CapitalReservationEvidence,
    ExactBaseUnit,
    PR227Error,
    PR227EvidenceBundle,
    PreSignerFreshnessEvidence,
    ProtocolPinEvidence,
    ReadinessStatus,
    RoundingPolicy,
    SimulationEnvelopeEvidence,
    TokenAmount,
    UiToBaseUnitConversion,
    evaluate_bundle,
    reject_non_finite_numeric,
)

D1 = "a" * 64
D2 = "b" * 64
D3 = "c" * 64
D4 = "d" * 64
D5 = "e" * 64
D6 = "f" * 64
P1 = "1" * 32
P2 = ("1" * 31) + "2"
P3 = ("1" * 31) + "3"
P4 = ("1" * 31) + "4"
P5 = ("1" * 31) + "5"


def _asset(symbol: str = "SOL", genesis: str = D1) -> AssetIdentity:
    return AssetIdentity(
        cluster_genesis_hash=genesis,
        mint_pubkey=P1,
        token_program_pubkey=P2,
        rooted_mint_bytes_hash=D2,
        decimals=9,
        metadata_slot=123,
        extensions=("immutable-owner",),
        symbol=symbol,
    )


def _other_asset() -> AssetIdentity:
    return AssetIdentity(
        cluster_genesis_hash=D1,
        mint_pubkey=P3,
        token_program_pubkey=P2,
        rooted_mint_bytes_hash=D3,
        decimals=6,
        metadata_slot=123,
        extensions=(),
        symbol="USDC",
    )


def _pin() -> ProtocolPinEvidence:
    return ProtocolPinEvidence(
        protocol="marginfi",
        program_pubkey=P4,
        materialized_program_bytes_hash=D3,
        materialized_program_bytes_len=2048,
        release_registry_hash=D4,
        source_slot=100,
    )


def _alt() -> AltSnapshotEvidence:
    return AltSnapshotEvidence(
        account_pubkey=P5,
        raw_account_hash=D5,
        source_slot=100,
        current_slot=110,
        addresses=(P1, P2, P3),
        deactivation_slot=None,
        last_extended_slot=105,
        last_extended_slot_start_index=2,
    )


def _plan() -> AtomicPlanEvidence:
    asset = _asset()
    quote_asset = _other_asset()
    pin = _pin()
    alt = _alt()
    return AtomicPlanEvidence(
        plan_id="attempt-001",
        input_amount=TokenAmount(asset, ExactBaseUnit(1_000_000, "u64")),
        leg_a_guaranteed_output=TokenAmount(
            quote_asset,
            ExactBaseUnit(2_000_000, "u64"),
        ),
        leg_b_input=TokenAmount(
            quote_asset,
            ExactBaseUnit(2_000_010, "u64"),
        ),
        leg_b_guaranteed_output=TokenAmount(
            asset,
            ExactBaseUnit(1_200_000, "u64"),
        ),
        flash_repayment_lamports=ExactBaseUnit(100_000, "u64"),
        max_network_fee_lamports=ExactBaseUnit(5_000, "u64"),
        max_jito_tip_lamports=ExactBaseUnit(2_000, "u64"),
        compute_unit_limit=400_000,
        compute_unit_price_micro_lamports=2_500,
        blockhash="blockhash-1",
        alt_hashes=(alt.alt_hash,),
        protocol_pin_hashes=(pin.pin_hash,),
    )


def _simulation(plan: AtomicPlanEvidence) -> SimulationEnvelopeEvidence:
    return SimulationEnvelopeEvidence(
        rpc_endpoint_id="helius-mainnet-readonly",
        cluster_genesis_hash=plan.input_amount.asset.cluster_genesis_hash,
        request_id="request-001",
        jsonrpc_version="2.0",
        api_version="2.1.0",
        raw_request_hash=D1,
        raw_response_hash=D2,
        context_slot=115,
        blockhash=plan.blockhash,
        fee_lamports=ExactBaseUnit(5_000, "u64"),
        sig_verify=True,
        loaded_accounts_data_size=4096,
    )


def _bundle() -> PR227EvidenceBundle:
    plan = _plan()
    simulation = _simulation(plan)
    reservation = CapitalReservationEvidence(
        opportunity_id="opp-001",
        wallet_pubkey=P1,
        generation=1,
        expiry_slot=140,
        reserved_lamports=ExactBaseUnit(1_107_000, "u64"),
        plan_hash=plan.plan_hash,
    )
    freshness = PreSignerFreshnessEvidence(
        plan_hash=plan.plan_hash,
        simulation_hash=simulation.simulation_hash,
        reservation=reservation,
        current_block_height=100,
        last_valid_block_height=120,
        remaining_height_margin=10,
        current_slot=120,
        revalidated_alt_hashes=plan.alt_hashes,
        message_hash=D6,
    )
    return PR227EvidenceBundle(
        plan=plan,
        protocol_pins=(_pin(),),
        alts=(_alt(),),
        simulation=simulation,
        freshness=freshness,
        provider_plane_ready=True,
        secret_release_ready=True,
    )


def test_pr227_happy_path_dependency_gated_bundle() -> None:
    bundle = _bundle()
    verdict = evaluate_bundle(bundle)

    assert verdict["schema"] == "pr227.exact-money-atomic-evidence.v1"
    assert verdict["status"] == ReadinessStatus.READY_DEPENDENCY_GATED.value
    assert verdict["surplus_lamports"] == 93_000
    assert verdict["plan_hash"] == bundle.plan.plan_hash
    assert verdict["simulation_hash"] == bundle.simulation.simulation_hash
    assert isinstance(verdict["bundle_hash"], str)


def test_exact_base_units_reject_bool_float_negative_and_u64_overflow() -> None:
    for value in (True, 1.5, -1, 2**64):
        with pytest.raises(PR227Error):
            ExactBaseUnit(value, "u64")  # type: ignore[arg-type]

    assert ExactBaseUnit(2**64, "u128").value == 2**64


def test_ui_conversion_requires_explicit_remainder_policy() -> None:
    with pytest.raises(PR227Error, match="PR227_EXACT_CONVERSION_HAS_REMAINDER"):
        UiToBaseUnitConversion(
            numerator=1,
            denominator=3,
            decimals=0,
            rounding_policy=RoundingPolicy.EXACT,
            base_units=ExactBaseUnit(0),
            remainder_numerator=0,
        )

    conversion = UiToBaseUnitConversion(
        numerator=1,
        denominator=3,
        decimals=0,
        rounding_policy=RoundingPolicy.FLOOR_WITH_REMAINDER,
        base_units=ExactBaseUnit(0),
        remainder_numerator=1,
    )
    assert conversion.remainder_numerator == 1


def test_asset_identity_is_cluster_mint_program_and_rooted_bytes_bound() -> None:
    asset = _asset()
    same_mint_different_cluster = replace(asset, cluster_genesis_hash=D4)

    assert asset.asset_hash != same_mint_different_cluster.asset_hash
    with pytest.raises(PR227Error):
        replace(asset, mint_pubkey="not-a-pubkey")


def test_plan_hash_changes_on_tip_compute_blockhash_and_alt_identity() -> None:
    plan = _plan()

    assert (
        replace(plan, max_jito_tip_lamports=ExactBaseUnit(3_000)).plan_hash
        != plan.plan_hash
    )
    assert replace(plan, compute_unit_limit=500_000).plan_hash != plan.plan_hash
    assert replace(plan, blockhash="blockhash-2").plan_hash != plan.plan_hash
    assert replace(plan, alt_hashes=(D6,)).plan_hash != plan.plan_hash


def test_caller_supplied_fingerprint_and_missing_dust_accounting_block() -> None:
    plan = _plan()

    with pytest.raises(
        PR227Error,
        match="PR227_CALLER_SUPPLIED_FINGERPRINT_FORBIDDEN",
    ):
        replace(plan, caller_sequence_fingerprint=D1)
    with pytest.raises(PR227Error, match="PR227_LEG_B_DUST_ACCOUNTING_MISSING"):
        replace(
            plan,
            leg_b_input=TokenAmount(
                _other_asset(),
                ExactBaseUnit(1_999_999, "u64"),
            ),
        )


def test_protocol_pin_requires_materialized_bytes_not_hash_syntax_only() -> None:
    with pytest.raises(PR227Error, match="materialized_program_bytes_len"):
        ProtocolPinEvidence(
            protocol="jupiter",
            program_pubkey=P4,
            materialized_program_bytes_hash=D3,
            materialized_program_bytes_len=0,
            release_registry_hash=D4,
            source_slot=1,
        )


def test_alt_evidence_blocks_manual_inconsistent_snapshots() -> None:
    with pytest.raises(PR227Error, match="PR227_ALT_DEACTIVATED"):
        replace(_alt(), deactivation_slot=100)
    with pytest.raises(PR227Error, match="PR227_ALT_V0_ACCOUNT_LIMIT_EXCEEDED"):
        replace(_alt(), addresses=tuple(P1 for _ in range(65)))
    with pytest.raises(PR227Error, match="PR227_ALT_START_INDEX_OUT_OF_RANGE"):
        replace(_alt(), last_extended_slot_start_index=99)


def test_simulation_envelope_requires_raw_rpc_identity_and_success() -> None:
    plan = _plan()

    with pytest.raises(PR227Error, match="PR227_JSONRPC_VERSION_MISMATCH"):
        replace(_simulation(plan), jsonrpc_version="1.0")
    with pytest.raises(
        PR227Error,
        match="PR227_RETRYABLE_SIMULATION_ERROR_NOT_AUTHORITY",
    ):
        replace(_simulation(plan), retryable_error=True)
    with pytest.raises(PR227Error):
        replace(_simulation(plan), sig_verify=1)  # type: ignore[arg-type]


def test_presigner_freshness_blocks_stale_blockhash_and_expired_reservation() -> None:
    bundle = _bundle()
    freshness = bundle.freshness

    with pytest.raises(PR227Error, match="PR227_BLOCKHASH_NOT_FRESH_BEFORE_SIGNER"):
        replace(
            freshness,
            current_block_height=111,
            last_valid_block_height=120,
            remaining_height_margin=10,
        )
    with pytest.raises(PR227Error, match="PR227_RESERVATION_EXPIRED_BEFORE_SIGNER"):
        replace(freshness, current_slot=140)


def test_bundle_blocks_dependency_mismatch_and_cluster_drift() -> None:
    bundle = _bundle()

    with pytest.raises(PR227Error, match="PR227_PR225_PROVIDER_PLANE_NOT_READY"):
        replace(bundle, provider_plane_ready=False)
    with pytest.raises(PR227Error, match="PR227_PR228_TRUST_PLANE_NOT_READY"):
        replace(bundle, secret_release_ready=False)

    wrong_cluster_simulation = replace(bundle.simulation, cluster_genesis_hash=D4)
    wrong_cluster_freshness = replace(
        bundle.freshness,
        simulation_hash=wrong_cluster_simulation.simulation_hash,
    )
    with pytest.raises(PR227Error, match="PR227_SIMULATION_CLUSTER_MISMATCH"):
        replace(
            bundle,
            simulation=wrong_cluster_simulation,
            freshness=wrong_cluster_freshness,
        )


def test_reject_non_finite_numeric_public_helper() -> None:
    with pytest.raises(PR227Error):
        reject_non_finite_numeric(float("nan"), "age")
    with pytest.raises(PR227Error):
        reject_non_finite_numeric(float("inf"), "age")
    reject_non_finite_numeric(1.0, "age")
