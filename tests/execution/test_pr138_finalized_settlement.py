from __future__ import annotations

from typing import Any, cast

import pytest

from src.execution.finalized_settlement_pr138 import (
    FinalizedTransactionEvidence,
    PR138SettlementError,
    SettlementOutcome,
    SettlementPhase,
    assert_economic_success_requires_finalized_actual,
    classify_finalized_actual_settlement,
    classify_transaction_status_observation,
)
from src.execution.models import ExecutionState

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
SIGNATURE = "5" * 88


def _evidence(**overrides: object) -> FinalizedTransactionEvidence:
    values: dict[str, object] = {
        "signature": SIGNATURE,
        "confirmation_status": "finalized",
        "transaction_message_hash": HASH_A,
        "finalized_slot": 123_456,
        "raw_transaction_hash": HASH_B,
        "meta_err": None,
        "fee_lamports": 5_000,
        "pre_balances_hash": HASH_C,
        "post_balances_hash": HASH_C,
        "pre_token_balances_hash": HASH_C,
        "post_token_balances_hash": HASH_C,
        "loaded_addresses_hash": HASH_C,
        "inner_instructions_hash": HASH_C,
        "logs_hash": HASH_C,
        "return_data_hash": None,
        "compute_units_consumed": 300_000,
        "marginfi_repayment_proven": True,
        "actual_network_fee_lamports": 5_000,
        "actual_priority_fee_lamports": 120,
        "actual_tip_lamports": 0,
        "actual_rent_lamports": 0,
        "actual_token_transfer_fee_lamports": 0,
        "finalized_account_state_hash": HASH_C,
    }
    values.update(overrides)
    kwargs = cast(dict[str, Any], values)
    return FinalizedTransactionEvidence(**kwargs)


@pytest.mark.parametrize("status", ["processed", "confirmed", "finalized"])
def test_pr138_status_observation_is_never_economic_success(status: str) -> None:
    decision = classify_transaction_status_observation(
        signature=SIGNATURE,
        message_hash=HASH_A,
        confirmation_status=status,
        transport_status="jito_bundle_landed",
    )

    assert decision.economically_successful is False
    assert decision.outcome == SettlementOutcome.PENDING
    assert decision.evidence_hash is None
    assert "FINALIZED_ACTUAL_SETTLEMENT_REQUIRED" in decision.blockers
    assert "transport status is not economic settlement proof" in decision.warnings
    if status == "processed":
        assert decision.phase == SettlementPhase.PROCESSED
        assert decision.durable_state is ExecutionState.PENDING
    elif status == "confirmed":
        assert decision.phase == SettlementPhase.CONFIRMED
        assert decision.durable_state is ExecutionState.RECONCILING
    else:
        assert decision.phase == SettlementPhase.FINALIZED
        assert decision.durable_state is ExecutionState.RECONCILING


@pytest.mark.parametrize("status", [None, "", "dropped"])
def test_pr138_unknown_status_latches_manual_review(status: str | None) -> None:
    decision = classify_transaction_status_observation(
        signature=SIGNATURE,
        message_hash=HASH_A,
        confirmation_status=status,
    )

    assert decision.outcome == SettlementOutcome.INDETERMINATE_MANUAL_REVIEW
    assert decision.durable_state is ExecutionState.AMBIGUOUS_MANUAL_REVIEW
    assert decision.economically_successful is False


def test_pr138_finalized_actual_success_requires_identity_and_repayment() -> None:
    decision = classify_finalized_actual_settlement(
        _evidence(),
        expected_message_hash=HASH_A,
        expected_signature=SIGNATURE,
    )

    assert decision.phase == SettlementPhase.RECONCILED
    assert decision.outcome == SettlementOutcome.RECONCILED_SUCCESS
    assert decision.durable_state is ExecutionState.RECONCILED_SUCCESS
    assert decision.economically_successful is True
    assert decision.evidence_hash is not None
    assert decision.blockers == ()
    assert_economic_success_requires_finalized_actual(decision)


def test_pr138_finalized_meta_error_is_reconciled_failure_not_success() -> None:
    decision = classify_finalized_actual_settlement(
        _evidence(meta_err={"InstructionError": [0, "Custom"]}),
        expected_message_hash=HASH_A,
    )

    assert decision.phase == SettlementPhase.RECONCILED
    assert decision.outcome == SettlementOutcome.RECONCILED_FAILURE
    assert decision.durable_state is ExecutionState.RECONCILED_FAILURE
    assert decision.economically_successful is False
    assert "FINALIZED_TRANSACTION_META_ERR" in decision.blockers


@pytest.mark.parametrize(
    ("overrides", "blocker"),
    [
        ({"confirmation_status": "confirmed"}, "FINALIZED_GET_TRANSACTION_REQUIRED"),
        ({"transaction_message_hash": "d" * 64}, "MESSAGE_HASH_MISMATCH"),
        ({"marginfi_repayment_proven": False}, "MARGINFI_REPAYMENT_NOT_PROVEN"),
        ({"signature": "6" * 88}, "SIGNATURE_MISMATCH"),
    ],
)
def test_pr138_conflicting_or_incomplete_actuals_latch_manual_review(
    overrides: dict[str, object],
    blocker: str,
) -> None:
    decision = classify_finalized_actual_settlement(
        _evidence(**overrides),
        expected_message_hash=HASH_A,
        expected_signature=SIGNATURE,
    )

    assert decision.phase == SettlementPhase.INDETERMINATE_MANUAL_REVIEW
    assert decision.outcome == SettlementOutcome.INDETERMINATE_MANUAL_REVIEW
    assert decision.durable_state is ExecutionState.AMBIGUOUS_MANUAL_REVIEW
    assert decision.economically_successful is False
    assert blocker in decision.blockers
    assert decision.evidence_hash is not None


def test_pr138_malformed_evidence_rejects_before_classification() -> None:
    with pytest.raises(PR138SettlementError, match="fee_lamports"):
        classify_finalized_actual_settlement(
            _evidence(fee_lamports=-1),
            expected_message_hash=HASH_A,
        )
