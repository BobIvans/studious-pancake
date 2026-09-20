from __future__ import annotations

from dataclasses import replace

import pytest
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from src.lending.jupiter_lend import (
    FLASHLOAN_BORROW_DISCRIMINATOR,
    FLASHLOAN_PAYBACK_DISCRIMINATOR,
    JUPITER_FLASHLOAN_ADMIN_PDA,
    JUPITER_LEND_FLASHLOAN_IDL_BLOB,
    JUPITER_LEND_FLASHLOAN_IDL_VERSION,
    JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
    JUPITER_LEND_UPSTREAM_COMMIT,
    JupiterLendAdapterError,
    JupiterLendFlashloanAccounts,
    build_flashloan_borrow_instruction,
    build_flashloan_payback_instruction,
    validate_jupiter_lend_order,
)
from src.lending.slumlord import (
    INSTRUCTIONS_SYSVAR_ID,
    SLUMLORD_INSTRUCTIONS_BLOB,
    SLUMLORD_LIBRARY_BLOB,
    SLUMLORD_PDA,
    SLUMLORD_PROGRAM_ID,
    SLUMLORD_UPSTREAM_COMMIT,
    SYSTEM_PROGRAM_ID,
    SlumlordAdapterError,
    SlumlordReserveState,
    build_borrow_instruction,
    build_check_repaid_instruction,
    build_repay_instruction,
    prepare_rent_loan,
    validate_slumlord_order,
)


def _pk(seed: int) -> Pubkey:
    return Pubkey.from_bytes(bytes((seed,)) * 32)


def _jupiter_accounts() -> JupiterLendFlashloanAccounts:
    return JupiterLendFlashloanAccounts(
        signer=_pk(1),
        flashloan_admin=JUPITER_FLASHLOAN_ADMIN_PDA,
        signer_borrow_token_account=_pk(2),
        mint=_pk(3),
        flashloan_token_reserves_liquidity=_pk(4),
        flashloan_borrow_position_on_liquidity=_pk(5),
        rate_model=_pk(6),
        vault=_pk(7),
        liquidity=_pk(8),
        liquidity_program=_pk(9),
        token_program=_pk(10),
    )


def test_slumlord_upstream_identity_is_pinned() -> None:
    assert SLUMLORD_UPSTREAM_COMMIT == "5c5565cb106f5316a66df8ba616034a7810fa850"
    assert SLUMLORD_INSTRUCTIONS_BLOB == "9755520565f83dd2ee9f02bcc2651e193e669dcc"
    assert SLUMLORD_LIBRARY_BLOB == "03b41179d6e50b745ee9b9e6273753f0b9fb39b1"
    assert str(SLUMLORD_PROGRAM_ID) == (
        "s1umBj7CEUA6djs6V1c6o2Nym3QrqF4ryKDr1Nm1FKt"
    )
    assert SLUMLORD_PDA != SLUMLORD_PROGRAM_ID


def test_slumlord_builders_match_pinned_instruction_contract() -> None:
    destination = _pk(11)
    source = _pk(12)

    borrow = build_borrow_instruction(destination)
    repay = build_repay_instruction(source)
    check = build_check_repaid_instruction()

    assert borrow.program_id == SLUMLORD_PROGRAM_ID
    assert bytes(borrow.data) == b""
    assert [(m.pubkey, m.is_signer, m.is_writable) for m in borrow.accounts] == [
        (SLUMLORD_PDA, False, True),
        (destination, False, True),
        (INSTRUCTIONS_SYSVAR_ID, False, False),
    ]

    assert bytes(repay.data) == b""
    assert [(m.pubkey, m.is_signer, m.is_writable) for m in repay.accounts] == [
        (SLUMLORD_PDA, False, True),
        (source, True, True),
        (SYSTEM_PROGRAM_ID, False, False),
    ]

    assert bytes(check.data) == b""
    assert [(m.pubkey, m.is_signer, m.is_writable) for m in check.accounts] == [
        (SLUMLORD_PDA, False, True)
    ]


