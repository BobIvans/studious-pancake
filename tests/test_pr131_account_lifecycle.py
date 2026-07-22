from __future__ import annotations

import pytest
from solders.pubkey import Pubkey

from src.account_lifecycle_pr131 import (
    NATIVE_SOL_MINT,
    SPL_TOKEN_PROGRAM_ID,
    TOKEN_ACCOUNT_BASE_DATA_SIZE,
    AccountLifecycleError,
    AccountLifecycleReason,
    AssociatedTokenAccountEvidence,
    AssociatedTokenAccountPolicy,
    CleanupPolicy,
    InstructionLifecycleEffect,
    LegAccountPlan,
    LifecycleStage,
    RentEvidence,
    RentReservation,
    WsolFundingSource,
    WsolLifecyclePolicy,
    derive_associated_token_address,
    require_explicit_jupiter_lifecycle_params,
    validate_associated_token_account,
    validate_cleanup_policy,
    validate_instruction_lifecycle_effect,
    validate_two_leg_lifecycle_dedup,
    validate_wsol_lifecycle,
)


def _pk(seed: int) -> str:
    return str(Pubkey.from_bytes(bytes([seed]) * 32))


PAYER = _pk(1)
TAKER = _pk(2)
OWNER = _pk(3)
MINT = _pk(4)
OUTPUT_MINT = _pk(5)
WRONG_OWNER = _pk(6)
TEMP_WS0L = _pk(7)
DESTINATION = _pk(8)


def _rent(lamports: int = 2_039_280) -> RentEvidence:
    return RentEvidence(
        data_size=TOKEN_ACCOUNT_BASE_DATA_SIZE,
        rent_exempt_lamports=lamports,
        source="getMinimumBalanceForRentExemption",
        endpoint_id="rpc-a",
        context_slot=123,
    )


def _reservation(
    required_lamports: int = 2_039_280,
    reserved_lamports: int = 2_039_280,
) -> RentReservation:
    return RentReservation(
        required_lamports=required_lamports,
        reserved_lamports=reserved_lamports,
        peak_locked_lamports=reserved_lamports,
    )


def _ata_policy(*, create_idempotent: bool = True) -> AssociatedTokenAccountPolicy:
    return AssociatedTokenAccountPolicy(
        owner=OWNER,
        mint=MINT,
        token_program=SPL_TOKEN_PROGRAM_ID,
        payer=PAYER,
        rent=_rent(),
        create_idempotent=create_idempotent,
    )


def _ata_evidence(
    *,
    exists: bool,
    owner: str = OWNER,
    address: str | None = None,
) -> AssociatedTokenAccountEvidence:
    return AssociatedTokenAccountEvidence(
        address=address or derive_associated_token_address(OWNER, MINT),
        owner=owner,
        mint=MINT,
        token_program=SPL_TOKEN_PROGRAM_ID,
        exists=exists,
        pre_existing=exists,
        lamports=2_039_280 if exists else 0,
    )


def test_pr131_jupiter_request_must_not_rely_on_lifecycle_defaults() -> None:
    payload = {
        "inputMint": MINT,
        "outputMint": OUTPUT_MINT,
        "amount": 1_000,
        "taker": TAKER,
        "payer": PAYER,
        "slippageBps": 50,
        "maxAccounts": 50,
        "blockhashSlotsToExpiry": 24,
        "forJitoBundle": False,
        "swapMode": "ExactIn",
    }

    with pytest.raises(AccountLifecycleError) as caught:
        require_explicit_jupiter_lifecycle_params(payload)

    assert caught.value.reason is AccountLifecycleReason.IMPLICIT_JUPITER_DEFAULT
    assert "wrapAndUnwrapSol" in caught.value.details["missing"]


def test_pr131_explicit_jupiter_params_render_all_lifecycle_fields() -> None:
    params = require_explicit_jupiter_lifecycle_params(
        {
            "inputMint": MINT,
            "outputMint": OUTPUT_MINT,
            "amount": "1000",
            "taker": TAKER,
            "payer": PAYER,
            "slippageBps": 50,
            "wrapAndUnwrapSol": False,
            "maxAccounts": 50,
            "blockhashSlotsToExpiry": 24,
            "forJitoBundle": True,
            "swapMode": "ExactIn",
            "destinationTokenAccount": DESTINATION,
        }
    )

    rendered = params.to_build_params()

    assert rendered["payer"] == PAYER
    assert rendered["taker"] == TAKER
    assert rendered["wrapAndUnwrapSol"] == "false"
    assert rendered["maxAccounts"] == "50"
    assert rendered["blockhashSlotsToExpiry"] == "24"
    assert rendered["forJitoBundle"] == "true"
    assert rendered["destinationTokenAccount"] == DESTINATION


