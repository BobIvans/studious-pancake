from __future__ import annotations

import dataclasses

import pytest

from src.market_economics_pr148 import (
    SPL_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    AssetPolicy,
    EconomicDecision,
    EconomicReason,
    ExactCostLedger,
    ExactMarketKernelInput,
    MarginFiStateEvidence,
    RouteQuoteEvidence,
    WalletLifecyclePolicy,
    evaluate_exact_market_candidate,
    logical_opportunity_id,
)


def _hash(label: str) -> str:
    return (label.encode("utf-8").hex() * 8)[:64]


def _quote(
    leg_id: str,
    *,
    input_mint: str,
    output_mint: str,
    exact_input_atoms: int,
    quoted_output_atoms: int,
    slot: int = 1_000,
) -> RouteQuoteEvidence:
    return RouteQuoteEvidence(
        provider="jupiter",
        leg_id=leg_id,
        input_mint=input_mint,
        output_mint=output_mint,
        exact_input_atoms=exact_input_atoms,
        quoted_output_atoms=quoted_output_atoms,
        request_hash=_hash(f"{leg_id}-request-{exact_input_atoms}"),
        response_hash=_hash(f"{leg_id}-response-{quoted_output_atoms}"),
        route_program_ids=("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",),
        slot=slot,
        expires_at_slot=1_050,
        provider_native_expiry_hash=_hash(f"{leg_id}-expiry"),
    )


def _asset(mint: str, *, token_program_id: str = SPL_TOKEN_PROGRAM_ID) -> AssetPolicy:
    return AssetPolicy(
        mint=mint,
        token_program_id=token_program_id,
        owner_verified=True,
        mint_authority_hash=_hash(f"{mint}-authority"),
        extension_policy_hash=_hash(f"{mint}-extensions"),
        account_size=165,
        rent_exempt_lamports=2_039_280,
    )


def _marginfi() -> MarginFiStateEvidence:
    return MarginFiStateEvidence(
        context_slot=1_000,
        root_slot=990,
        group_hash=_hash("group"),
        bank_hashes=(_hash("bank-sol"), _hash("bank-usdc")),
        oracle_hashes=(_hash("oracle-sol"), _hash("oracle-usdc")),
        vault_hashes=(_hash("vault-sol"), _hash("vault-usdc")),
        canonical_idl_hash=_hash("idl"),
        account_vectors_hash=_hash("accounts"),
        instruction_vectors_hash=_hash("instructions"),
        rpc_evidence_hash=_hash("rpc"),
        flashloan_fee_bps=5,
        flashloan_metas_verified=True,
        token_2022_paths_verified=True,
        human_reviewed=True,
        shadow_execution_capable=True,
    )


def _ledger() -> ExactCostLedger:
    principal = 1_000_000
    flash_fee = 500
    return ExactCostLedger(
        principal_atoms=principal,
        flash_fee_atoms=flash_fee,
        required_repayment_atoms=principal + flash_fee,
        gross_output_atoms=1_006_000,
        swap_fees_atoms=1_000,
        transfer_fees_atoms=100,
        slippage_atoms=250,
        uncertainty_atoms=150,
        network_fee_lamports=5_000,
        priority_fee_lamports=1_000,
        tip_lamports=2_000,
        rent_locked_lamports=2_039_280,
        rent_refunded_lamports=2_039_280,
        flash_fee_entries=1,
    )


def _input() -> ExactMarketKernelInput:
    sol = "So11111111111111111111111111111111111111112"
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    first = _quote(
        "first",
        input_mint=sol,
        output_mint=usdc,
        exact_input_atoms=1_000_000,
        quoted_output_atoms=1_002_000,
    )
    second = _quote(
        "second",
        input_mint=usdc,
        output_mint=sol,
        exact_input_atoms=1_002_000,
        quoted_output_atoms=1_006_000,
    )
    return ExactMarketKernelInput(
        strategy_id="circular-arb",
        policy_version="pr148-policy-v1",
        pair="SOL/USDC/SOL",
        first_leg=first,
        second_leg=second,
        marginfi=_marginfi(),
        input_asset=_asset(sol),
        intermediate_asset=_asset(usdc),
        output_asset=_asset(sol),
        lifecycle=WalletLifecyclePolicy(
            payer="payer11111111111111111111111111111111111111",
            taker="taker11111111111111111111111111111111111111",
            expected_ata_creations=1,
            rent_reserved_lamports=2_039_280,
            own_sol_debit_lamports=8_000,
            reserved_wallet_sol_lamports=20_000,
            jupiter_lifecycle_flags_hash=_hash("jupiter-flags"),
        ),
        ledger=_ledger(),
        current_slot=1_000,
        evidence_generation=7,
        min_profit_atoms=1,
    )


def test_pr148_accepts_exact_candidate_with_reviewed_evidence() -> None:
    report = evaluate_exact_market_candidate(_input())

    assert report.decision is EconomicDecision.EXACT_CANDIDATE
    assert report.candidate is not None
    assert report.candidate.conservative_profit_atoms == 4_000


def test_pr148_rejects_second_leg_not_bound_to_exact_first_output() -> None:
    data = _input()
    bad_second = dataclasses.replace(data.second_leg, exact_input_atoms=1_001_999)
    data = dataclasses.replace(data, second_leg=bad_second)

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert any(f.reason is EconomicReason.EXACT_AMOUNT_MISMATCH for f in report.failures)