def test_slumlord_reserve_uses_balance_minus_one_and_saturating_debt() -> None:
    idle = SlumlordReserveState(
        address=SLUMLORD_PDA,
        owner=SLUMLORD_PROGRAM_ID,
        lamports=100,
        data=b"",
        slot=77,
    )
    prepared = prepare_rent_loan(
        idle,
        destination=_pk(13),
        repayment_source=_pk(14),
        requested_lamports=99,
    )
    assert prepared.borrow_lamports == 99
    assert prepared.required_repayment_lamports == 99

    active = SlumlordReserveState(
        address=SLUMLORD_PDA,
        owner=SLUMLORD_PROGRAM_ID,
        lamports=1,
        data=(100).to_bytes(8, "little"),
        slot=78,
    )
    assert active.loan_active is True
    assert active.old_lamports == 100
    assert active.outstanding_lamports == 99
    assert active.available_borrow_lamports == 0


def test_slumlord_rejects_amount_override_active_and_malformed_state() -> None:
    idle = SlumlordReserveState(
        address=SLUMLORD_PDA,
        owner=SLUMLORD_PROGRAM_ID,
        lamports=100,
        data=b"",
        slot=80,
    )
    with pytest.raises(SlumlordAdapterError, match="BORROW_AMOUNT_MISMATCH"):
        prepare_rent_loan(
            idle,
            destination=_pk(15),
            repayment_source=_pk(16),
            requested_lamports=98,
        )

    active = SlumlordReserveState(
        address=SLUMLORD_PDA,
        owner=SLUMLORD_PROGRAM_ID,
        lamports=1,
        data=(100).to_bytes(8, "little"),
        slot=81,
    )
    with pytest.raises(SlumlordAdapterError, match="BORROW_ALREADY_ACTIVE"):
        prepare_rent_loan(
            active,
            destination=_pk(15),
            repayment_source=_pk(16),
        )

    with pytest.raises(SlumlordAdapterError, match="INVALID_STATE"):
        SlumlordReserveState(
            address=SLUMLORD_PDA,
            owner=SLUMLORD_PROGRAM_ID,
            lamports=100,
            data=b"short",
            slot=82,
        )


def test_slumlord_requires_borrow_repay_succeeding_check() -> None:
    borrow = build_borrow_instruction(_pk(17))
    repay = build_repay_instruction(_pk(18))
    check = build_check_repaid_instruction()

    certificate = validate_slumlord_order((borrow, repay, check))
    assert (
        certificate.borrow_index,
        certificate.repay_index,
        certificate.check_repaid_index,
    ) == (0, 1, 2)

    with pytest.raises(SlumlordAdapterError, match="ORDER_INVARIANT"):
        validate_slumlord_order((borrow, repay))
    with pytest.raises(SlumlordAdapterError, match="ORDER_INVARIANT"):
        validate_slumlord_order((check, borrow, repay))


def test_slumlord_order_rejects_correct_discriminator_with_wrong_metas() -> None:
    malformed_borrow = Instruction(
        SLUMLORD_PROGRAM_ID,
        b"",
        [
            AccountMeta(SLUMLORD_PDA, False, True),
            AccountMeta(_pk(17), True, True),
            AccountMeta(INSTRUCTIONS_SYSVAR_ID, False, False),
        ],
    )
    repay = build_repay_instruction(_pk(18))
    check = build_check_repaid_instruction()

    with pytest.raises(SlumlordAdapterError, match="ORDER_INVARIANT"):
        validate_slumlord_order((malformed_borrow, repay, check))


def test_jupiter_lend_official_idl_identity_is_pinned() -> None:
    assert JUPITER_LEND_UPSTREAM_COMMIT == (
        "33a22cf7a5bfdd32ab1712dda4adfbeb9b348ad9"
    )
    assert JUPITER_LEND_FLASHLOAN_IDL_BLOB == (
        "0d0ae6d624b33355315e98baaf0a5d00d317beb8"
    )
    assert JUPITER_LEND_FLASHLOAN_IDL_VERSION == "0.1.4"
    assert str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID) == (
        "jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS"
    )