def test_pr131_existing_ata_must_match_expected_pda_owner_mint_program() -> None:
    finding = validate_associated_token_account(
        _ata_policy(),
        _ata_evidence(exists=True),
        _reservation(),
    )

    assert finding.semantic_class == "existing_ata"
    assert finding.account == derive_associated_token_address(OWNER, MINT)


def test_pr131_wrong_ata_owner_fails_closed() -> None:
    with pytest.raises(AccountLifecycleError) as caught:
        validate_associated_token_account(
            _ata_policy(),
            _ata_evidence(exists=True, owner=WRONG_OWNER),
            _reservation(),
        )

    assert caught.value.reason is AccountLifecycleReason.ATA_OWNER_MISMATCH


def test_pr131_missing_ata_requires_idempotent_create_and_rent_reservation() -> None:
    finding = validate_associated_token_account(
        _ata_policy(create_idempotent=True),
        _ata_evidence(exists=False),
        _reservation(),
    )

    assert finding.semantic_class == "idempotent_ata_create"
    assert finding.lamports_reserved == 2_039_280


def test_pr131_insufficient_rent_reservation_blocks_missing_ata() -> None:
    with pytest.raises(AccountLifecycleError) as caught:
        validate_associated_token_account(
            _ata_policy(create_idempotent=True),
            _ata_evidence(exists=False),
            _reservation(reserved_lamports=1),
        )

    assert caught.value.reason is AccountLifecycleReason.INSUFFICIENT_RENT_RESERVATION


def test_pr131_pre_borrow_setup_cannot_use_flash_principal() -> None:
    effect = InstructionLifecycleEffect(
        stage=LifecycleStage.PRE_BORROW_OWN_CAPITAL,
        uses_flash_principal=True,
        debits_payer_lamports=0,
        reserved_lamports=0,
    )

    with pytest.raises(AccountLifecycleError) as caught:
        validate_instruction_lifecycle_effect(effect)

    assert caught.value.reason is AccountLifecycleReason.FLASH_PRINCIPAL_PRE_BORROW


def test_pr131_pre_borrow_payer_debit_must_be_reserved() -> None:
    effect = InstructionLifecycleEffect(
        stage=LifecycleStage.PRE_BORROW_OWN_CAPITAL,
        debits_payer_lamports=2_039_280,
        reserved_lamports=1,
    )

    with pytest.raises(AccountLifecycleError) as caught:
        validate_instruction_lifecycle_effect(effect)

    assert caught.value.reason is AccountLifecycleReason.PRE_BORROW_PAYER_DEBIT


def test_pr131_wsol_requires_sync_native_and_payer_close_destination() -> None:
    policy = WsolLifecyclePolicy(
        account=TEMP_WS0L,
        funding_source=WsolFundingSource.PAYER_RESERVED_SOL,
        amount_lamports=1_000_000,
        rent_lamports=2_039_280,
        sync_native_after_funding=True,
        temporary_account=True,
        pre_existing=False,
        close_destination=PAYER,
        close_authority=PAYER,
    )

    finding = validate_wsol_lifecycle(policy, payer=PAYER)

    assert finding.semantic_class == "temporary_wsol"
    assert finding.account == TEMP_WS0L


def test_pr131_wsol_missing_sync_native_fails_closed() -> None:
    policy = WsolLifecyclePolicy(
        account=TEMP_WS0L,
        funding_source=WsolFundingSource.PAYER_RESERVED_SOL,
        amount_lamports=1_000_000,
        rent_lamports=2_039_280,
        sync_native_after_funding=False,
        temporary_account=True,
        pre_existing=False,
        close_destination=PAYER,
        close_authority=PAYER,
    )

    with pytest.raises(AccountLifecycleError) as caught:
        validate_wsol_lifecycle(policy, payer=PAYER)

    assert caught.value.reason is AccountLifecycleReason.WSOL_SYNC_MISSING


def test_pr131_cleanup_cannot_close_preexisting_account() -> None:
    policy = CleanupPolicy(
        account=derive_associated_token_address(OWNER, NATIVE_SOL_MINT),
        pre_existing=True,
        close_destination=PAYER,
        expected_rent_destination=PAYER,
    )

    with pytest.raises(AccountLifecycleError) as caught:
        validate_cleanup_policy(policy)

    assert caught.value.reason is AccountLifecycleReason.CLEANUP_PREEXISTING_ACCOUNT


def test_pr131_two_leg_lifecycle_must_dedup_duplicate_ata_plans() -> None:
    shared = derive_associated_token_address(OWNER, MINT)
    first = LegAccountPlan("a", ata_addresses=(shared,))
    second = LegAccountPlan("b", ata_addresses=(shared,))

    with pytest.raises(AccountLifecycleError) as caught:
        validate_two_leg_lifecycle_dedup(first, second)

    assert caught.value.reason is AccountLifecycleReason.DUPLICATE_ATA_PLAN
