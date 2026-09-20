from __future__ import annotations

from dataclasses import replace

import pytest

from src.cross_chain.agg12 import (
    BasketComponent,
    BasketEvidence,
    ChainAsset,
    ChainDialect,
    ChainResearchDossier,
    CollateralFirstEvidence,
    DynamicFeeEvidence,
    EvmCycleEvidence,
    FlashMintEvidence,
    GasBidOption,
    IntentEvidence,
    LendingAwareEvidence,
    LlammaEvidence,
    NettingEvidence,
    OptInBackrunEvidence,
    PendleEvidence,
    ResearchDisposition,
    RouteLeg,
    SuiCycleEvidence,
    SuiObjectTransition,
    VaultEvidence,
    build_starknet_aptos_adapters,
    choose_sui_gas_option,
    evaluate_emerging_chain,
    qualify_bold_basket,
    qualify_compound_stock,
    qualify_erc4626,
    qualify_eulerswap,
    qualify_evm_cycle,
    qualify_flashmint_psm,
    qualify_intent_fill,
    qualify_llamma,
    qualify_morpho_preliq,
    qualify_netting,
    qualify_optin_backrun,
    qualify_pendle,
    qualify_sky_callback,
    qualify_stablesurge,
    qualify_sui_book,
)

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64


def asset(
    name: str,
    dialect: ChainDialect = ChainDialect.EVM,
) -> ChainAsset:
    return ChainAsset("chain-a", dialect, name, 18, "g1")


def leg(
    input_name: str,
    output_name: str,
    *,
    before: str,
    after: str,
    shared: str,
    amount_in: int = 100,
    guaranteed_out: int = 110,
    dialect: ChainDialect = ChainDialect.EVM,
    family: str = "uniswap-v3",
) -> RouteLeg:
    return RouteLeg(
        protocol="verified-protocol",
        pool_or_market=shared,
        model_family=family,
        input_asset=asset(input_name, dialect),
        output_asset=asset(output_name, dialect),
        amount_in=amount_in,
        guaranteed_out=guaranteed_out,
        fee_units=1,
        state_before_sha256=before,
        state_after_sha256=after,
        shared_resource_id=shared,
    )


def research(dialect: ChainDialect) -> ChainResearchDossier:
    return ChainResearchDossier(
        chain_id=f"{dialect.value}-mainnet",
        dialect=dialect,
        adapter_dialect=dialect,
        official_state_api=True,
        official_simulation_api=True,
        executable_primitives=("swap", "state-read"),
        native_gas_asset="GAS",
        sdk_license="Apache-2.0",
        deployment_evidence_sha256=H1,
        signing_model="dialect-native-signing",
        finality_model="dialect-native-finality",
        resource_model="dialect-native-resources",
        access_available=True,
    )


def test_nf269_starknet_and_aptos_keep_separate_dialects() -> None:
    starknet, aptos = build_starknet_aptos_adapters(
        research(ChainDialect.STARKNET),
        research(ChainDialect.APTOS),
    )
    assert starknet.disposition is ResearchDisposition.OFFLINE_SUPPORTED
    assert aptos.disposition is ResearchDisposition.OFFLINE_SUPPORTED

    bad = replace(
        research(ChainDialect.STARKNET),
        adapter_dialect=ChainDialect.EVM,
    )
    blocked, _ = build_starknet_aptos_adapters(
        bad,
        research(ChainDialect.APTOS),
    )
    assert "CHAIN_DIALECT_ADAPTER_MISMATCH" in blocked.blockers


def test_nf270_emerging_chain_missing_access_is_research_only() -> None:
    verdict = evaluate_emerging_chain(
        replace(
            research(ChainDialect.EVM),
            access_available=False,
        )
    )
    assert verdict.disposition is ResearchDisposition.RESEARCH_ONLY
    assert "CHAIN_ACCESS_UNAVAILABLE" in verdict.blockers
    assert verdict.live_enabled is False


