from dataclasses import replace

from src.mpr2621_lst_atomic_exit import (
    AcquisitionProof,
    CandidateLimits,
    CostProof,
    Decision,
    ExitProof,
    LstAtomicExitCandidate,
    LstCapability,
    Mechanism,
    NavState,
    SCHEMA_VERSION,
    ShadowEvidence,
    capability_digest,
    qualify_candidate,
    qualify_shadow,
)

H = "a" * 64
R = "b" * 64
M = "Lst111111111111111111111111111111111111111"


def capability(**overrides):
    value = LstCapability(
        capability_id="lst:test:gen1",
        mint=M,
        token_program="Tokenkeg",
        decimals=9,
        staking_protocol="qualified-test-protocol",
        pool_program="Pool111",
        pool_generation="gen1",
        mechanism=Mechanism.STAKEDEX_WITHDRAW_SOL,
        cluster="mainnet-beta",
        genesis_hash="genesis",
        evidence_hash=H,
        status="reviewed_executable",
        route_program_ids=("Pool111",),
        route_account_hash=R,
        source_pins=("stakedex-sdk@reviewed", "jupiter-contract@reviewed"),
    )
    return replace(value, **overrides)


def candidate(**overrides):
    cap = overrides.pop("capability", capability())
    value = LstAtomicExitCandidate(
        schema_version=SCHEMA_VERSION,
        candidate_id="cand-1",
        capability=cap,
        nav=NavState(
            epoch=900,
            rooted_slot=123456,
            update_generation="gen1",
            numerator_lamports=1_050_000_000,
            denominator_atomic_lst=1_000_000_000,
            liquid_sol_capacity_lamports=2_000_000_000,
            state_hash=H,
            fresh=True,
            complete=True,
        ),
        acquisition=AcquisitionProof(
            provider="governed-jupiter",
            input_sol_lamports=1_000_000_000,
            guaranteed_lst_out_atomic=1_000_000_000,
            route_program_ids=("Dex111",),
            route_account_hash=H,
            request_id="req-1",
            deadline_ms=250,
        ),
        exit=ExitProof(
            provider="governed-stakedex",
            mechanism=cap.mechanism,
            lst_in_atomic=1_000_000_000,
            guaranteed_active_sol_out_lamports=1_020_000_000,
            same_transaction=True,
            route_program_ids=cap.route_program_ids,
            route_account_hash=cap.route_account_hash,
            immediate_liquidity_lamports=2_000_000_000,
        ),
        costs=CostProof(1_000_000, 1_000_000, 1_000_000, 5_000, 5_000, 0, 0, 100_000),
        limits=CandidateLimits(
            lender_capacity_lamports=2_000_000_000,
            acquisition_capacity_lamports=2_000_000_000,
            exit_capacity_lamports=2_000_000_000,
            strategy_cap_lamports=1_500_000_000,
            wallet_cost_reserve_lamports=10_000_000,
            max_message_accounts=64,
            message_accounts=24,
        ),
        flash_repayment_lamports=1_001_000_000,
        minimum_surplus_lamports=1_000_000,
        expected_profit_lamports=999_999_999,
        final_message_hash=H,
        final_simulation_hash=R,
        simulation_success=True,
        decoded_acquired_lst_atomic=1_000_000_000,
        decoded_consumed_lst_atomic=1_000_000_000,
        decoded_returned_sol_lamports=1_020_000_000,
        decoded_flash_repaid_lamports=1_001_000_000,
        residual_assets={M: 0, "WSOL": 0},
    )
    return replace(value, **overrides)


def blockers(value):
    return set(qualify_candidate(value).blockers)


def test_t01_2620_is_not_an_execution_dependency():
    result = qualify_candidate(candidate())
    assert result.decision is Decision.QUALIFIED_SENDER_FREE


def test_t02_sender_signer_and_live_are_always_false():
    result = qualify_candidate(candidate())
    assert (result.sender_allowed, result.signer_allowed, result.live_enabled) == (False, False, False)


def test_t03_bool_or_float_money_cannot_enter_canonical_costs():
    bad = candidate(costs=replace(candidate().costs, lender_fee_lamports=True))
    assert "COST" in blockers(bad)


def test_t04_candidate_policy_is_immutable_frozen_data():
    value = candidate()
    try:
        value.retry_generation = 2
    except Exception:
        pass
    else:
        raise AssertionError("candidate must be immutable")


def test_t05_unknown_or_revoked_capability_rejects():
    assert "LST_CAPABILITY_NOT_REVIEWED_EXECUTABLE" in blockers(
        candidate(capability=capability(status="revoked"))
    )


def test_t06_unmodeled_token2022_extensions_reject():
    cap = capability(token2022_extensions=("transfer-fee",), transfer_fee_modeled=False)
    assert "TOKEN2022_EXTENSION_UNMODELED" in blockers(candidate(capability=cap))


def test_t07_nav_uses_exact_rational_math():
    result = qualify_candidate(candidate())
    assert result.nav_lamports_per_lst_atomic_num == 21
    assert result.nav_lamports_per_lst_atomic_den == 20


def test_t08_stale_or_incomplete_nav_rejects():
    for nav in (
        replace(candidate().nav, fresh=False),
        replace(candidate().nav, complete=False),
    ):
        assert qualify_candidate(replace(candidate(), nav=nav)).decision is Decision.BLOCKED


def test_t09_delayed_stake_deactivation_is_never_atomic_exit():
    cap = capability(mechanism=Mechanism.STAKE_ACCOUNT_DEACTIVATION)
    bad = candidate(capability=cap, exit=replace(candidate().exit, mechanism=Mechanism.STAKE_ACCOUNT_DEACTIVATION))
    assert "MECHANISM_NOT_IMMEDIATE_ACTIVE_SOL_EXIT" in blockers(bad)


