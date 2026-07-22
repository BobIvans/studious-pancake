from __future__ import annotations

import pytest

from src.execution.compute_budget_finalization import (
    ComputeBudgetFinalizationCode,
    ComputeBudgetFinalizationError,
    FinalObservation,
    PriorityFeeObservation,
    assert_single_compute_budget_variants,
    build_compute_budget_instructions,
    finalize_compute_budget_policy,
    validate_final_observation,
)


def _fee_observations() -> tuple[PriorityFeeObservation, ...]:
    return (
        PriorityFeeObservation(
            slot=40,
            micro_lamports_per_cu=10,
            writable_accounts=("payer", "amm"),
            endpoint_id="rpc-a",
        ),
        PriorityFeeObservation(
            slot=41,
            micro_lamports_per_cu=20,
            writable_accounts=("payer", "amm"),
            endpoint_id="rpc-a",
        ),
        PriorityFeeObservation(
            slot=42,
            micro_lamports_per_cu=30,
            writable_accounts=("payer", "amm"),
            endpoint_id="rpc-a",
        ),
    )


def test_pr128_builds_explicit_compute_budget_instruction_set() -> None:
    policy = finalize_compute_budget_policy(
        observed_units_consumed=200_000,
        observed_loaded_accounts_data_size=1_024,
        priority_fee_observations=_fee_observations(),
        min_context_slot=40,
        expected_network_fee_lamports=5_000,
        tip_lamports=1_000,
        max_total_landing_cost_lamports=6_000,
    )

    assert policy.unit_limit == 240_000
    assert policy.loaded_accounts_data_size_limit == 1_229
    assert policy.micro_lamports_per_cu == 30
    assert policy.priority_fee_slot == 42
    assert policy.total_landing_cost_lamports == 6_000

    instructions = build_compute_budget_instructions(policy)

    assert tuple(instruction.data[0] for instruction in instructions) == (2, 3, 4)
    assert_single_compute_budget_variants(instructions)


def test_pr128_duplicate_compute_budget_variant_is_rejected() -> None:
    policy = finalize_compute_budget_policy(
        observed_units_consumed=100,
        observed_loaded_accounts_data_size=100,
        priority_fee_observations=_fee_observations(),
        min_context_slot=40,
        expected_network_fee_lamports=0,
    )
    instructions = build_compute_budget_instructions(policy)

    with pytest.raises(ComputeBudgetFinalizationError) as exc_info:
        assert_single_compute_budget_variants((*instructions, instructions[0]))

    assert exc_info.value.code is ComputeBudgetFinalizationCode.COMPUTE_BUDGET_DUPLICATE


def test_pr128_loaded_account_data_observation_is_required() -> None:
    with pytest.raises(ComputeBudgetFinalizationError) as exc_info:
        finalize_compute_budget_policy(
            observed_units_consumed=200_000,
            observed_loaded_accounts_data_size=None,
            priority_fee_observations=_fee_observations(),
            min_context_slot=40,
            expected_network_fee_lamports=5_000,
        )

    assert exc_info.value.code is (
        ComputeBudgetFinalizationCode.LOADED_ACCOUNT_DATA_UNAVAILABLE
    )


def test_pr128_stale_or_missing_priority_fee_evidence_fails_closed() -> None:
    with pytest.raises(ComputeBudgetFinalizationError) as missing:
        finalize_compute_budget_policy(
            observed_units_consumed=200_000,
            observed_loaded_accounts_data_size=1_024,
            priority_fee_observations=(),
            min_context_slot=40,
            expected_network_fee_lamports=5_000,
        )
    assert missing.value.code is (
        ComputeBudgetFinalizationCode.PRIORITY_FEE_EVIDENCE_UNAVAILABLE
    )

    with pytest.raises(ComputeBudgetFinalizationError) as stale:
        finalize_compute_budget_policy(
            observed_units_consumed=200_000,
            observed_loaded_accounts_data_size=1_024,
            priority_fee_observations=_fee_observations(),
            min_context_slot=50,
            expected_network_fee_lamports=5_000,
        )
    assert stale.value.code is ComputeBudgetFinalizationCode.PRIORITY_FEE_EVIDENCE_STALE


def test_pr128_priority_fee_and_landing_cost_caps_create_no_trade() -> None:
    with pytest.raises(ComputeBudgetFinalizationError) as fee_cap:
        finalize_compute_budget_policy(
            observed_units_consumed=200_000,
            observed_loaded_accounts_data_size=1_024,
            priority_fee_observations=_fee_observations(),
            min_context_slot=40,
            expected_network_fee_lamports=5_000,
            max_micro_lamports_per_cu=15,
        )
    assert fee_cap.value.code is ComputeBudgetFinalizationCode.PRIORITY_FEE_CAP_EXCEEDED

    with pytest.raises(ComputeBudgetFinalizationError) as landing_cap:
        finalize_compute_budget_policy(
            observed_units_consumed=200_000,
            observed_loaded_accounts_data_size=1_024,
            priority_fee_observations=_fee_observations(),
            min_context_slot=40,
            expected_network_fee_lamports=5_000,
            tip_lamports=1_001,
            max_total_landing_cost_lamports=6_000,
        )
    assert landing_cap.value.code is (
        ComputeBudgetFinalizationCode.LANDING_COST_CAP_EXCEEDED
    )


def test_pr128_final_observation_must_match_approved_policy() -> None:
    policy = finalize_compute_budget_policy(
        observed_units_consumed=200_000,
        observed_loaded_accounts_data_size=1_024,
        priority_fee_observations=_fee_observations(),
        min_context_slot=40,
        expected_network_fee_lamports=5_000,
        tip_lamports=1_000,
        max_total_landing_cost_lamports=6_000,
    )

    validate_final_observation(
        policy,
        FinalObservation(
            units_consumed=210_000,
            loaded_accounts_data_size=1_200,
            network_fee_lamports=5_000,
        ),
    )

    for observation in (
        FinalObservation(
            units_consumed=240_001,
            loaded_accounts_data_size=1_200,
            network_fee_lamports=5_000,
        ),
        FinalObservation(
            units_consumed=210_000,
            loaded_accounts_data_size=1_230,
            network_fee_lamports=5_000,
        ),
        FinalObservation(
            units_consumed=210_000,
            loaded_accounts_data_size=1_200,
            network_fee_lamports=5_001,
        ),
    ):
        with pytest.raises(ComputeBudgetFinalizationError) as exc_info:
            validate_final_observation(policy, observation)
        assert exc_info.value.code is (
            ComputeBudgetFinalizationCode.FINAL_OBSERVATION_MISMATCH
        )