def test_pr148_rejects_linear_projection_quote() -> None:
    data = _input()
    data = dataclasses.replace(
        data,
        second_leg=dataclasses.replace(data.second_leg, derived_from_linear_projection=True),
    )

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert any(f.reason is EconomicReason.LINEAR_PROJECTION_FORBIDDEN for f in report.failures)


def test_pr148_requires_route_program_identities() -> None:
    data = _input()
    data = dataclasses.replace(
        data,
        first_leg=dataclasses.replace(data.first_leg, route_program_ids=()),
    )

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert any(f.reason is EconomicReason.EMPTY_ROUTE_PROGRAMS for f in report.failures)


def test_pr148_rejects_expired_quote() -> None:
    data = dataclasses.replace(_input(), current_slot=1_100)

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert any(f.reason is EconomicReason.QUOTE_EXPIRED for f in report.failures)


def test_pr148_rejects_mixed_slot_marginfi_state() -> None:
    data = _input()
    data = dataclasses.replace(
        data,
        marginfi=dataclasses.replace(data.marginfi, context_slot=900, root_slot=990),
    )

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert any(f.reason is EconomicReason.MIXED_SLOT_STATE for f in report.failures)


def test_pr148_requires_reviewed_shadow_capable_marginfi() -> None:
    data = _input()
    data = dataclasses.replace(
        data,
        marginfi=dataclasses.replace(data.marginfi, human_reviewed=False),
    )

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert any(f.reason is EconomicReason.MARGINFI_UNREVIEWED for f in report.failures)


def test_pr148_rejects_unattested_mint() -> None:
    data = _input()
    data = dataclasses.replace(
        data,
        intermediate_asset=dataclasses.replace(data.intermediate_asset, owner_verified=False),
    )

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert any(f.reason is EconomicReason.ASSET_UNATTESTED for f in report.failures)


def test_pr148_rejects_unapproved_token_2022_transfer_hook() -> None:
    data = _input()
    token_2022 = dataclasses.replace(
        data.intermediate_asset,
        token_program_id=TOKEN_2022_PROGRAM_ID,
        transfer_hook_enabled=True,
        transfer_hook_policy_approved=False,
    )
    data = dataclasses.replace(data, intermediate_asset=token_2022)

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert any(f.reason is EconomicReason.TOKEN_2022_UNSUPPORTED for f in report.failures)


def test_pr148_rejects_unapproved_lst_asset() -> None:
    data = _input()
    lst = dataclasses.replace(data.input_asset, is_lst=True, lst_policy_approved=False)
    data = dataclasses.replace(data, input_asset=lst, output_asset=lst)

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert any(f.reason is EconomicReason.LST_UNAPPROVED for f in report.failures)


def test_pr148_flash_fee_must_match_marginfi_fee_and_be_once() -> None:
    data = _input()
    ledger = dataclasses.replace(data.ledger, flash_fee_entries=2)
    data = dataclasses.replace(data, ledger=ledger)

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert any(f.reason is EconomicReason.FLASH_FEE_DOUBLE_COUNTED for f in report.failures)


def test_pr148_requires_wallet_sol_and_ata_rent_reservation() -> None:
    data = _input()
    lifecycle = dataclasses.replace(
        data.lifecycle,
        rent_reserved_lamports=0,
        reserved_wallet_sol_lamports=1,
    )
    data = dataclasses.replace(data, lifecycle=lifecycle)

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert {failure.reason for failure in report.failures} >= {
        EconomicReason.ATA_RENT_UNRESERVED,
        EconomicReason.WALLET_SOL_UNRESERVED,
    }


def test_pr148_returns_no_trade_for_complete_but_low_profit_evidence() -> None:
    data = _input()
    ledger = dataclasses.replace(data.ledger, gross_output_atoms=1_002_200)
    second = dataclasses.replace(data.second_leg, quoted_output_atoms=1_002_200)
    data = dataclasses.replace(data, ledger=ledger, second_leg=second, min_profit_atoms=1_000)

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.NO_TRADE
    assert report.reason is EconomicReason.BELOW_MIN_PROFIT


def test_pr148_logical_id_is_deterministic_and_changes_with_quote_hash() -> None:
    first = _input()
    second = _input()

    assert logical_opportunity_id(first) == logical_opportunity_id(second)

    changed_quote = dataclasses.replace(
        first.first_leg,
        response_hash=_hash("changed-first-response"),
    )
    changed = dataclasses.replace(first, first_leg=changed_quote)

    assert logical_opportunity_id(first) != logical_opportunity_id(changed)


def test_pr148_duplicate_or_cooldown_logical_id_blocks() -> None:
    data = _input()
    logical_id = logical_opportunity_id(data)
    data = dataclasses.replace(data, seen_or_cooldown_logical_ids=(logical_id,))

    report = evaluate_exact_market_candidate(data)

    assert report.decision is EconomicDecision.BLOCKED
    assert any(f.reason is EconomicReason.DUPLICATE_OR_COOLDOWN for f in report.failures)


def test_pr148_binary_float_evidence_is_rejected() -> None:
    data = _input()
    assert data.ledger.swap_fees_atoms == 1_000
    with pytest.raises(TypeError):
        dataclasses.replace(data.ledger, swap_fees_atoms=1.5)  # type: ignore[arg-type]