def test_t10_insufficient_immediate_sol_liquidity_is_no_trade_or_blocked():
    bad_exit = replace(candidate().exit, immediate_liquidity_lamports=1)
    assert "EXIT_LIQUIDITY_INSUFFICIENT" in blockers(replace(candidate(), exit=bad_exit))


def test_t11_cost_components_are_counted_once_and_integer_only():
    result = qualify_candidate(candidate())
    expected = 1_020_000_000 - 1_001_000_000 - candidate().costs.total()
    assert result.guaranteed_surplus_lamports == expected


def test_t12_sizing_is_bounded_by_minimum_capacity():
    limits = replace(candidate().limits, lender_capacity_lamports=999_999_999)
    assert "BORROW_EXCEEDS_HARD_CAPACITY" in blockers(replace(candidate(), limits=limits))


def test_t13_exit_cannot_consume_more_lst_than_guaranteed_acquisition():
    exit_proof = replace(candidate().exit, lst_in_atomic=1_000_000_001)
    assert "EXIT_CONSUMES_UNGUARANTEED_LST" in blockers(replace(candidate(), exit=exit_proof))


def test_t14_premium_mint_direction_stays_disabled():
    assert "PREMIUM_MINT_DIRECTION_DISABLED" in blockers(candidate(premium_direction_requested=True))


def test_t15_lst_to_lst_does_not_inherit_sol_exit_capability():
    cap = capability(mechanism=Mechanism.LST_TO_LST_POOL_SWAP)
    bad = candidate(capability=cap, exit=replace(candidate().exit, mechanism=Mechanism.LST_TO_LST_POOL_SWAP))
    assert "MECHANISM_NOT_IMMEDIATE_ACTIVE_SOL_EXIT" in blockers(bad)


def test_t16_route_label_cannot_replace_program_and_account_binding():
    bad_exit = replace(candidate().exit, provider="Sanctum", route_account_hash=H)
    assert "EXIT_ROUTE_AUTHORITY_MISMATCH" in blockers(replace(candidate(), exit=bad_exit))


def test_t17_capability_digest_binds_source_and_route_identity():
    first = capability_digest(capability())
    second = capability_digest(capability(route_program_ids=("Other",)))
    assert first != second


def test_t18_provider_request_requires_identity_and_deadline():
    bad_acq = replace(candidate().acquisition, request_id="", deadline_ms=0)
    assert "PROVIDER_REQUEST_ID_OR_DEADLINE_INVALID" in blockers(replace(candidate(), acquisition=bad_acq))


def test_t19_authority_module_has_no_network_or_keypair_dependency():
    import inspect
    import src.mpr2621_lst_atomic_exit as module

    source = inspect.getsource(module)
    for forbidden in ("aiohttp", "requests.", "Keypair", "sendTransaction", "send_bundle"):
        assert forbidden not in source


def test_t20_fee_double_count_regression_uses_explicit_components():
    costs = candidate().costs
    assert costs.total() == 3_110_000


def test_t21_residual_assets_are_per_asset_not_summed():
    good = candidate(residual_assets={M: 5, "WSOL": 7})
    assert qualify_candidate(good).decision is Decision.QUALIFIED_SENDER_FREE


def test_t22_message_account_limit_fails_closed():
    limits = replace(candidate().limits, message_accounts=65)
    assert "MESSAGE_ACCOUNT_LIMIT_EXCEEDED" in blockers(replace(candidate(), limits=limits))


def test_t23_simulation_must_prove_all_acquisition_exit_and_repayment_deltas():
    bad = candidate(decoded_flash_repaid_lamports=None)
    assert "SIMULATION_ACCOUNT_DELTAS_INCOMPLETE" in blockers(bad)


def test_t24_caller_expected_profit_is_not_economic_authority():
    good = candidate(expected_profit_lamports=-999_999_999)
    assert qualify_candidate(good).decision is Decision.QUALIFIED_SENDER_FREE
    bad = candidate(decoded_returned_sol_lamports=0)
    assert qualify_candidate(bad).decision is Decision.BLOCKED


def test_t25_post_effect_recursive_retry_is_forbidden():
    bad = candidate(effect_issued_or_unknown=True, retry_generation=2)
    assert "POST_EFFECT_RETRY_FORBIDDEN" in blockers(bad)


def test_t26_message_bounds_protect_downstream_resources():
    limits = replace(candidate().limits, max_message_accounts=32, message_accounts=33)
    assert qualify_candidate(replace(candidate(), limits=limits)).decision is Decision.BLOCKED


def test_t27_shadow_is_bound_to_exact_lst_capability():
    shadow = ShadowEvidence("other", M, True, False, 3600, 1, "gen1")
    ok, codes = qualify_shadow(capability(), shadow)
    assert not ok and "SHADOW_CAPABILITY_IDENTITY_MISMATCH" in codes


def test_t28_epoch_transition_required_for_shadow_qualification():
    shadow = ShadowEvidence("lst:test:gen1", M, True, False, 3600, 0, "gen1")
    ok, codes = qualify_shadow(capability(), shadow)
    assert not ok and "EPOCH_TRANSITION_NOT_OBSERVED" in codes


def test_t29_module_is_sender_free_and_does_not_import_legacy_lst_executor():
    import inspect
    import src.mpr2621_lst_atomic_exit as module

    source = inspect.getsource(module)
    assert "lst_unstake_arbitrage" not in source
    assert "lst_route_aggregator" not in source


def test_t30_complete_sender_free_staged_candidate_qualifies_without_canary():
    result = qualify_candidate(candidate())
    assert result.decision is Decision.QUALIFIED_SENDER_FREE
    assert result.canary_eligible is False
