from __future__ import annotations

import pytest

from src.economics.capital import (
    AtomicCapitalLedger,
    CapitalCandidate,
    CapitalEngineError,
    CapitalPolicy,
    MessageFeeQuote,
    NativeCostBreakdown,
    NoTradeReason,
    lamports_from_sol_string,
)


def _policy() -> CapitalPolicy:
    return CapitalPolicy(
        protected_reserve_lamports=10_000_000,
        minimum_net_profit_lamports=100_000,
        maximum_priority_fee_lamports=1_000_000,
        maximum_jito_tip_lamports=1_000_000,
        maximum_peak_rent_lamports=8_000_000,
        contingency_lamports=500_000,
        maximum_flash_loan_lamports=2_000_000_000,
    )


def _candidate(
    candidate_id: str = "candidate-a",
    *,
    guaranteed_min_out_lamports: int = 1_020_000_000,
    flash_repayment_lamports: int = 1_000_000_000,
    requested_flash_loan_lamports: int = 1_000_000_000,
    base_network_fee_lamports: int = 5_000,
    priority_fee_lamports: int = 50_000,
    jito_tip_lamports: int = 0,
    peak_rent_lamports: int = 2_000_000,
    rent_loss_lamports: int = 0,
    protocol_fee_lamports: int = 0,
    slippage_buffer_lamports: int = 100_000,
    uncertainty_buffer_lamports: int = 100_000,
) -> CapitalCandidate:
    return CapitalCandidate(
        candidate_id=candidate_id,
        guaranteed_min_out_lamports=guaranteed_min_out_lamports,
        flash_repayment_lamports=flash_repayment_lamports,
        requested_flash_loan_lamports=requested_flash_loan_lamports,
        native_costs=NativeCostBreakdown(
            base_network_fee_lamports=base_network_fee_lamports,
            priority_fee_lamports=priority_fee_lamports,
            jito_tip_lamports=jito_tip_lamports,
            peak_rent_lamports=peak_rent_lamports,
            rent_loss_lamports=rent_loss_lamports,
        ),
        protocol_fee_lamports=protocol_fee_lamports,
        slippage_buffer_lamports=slippage_buffer_lamports,
        uncertainty_buffer_lamports=uncertainty_buffer_lamports,
        message_hash=f"hash-{candidate_id}",
    )


def test_0015_sol_is_not_fully_spendable_because_reserve_is_protected() -> None:
    wallet_lamports = lamports_from_sol_string("0.015")
    ledger = AtomicCapitalLedger(wallet_lamports=wallet_lamports, policy=_policy())

    candidate = _candidate(
        peak_rent_lamports=4_600_000,
        base_network_fee_lamports=5_000,
    )

    decision = ledger.reserve(candidate)

    assert wallet_lamports == 15_000_000
    assert decision.allowed is False
    assert decision.reason is NoTradeReason.INSUFFICIENT_NATIVE_BALANCE
    assert decision.available_native_lamports == 5_000_000
    assert decision.required_native_lamports == 5_155_000
    assert ledger.snapshot().active_reserved_lamports == 0


def test_profitable_candidate_reserves_then_release_is_idempotent() -> None:
    ledger = AtomicCapitalLedger(wallet_lamports=20_000_000, policy=_policy())

    decision = ledger.reserve(_candidate(peak_rent_lamports=2_000_000))

    assert decision.allowed is True
    assert decision.reason is NoTradeReason.TRADE_PERMITTED
    assert decision.reservation_id is not None
    assert ledger.snapshot().active_reserved_lamports == 2_555_000

    assert ledger.release(decision.reservation_id) is True
    assert ledger.release(decision.reservation_id) is False
    assert ledger.snapshot().active_reserved_lamports == 0


def test_two_candidates_cannot_reserve_the_same_available_balance() -> None:
    ledger = AtomicCapitalLedger(wallet_lamports=16_000_000, policy=_policy())

    first = ledger.reserve(_candidate("first", peak_rent_lamports=4_000_000))
    second = ledger.reserve(_candidate("second", peak_rent_lamports=4_000_000))

    assert first.allowed is True
    assert second.allowed is False
    assert second.reason is NoTradeReason.INSUFFICIENT_NATIVE_BALANCE
    assert ledger.snapshot().active_reserved_lamports == 4_555_000


