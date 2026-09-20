from __future__ import annotations

from src.execution.finalized_economic_ledger import (
    SOL_ASSET_ID,
    AttemptEconomicLineage,
    EconomicPosting,
    FinalizedEconomicInput,
    FinalizedEconomicOutcome,
    PostingKind,
    classify_finalized_economics,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64
SIGNATURE = "5" * 88


def _lineage() -> AttemptEconomicLineage:
    return AttemptEconomicLineage(
        attempt_id="attempt-2610",
        attempt_generation=1,
        message_hash=HASH_A,
        signed_transaction_digest=HASH_B,
        primary_signature=SIGNATURE,
        finalized_slot=123_456,
        release_hash=HASH_C,
        config_hash=HASH_D,
        policy_hash=HASH_E,
        cluster_genesis_hash=HASH_F,
        raw_evidence_hash=HASH_A,
    )


def _posting(
    posting_id: str,
    asset_id: str,
    amount: int,
    kind: PostingKind,
) -> EconomicPosting:
    return EconomicPosting(
        posting_id=posting_id,
        asset_id=asset_id,
        base_units=amount,
        kind=kind,
        account_scope="strategy-wallet",
        evidence_hash=HASH_B,
    )


def _input(*postings: EconomicPosting, **overrides: object) -> FinalizedEconomicInput:
    values: dict[str, object] = {
        "lineage": _lineage(),
        "confirmation_status": "finalized",
        "meta_err": None,
        "marginfi_repayment_proven": True,
        "economics_complete": True,
        "postings": tuple(postings),
    }
    values.update(overrides)
    return FinalizedEconomicInput(**values)  # type: ignore[arg-type]


def test_mpr2610_positive_single_asset_is_realized_profit() -> None:
    result = classify_finalized_economics(
        _input(_posting("p1", "spl:USDC:6", 25_000, PostingKind.STRATEGY_ASSET_DELTA))
    )

    assert result.outcome is FinalizedEconomicOutcome.FINALIZED_REALIZED_PROFIT
    assert result.economically_successful is True
    assert result.per_asset_delta == (("spl:USDC:6", 25_000),)


def test_mpr2610_negative_and_zero_are_not_profitable() -> None:
    loss = classify_finalized_economics(
        _input(_posting("p1", "spl:USDC:6", -1, PostingKind.STRATEGY_ASSET_DELTA))
    )
    zero = classify_finalized_economics(
        _input(_posting("p2", "spl:USDC:6", 0, PostingKind.STRATEGY_ASSET_DELTA))
    )

    assert loss.outcome is FinalizedEconomicOutcome.FINALIZED_REALIZED_LOSS
    assert zero.outcome is FinalizedEconomicOutcome.FINALIZED_REALIZED_BREAK_EVEN
    assert loss.economically_successful is False
    assert zero.economically_successful is False


def test_mpr2610_incomplete_economics_never_becomes_realized() -> None:
    result = classify_finalized_economics(
        _input(
            _posting("p1", "spl:USDC:6", 25_000, PostingKind.STRATEGY_ASSET_DELTA),
            economics_complete=False,
        )
    )

    assert result.outcome is FinalizedEconomicOutcome.FINALIZED_PENDING_ECONOMICS
    assert result.economically_successful is False


def test_mpr2610_finalized_meta_error_books_failure_not_profit() -> None:
    result = classify_finalized_economics(
        _input(
            _posting("fee", SOL_ASSET_ID, -5_000, PostingKind.NETWORK_FEE),
            meta_err={"InstructionError": [0, "Custom"]},
            payer_pre_lamports=1_000_000,
            payer_post_lamports=995_000,
            meta_fee_lamports=5_000,
        )
    )

    assert result.outcome is FinalizedEconomicOutcome.FINALIZED_FAILURE_COSTED
    assert result.economically_successful is False
    assert result.per_asset_delta == ((SOL_ASSET_ID, -5_000),)


def test_mpr2610_cross_asset_result_requires_valuation_before_profit_claim() -> None:
    result = classify_finalized_economics(
        _input(
            _posting("gain", "spl:USDC:6", 30_000, PostingKind.STRATEGY_ASSET_DELTA),
            _posting("fee", SOL_ASSET_ID, -5_000, PostingKind.NETWORK_FEE),
        )
    )

    assert result.outcome is FinalizedEconomicOutcome.FINALIZED_REALIZED_PARTIAL
    assert result.economically_successful is False
    assert "CROSS_ASSET_VALUATION_REQUIRED" in result.blockers


def test_mpr2610_funding_and_sweep_are_not_strategy_pnl() -> None:
    result = classify_finalized_economics(
        _input(
            _posting("fund", "spl:USDC:6", 1_000_000, PostingKind.FUNDING),
            _posting("trade", "spl:USDC:6", -10, PostingKind.STRATEGY_ASSET_DELTA),
        )
    )

    assert result.per_asset_delta == (("spl:USDC:6", -10),)
    assert result.outcome is FinalizedEconomicOutcome.FINALIZED_REALIZED_LOSS


def test_mpr2610_payer_conservation_mismatch_quarantines() -> None:
    result = classify_finalized_economics(
        _input(
            _posting("fee", SOL_ASSET_ID, -5_000, PostingKind.NETWORK_FEE),
            payer_pre_lamports=1_000_000,
            payer_post_lamports=994_999,
            meta_fee_lamports=5_000,
        )
    )

    assert result.outcome is FinalizedEconomicOutcome.UNKNOWN_QUARANTINED
    assert result.economically_successful is False
    assert "PAYER_NATIVE_CONSERVATION_MISMATCH" in result.blockers


def test_mpr2610_meta_fee_is_total_and_not_double_counted() -> None:
    result = classify_finalized_economics(
        _input(
            _posting("fee", SOL_ASSET_ID, -5_000, PostingKind.NETWORK_FEE),
            payer_pre_lamports=1_000_000,
            payer_post_lamports=995_000,
            meta_fee_lamports=5_000,
        )
    )

    assert result.outcome is FinalizedEconomicOutcome.FINALIZED_REALIZED_LOSS
    assert result.per_asset_delta == ((SOL_ASSET_ID, -5_000),)


def test_mpr2610_nonfinalized_and_unproven_repayment_quarantine() -> None:
    result = classify_finalized_economics(
        _input(
            _posting("p1", "spl:USDC:6", 1, PostingKind.STRATEGY_ASSET_DELTA),
            confirmation_status="confirmed",
            marginfi_repayment_proven=False,
        )
    )

    assert result.outcome is FinalizedEconomicOutcome.UNKNOWN_QUARANTINED
    assert set(result.blockers) == {
        "FINALIZED_EVIDENCE_REQUIRED",
        "MARGINFI_REPAYMENT_NOT_PROVEN",
    }


def test_mpr2610_reordered_postings_replay_to_same_ledger_hash() -> None:
    fee = _posting("a-fee", SOL_ASSET_ID, -5_000, PostingKind.NETWORK_FEE)
    gain = _posting("b-gain", "spl:USDC:6", 30_000, PostingKind.STRATEGY_ASSET_DELTA)

    first = classify_finalized_economics(_input(fee, gain))
    replay = classify_finalized_economics(_input(gain, fee))

    assert first.outcome is FinalizedEconomicOutcome.FINALIZED_REALIZED_PARTIAL
    assert replay.outcome is first.outcome
    assert replay.per_asset_delta == first.per_asset_delta
    assert replay.ledger_hash == first.ledger_hash