def test_nf272_evm_cycle_requires_state_continuity_and_gas() -> None:
    legs = (
        leg(
            "A",
            "B",
            before=H1,
            after=H2,
            shared="pool-1",
        ),
        leg(
            "B",
            "A",
            before=H2,
            after=H3,
            shared="pool-1",
        ),
    )
    good = EvmCycleEvidence(
        legs,
        50,
        40,
        1,
        1,
        7,
        True,
        True,
    )
    assert qualify_evm_cycle(good).admitted

    bad = replace(
        good,
        legs=(
            legs[0],
            replace(
                legs[1],
                state_before_sha256=H4,
            ),
        ),
        funded_gas_units=0,
    )
    decision = qualify_evm_cycle(bad)
    assert "LEG_1_SHARED_RESOURCE_STATE_RESET" in decision.blockers
    assert "EVM_GAS_NOT_FUNDED" in decision.blockers

    losing = replace(
        good,
        legs=(
            legs[0],
            replace(legs[1], guaranteed_out=1),
        ),
        conservative_net_base_units=7,
    )
    losing_decision = qualify_evm_cycle(losing)
    assert "EVM_CLAIMED_NET_EXCEEDS_ROUTE_BOUND" in losing_decision.blockers
    assert "EVM_CONSERVATIVE_NET_NONPOSITIVE" in losing_decision.blockers

    decimal_mismatch = replace(
        good,
        legs=(
            legs[0],
            replace(
                legs[1],
                input_asset=ChainAsset(
                    "chain-a",
                    ChainDialect.EVM,
                    "B",
                    6,
                    "g1",
                ),
            ),
        ),
    )
    assert (
        "LEG_1_ASSET_CONTINUITY_BROKEN"
        in qualify_evm_cycle(decimal_mismatch).blockers
    )


def collateral(mechanism: str) -> CollateralFirstEvidence:
    return CollateralFirstEvidence(
        mechanism=mechanism,
        deployment_current=True,
        terms_current=True,
        access_permitted=True,
        collateral_units=100,
        collateral_sale_output_units=150,
        debt_units=100,
        funding_units=100,
        gas_cost_base_units=10,
        callback_permitted=True,
        collateral_delivered_before_debt=True,
        residual_debt_units=0,
        noncash_reward_units=999,
    )


@pytest.mark.parametrize(
    ("fn", "mechanism"),
    [
        (
            qualify_compound_stock,
            "compound-buy-collateral",
        ),
        (
            qualify_sky_callback,
            "sky-auction-callback",
        ),
        (
            qualify_morpho_preliq,
            "morpho-pre-liquidation",
        ),
    ],
)
def test_nf273_275_collateral_paths_close_real_debt(
    fn,
    mechanism,
) -> None:
    assert fn(collateral(mechanism)).admitted
    bad = replace(
        collateral(mechanism),
        residual_debt_units=1,
    )
    assert not fn(bad).admitted


def test_nf276_bold_basket_requires_every_component_exit() -> None:
    components = (
        BasketComponent(asset("C1"), 10, 80),
        BasketComponent(asset("C2"), 20, 50),
    )
    good = BasketEvidence(True, components, 100, 5, 5)
    assert qualify_bold_basket(good).admitted

    bad = replace(
        good,
        mandatory_components=(
            components[0],
            replace(
                components[1],
                executable_exit_base_units=None,
            ),
        ),
    )
    assert (
        "BASKET_COMPONENT_1_EXIT_UNKNOWN"
        in qualify_bold_basket(bad).blockers
    )


def test_nf277_eulerswap_checks_capacity_and_repayment() -> None:
    good = LendingAwareEvidence(
        True,
        True,
        True,
        100,
        120,
        150,
        100,
        10,
        0,
    )
    assert qualify_eulerswap(good).admitted

    bad = replace(
        good,
        requested_units=121,
        residual_debt_units=1,
    )
    decision = qualify_eulerswap(bad)
    assert "EULERSWAP_CAPACITY_EXCEEDED" in decision.blockers
    assert "EULERSWAP_REPAYMENT_BELOW_BORROW" in decision.blockers
    assert "EULERSWAP_RESIDUAL_DEBT" in decision.blockers

    underpaid = replace(good, repay_base_units=0)
    assert (
        "EULERSWAP_REPAYMENT_BELOW_BORROW"
        in qualify_eulerswap(underpaid).blockers
    )


def test_nf278_erc4626_preview_does_not_override_capacity() -> None:
    good = VaultEvidence(
        True,
        100,
        120,
        110,
        105,
        True,
        0,
        True,
        5,
        20,
    )
    assert qualify_erc4626(good).admitted

    bad = replace(
        good,
        synchronous=False,
        queue_delay_seconds=60,
        executable_redeem_assets=111,
    )
    decision = qualify_erc4626(bad)
    assert (
        "ERC4626_ASYNC_REDEEM_NOT_ATOMIC_EXIT"
        in decision.blockers
    )
    assert "ERC4626_REDEEM_EXCEEDS_CAPACITY" in decision.blockers