def test_negative_or_uncertain_net_profit_is_rejected() -> None:
    ledger = AtomicCapitalLedger(wallet_lamports=50_000_000, policy=_policy())

    decision = ledger.evaluate(
        _candidate(
            guaranteed_min_out_lamports=1_000_180_000,
            flash_repayment_lamports=1_000_000_000,
            base_network_fee_lamports=5_000,
            priority_fee_lamports=50_000,
            slippage_buffer_lamports=100_000,
            uncertainty_buffer_lamports=100_000,
        )
    )

    assert decision.allowed is False
    assert decision.reason is NoTradeReason.NON_POSITIVE_CONSERVATIVE_NET_PROFIT
    assert decision.conservative_net_profit_lamports == -75_000


def test_positive_but_below_minimum_net_profit_is_rejected() -> None:
    ledger = AtomicCapitalLedger(wallet_lamports=50_000_000, policy=_policy())

    decision = ledger.evaluate(
        _candidate(
            guaranteed_min_out_lamports=1_000_360_000,
            flash_repayment_lamports=1_000_000_000,
            base_network_fee_lamports=5_000,
            priority_fee_lamports=50_000,
            slippage_buffer_lamports=100_000,
            uncertainty_buffer_lamports=100_000,
        )
    )

    assert decision.allowed is False
    assert decision.reason is NoTradeReason.BELOW_MINIMUM_NET_PROFIT
    assert decision.conservative_net_profit_lamports == 105_000


def test_fee_rent_tip_and_flash_size_policy_caps_fail_closed() -> None:
    ledger = AtomicCapitalLedger(wallet_lamports=100_000_000, policy=_policy())

    assert (
        ledger.evaluate(_candidate(priority_fee_lamports=1_000_001)).reason
        is NoTradeReason.PRIORITY_FEE_EXCEEDS_POLICY
    )
    assert (
        ledger.evaluate(_candidate(jito_tip_lamports=1_000_001)).reason
        is NoTradeReason.JITO_TIP_EXCEEDS_POLICY
    )
    assert (
        ledger.evaluate(_candidate(peak_rent_lamports=8_000_001)).reason
        is NoTradeReason.PEAK_RENT_EXCEEDS_POLICY
    )
    assert (
        ledger.evaluate(
            _candidate(requested_flash_loan_lamports=2_000_000_001)
        ).reason
        is NoTradeReason.FLASH_LOAN_SIZE_EXCEEDS_POLICY
    )


def test_get_fee_for_message_payload_is_integer_and_non_null() -> None:
    quote = MessageFeeQuote.from_rpc_payload(
        message_hash="abc",
        payload={"result": {"context": {"slot": 123}, "value": 5000}},
    )

    costs = NativeCostBreakdown.from_message_fee(
        quote,
        priority_fee_lamports=10,
        peak_rent_lamports=20,
    )

    assert quote.source == "getFeeForMessage"
    assert quote.context_slot == 123
    assert costs.required_wallet_lamports(_policy()) == 505_030

    with pytest.raises(CapitalEngineError, match="null fee"):
        MessageFeeQuote.from_rpc_payload(
            message_hash="abc",
            payload={"result": {"value": None}},
        )


def test_integer_only_inputs_reject_binary_float_money() -> None:
    with pytest.raises(CapitalEngineError, match="integer lamports"):
        NativeCostBreakdown(base_network_fee_lamports=5_000.0)  # type: ignore[arg-type]

    with pytest.raises(CapitalEngineError, match="more than 9 decimal"):
        lamports_from_sol_string("0.0000000001")


def test_choose_best_candidate_prefers_highest_conservative_net() -> None:
    ledger = AtomicCapitalLedger(wallet_lamports=100_000_000, policy=_policy())

    decision = ledger.choose_best_candidate(
        [
            _candidate("small", guaranteed_min_out_lamports=1_020_000_000),
            _candidate("large", guaranteed_min_out_lamports=1_030_000_000),
        ]
    )

    assert decision.allowed is True
    assert decision.candidate_id == "large"
    assert decision.reservation_id is None