def test_jupiter_lend_builders_match_pinned_discriminators_amount_and_metas() -> None:
    accounts = _jupiter_accounts()
    amount = 123_456_789
    borrow = build_flashloan_borrow_instruction(accounts, amount)
    payback = build_flashloan_payback_instruction(accounts, amount)

    assert borrow.program_id == JUPITER_LEND_FLASHLOAN_PROGRAM_ID
    assert bytes(borrow.data[:8]) == FLASHLOAN_BORROW_DISCRIMINATOR
    assert int.from_bytes(bytes(borrow.data[8:]), "little") == amount
    assert bytes(payback.data[:8]) == FLASHLOAN_PAYBACK_DISCRIMINATOR
    assert int.from_bytes(bytes(payback.data[8:]), "little") == amount

    actual_flags = [(m.is_signer, m.is_writable) for m in borrow.accounts]
    assert actual_flags == [
        (True, True),
        (False, True),
        (False, True),
        (False, False),
        (False, True),
        (False, True),
        (False, False),
        (False, True),
        (False, False),
        (False, False),
        (False, False),
        (False, False),
        (False, False),
        (False, False),
    ]
    assert tuple(borrow.accounts) == tuple(payback.accounts)


def test_jupiter_lend_order_is_amount_and_account_bound() -> None:
    accounts = _jupiter_accounts()
    borrow = build_flashloan_borrow_instruction(accounts, 10)
    payback = build_flashloan_payback_instruction(accounts, 10)
    certificate = validate_jupiter_lend_order((borrow, payback))
    assert certificate.amount == 10
    assert certificate.borrow_index == 0
    assert certificate.payback_index == 1

    amount_mismatch = build_flashloan_payback_instruction(accounts, 11)
    with pytest.raises(JupiterLendAdapterError, match="AMOUNT_MISMATCH"):
        validate_jupiter_lend_order((borrow, amount_mismatch))

    foreign_accounts = replace(accounts, signer=_pk(21))
    foreign_payback = build_flashloan_payback_instruction(foreign_accounts, 10)
    with pytest.raises(JupiterLendAdapterError, match="ACCOUNT_MISMATCH"):
        validate_jupiter_lend_order((borrow, foreign_payback))

    with pytest.raises(JupiterLendAdapterError, match="ORDER_INVARIANT"):
        validate_jupiter_lend_order((payback, borrow))
    with pytest.raises(JupiterLendAdapterError, match="INVALID_AMOUNT"):
        build_flashloan_borrow_instruction(accounts, 0)


def test_jupiter_lend_order_rejects_malformed_meta_shape() -> None:
    accounts = _jupiter_accounts()
    valid_payback = build_flashloan_payback_instruction(accounts, 10)
    malformed_borrow = Instruction(
        JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
        FLASHLOAN_BORROW_DISCRIMINATOR + (10).to_bytes(8, "little"),
        [
            AccountMeta(accounts.signer, False, True),
            *accounts.metas()[1:],
        ],
    )

    with pytest.raises(JupiterLendAdapterError, match="ACCOUNT_MISMATCH"):
        validate_jupiter_lend_order((malformed_borrow, valid_payback))


def test_jupiter_lend_rejects_wrong_flashloan_admin() -> None:
    with pytest.raises(JupiterLendAdapterError, match="INVALID_FIXED_ACCOUNT"):
        JupiterLendFlashloanAccounts(
            signer=_pk(1),
            flashloan_admin=_pk(20),
            signer_borrow_token_account=_pk(2),
            mint=_pk(3),
            flashloan_token_reserves_liquidity=_pk(4),
            flashloan_borrow_position_on_liquidity=_pk(5),
            rate_model=_pk(6),
            vault=_pk(7),
            liquidity=_pk(8),
            liquidity_program=_pk(9),
            token_program=_pk(10),
        )


def test_agg03_adapters_are_sender_free() -> None:
    accounts = _jupiter_accounts()
    instruction = build_flashloan_borrow_instruction(accounts, 1)
    assert isinstance(instruction, Instruction)
    assert not hasattr(instruction, "sign")
    assert not hasattr(instruction, "send")