def test_nf279_directional_fee_requires_active_rule_and_state() -> None:
    good = DynamicFeeEvidence(
        True,
        True,
        "A->B",
        10,
        100,
        120,
        5,
        H1,
        H2,
    )
    assert qualify_stablesurge(good).admitted

    bad = replace(
        good,
        fee_rule_active=False,
        state_after_sha256=H1,
    )
    decision = qualify_stablesurge(bad)
    assert "DYNAMIC_FEE_RULE_INACTIVE" in decision.blockers
    assert (
        "DYNAMIC_FEE_STATE_TRANSITION_UNPROVEN"
        in decision.blockers
    )


def test_nf280_netting_savings_are_not_spread() -> None:
    good = NettingEvidence(
        True,
        True,
        20,
        50,
        5,
        (0, 0),
    )
    assert qualify_netting(good).admitted

    bad = replace(
        good,
        gross_external_spread_base_units=0,
    )
    assert (
        "NETTING_SAVINGS_ARE_NOT_SPREAD"
        in qualify_netting(bad).blockers
    )


def test_nf281_pendle_excludes_future_yield_from_atomic_net() -> None:
    good = PendleEvidence(
        True,
        1000,
        1000,
        1000,
        H1,
        True,
        True,
        20,
        10_000,
        5,
    )
    assert qualify_pendle(good).admitted

    bad = replace(
        good,
        atomic_surplus_base_units=0,
        future_yield_units=1_000_000,
    )
    assert (
        "PENDLE_ATOMIC_NET_NONPOSITIVE"
        in qualify_pendle(bad).blockers
    )


def test_nf282_flashmint_enforces_cap_capacity_and_burn() -> None:
    good = FlashMintEvidence(
        True,
        100,
        120,
        110,
        100,
        30,
        5,
        0,
    )
    assert qualify_flashmint_psm(good).admitted

    bad = replace(
        good,
        minted_units=121,
        returned_units=99,
        residual_debt_units=1,
    )
    decision = qualify_flashmint_psm(bad)
    assert "FLASHMINT_CAP_EXCEEDED" in decision.blockers
    assert "FLASHMINT_PSM_CAPACITY_EXCEEDED" in decision.blockers
    assert "FLASHMINT_NOT_FULLY_RETURNED" in decision.blockers


def test_nf283_llamma_requires_every_component_and_deployment() -> None:
    good = LlammaEvidence(
        True,
        H1,
        (
            BasketComponent(
                asset("LP-A"),
                10,
                80,
            ),
            BasketComponent(
                asset("LP-B"),
                10,
                60,
            ),
        ),
        100,
        10,
    )
    assert qualify_llamma(good).admitted

    bad = replace(
        good,
        collateral_components=(
            BasketComponent(
                asset("LP-A"),
                10,
                None,
            ),
        ),
    )
    assert (
        "LLAMMA_COMPONENT_0_EXIT_UNKNOWN"
        in qualify_llamma(bad).blockers
    )


def test_nf284_intent_validates_signature_expiry_and_costs() -> None:
    good = IntentEvidence(
        True,
        True,
        True,
        200,
        100,
        100,
        105,
        True,
        2,
        3,
        20,
        True,
    )
    assert qualify_intent_fill(good).admitted

    bad = replace(
        good,
        signature_valid=False,
        now_unix=200,
        user_out_units=99,
        onboarding_complete=False,
    )
    decision = qualify_intent_fill(bad)
    assert "INTENT_SIGNATURE_INVALID" in decision.blockers
    assert "INTENT_EXPIRED" in decision.blockers
    assert "INTENT_USER_MINIMUM_VIOLATED" in decision.blockers
    assert "INTENT_SOLVER_ONBOARDING_MISSING" in decision.blockers


def test_nf285_optin_backrun_requires_consent_and_safe_mev() -> None:
    good = OptInBackrunEvidence(
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        20,
        5,
    )
    assert qualify_optin_backrun(good).admitted

    bad = replace(
        good,
        relay_current=False,
        no_sandwich=False,
        no_oracle_manipulation=False,
    )
    decision = qualify_optin_backrun(bad)
    assert "BACKRUN_RELAY_NOT_CURRENT" in decision.blockers
    assert "BACKRUN_SANDWICH_FORBIDDEN" in decision.blockers
    assert (
        "BACKRUN_ORACLE_MANIPULATION_FORBIDDEN"
        in decision.blockers
    )


def test_nf286_sui_checks_object_versions_gas_and_repayment() -> None:
    legs = (
        leg(
            "SUI",
            "USDC",
            before=H1,
            after=H2,
            shared="0x1",
            dialect=ChainDialect.SUI,
            family="deepbook",
        ),
        leg(
            "USDC",
            "SUI",
            before=H2,
            after=H3,
            shared="0x1",
            dialect=ChainDialect.SUI,
            family="cetus",
        ),
    )
    transitions = (
        SuiObjectTransition(
            "0x1",
            1,
            2,
            1000,
            900,
        ),
        SuiObjectTransition(
            "0x1",
            2,
            3,
            900,
            850,
        ),
    )
    good = SuiCycleEvidence(
        True,
        legs,
        transitions,
        100,
        100,
        50,
        40,
        5,
        5,
    )
    assert qualify_sui_book(good).admitted

    bad = replace(
        good,
        object_transitions=(
            transitions[0],
            replace(
                transitions[1],
                before_version=4,
                liquidity_before=1000,
            ),
        ),
        returned_units=99,
        gas_budget_units=10,
    )
    decision = qualify_sui_book(bad)
    assert (
        "SUI_OBJECT_1_VERSION_CHAIN_BROKEN"
        in decision.blockers
    )
    assert "SUI_OBJECT_1_LIQUIDITY_RESET" in decision.blockers
    assert "SUI_BORROW_NOT_REPAID" in decision.blockers
    assert "SUI_GAS_NOT_FUNDED" in decision.blockers

    missing_objects = replace(good, object_transitions=())
    missing_decision = qualify_sui_book(missing_objects)
    assert "SUI_OBJECT_TRANSITIONS_MISSING" in missing_decision.blockers
    assert any(
        blocker.startswith("SUI_SHARED_RESOURCE_TRANSITION_MISSING:")
        for blocker in missing_decision.blockers
    )

    incomplete_objects = replace(
        good,
        object_transitions=(transitions[0],),
    )
    incomplete_decision = qualify_sui_book(incomplete_objects)
    assert (
        "SUI_SHARED_RESOURCE_TRANSITION_COUNT_MISMATCH"
        in incomplete_decision.blockers
    )
    assert (
        "SUI_SHARED_RESOURCE_TRANSITION_MISSING:1:0x1"
        in incomplete_decision.blockers
    )

    surplus_objects = replace(
        good,
        object_transitions=(
            transitions[0],
            transitions[1],
            SuiObjectTransition(
                "0x1",
                3,
                4,
                850,
                800,
            ),
        ),
    )
    surplus_decision = qualify_sui_book(surplus_objects)
    assert (
        "SUI_SHARED_RESOURCE_TRANSITION_COUNT_MISMATCH"
        in surplus_decision.blockers
    )

    losing = replace(
        good,
        route_legs=(
            legs[0],
            replace(legs[1], guaranteed_out=90),
        ),
        conservative_net_base_units=5,
    )
    losing_decision = qualify_sui_book(losing)
    assert "SUI_CLAIMED_NET_EXCEEDS_ROUTE_BOUND" in losing_decision.blockers
    assert "SUI_CONSERVATIVE_NET_NONPOSITIVE" in losing_decision.blockers


def test_nf287_sui_fee_chooses_best_net_not_highest_bid() -> None:
    low = GasBidOption(10, 5, 2, 30)
    high = GasBidOption(100, 25, 2, 35)
    choice = choose_sui_gas_option(
        (low, high),
        fee_rule_active=True,
        deployment_generation="g1",
        fee_rule_generation="g1",
    )
    assert choice.decision.admitted
    assert choice.option == low

    stale = choose_sui_gas_option(
        (low,),
        fee_rule_active=False,
        deployment_generation="g2",
        fee_rule_generation="g1",
    )
    assert stale.option is None
    assert "SUI_FEE_RULE_INACTIVE" in stale.decision.blockers
    assert (
        "SUI_FEE_RULE_GENERATION_STALE"
        in stale.decision.blockers
    )

    active_single = choose_sui_gas_option(
        (low,),
        fee_rule_active=True,
        deployment_generation="g1",
        fee_rule_generation="g1",
    )
    inactive_single = choose_sui_gas_option(
        (low,),
        fee_rule_active=False,
        deployment_generation="g1",
        fee_rule_generation="g1",
    )
    assert (
        active_single.decision.evidence_digest
        != inactive_single.decision.evidence_digest
    )


def test_every_admission_is_sender_free_and_digest_bound() -> None:
    decision = qualify_netting(
        NettingEvidence(
            True,
            True,
            20,
            1,
            5,
            (0,),
        )
    )
    assert decision.live_enabled is False
    assert len(decision.evidence_digest) == 64
