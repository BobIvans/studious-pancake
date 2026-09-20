from __future__ import annotations

import pytest
from solders.instruction import Instruction
from solders.pubkey import Pubkey

from src.lending.agg03_financing_ports import (
    JupiterLendFinancingPort,
    JupiterLendFinancingSnapshot,
    SlumlordFinancingPort,
    SlumlordFinancingSnapshot,
)
from src.lending.financing import (
    FinancingContractError,
    FinancingEvidence,
    FinancingRole,
)
from src.lending.jupiter_lend import (
    JUPITER_FLASHLOAN_ADMIN_PDA,
    JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
    JupiterLendFlashloanAccounts,
)
from src.lending.slumlord import (
    SLUMLORD_PDA,
    SLUMLORD_PROGRAM_ID,
    SlumlordReserveState,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _jupiter_accounts() -> JupiterLendFlashloanAccounts:
    payer = Pubkey.new_unique()
    token = Pubkey.new_unique()
    return JupiterLendFlashloanAccounts(
        signer=payer,
        flashloan_admin=JUPITER_FLASHLOAN_ADMIN_PDA,
        signer_borrow_token_account=token,
        mint=Pubkey.new_unique(),
        flashloan_token_reserves_liquidity=Pubkey.new_unique(),
        flashloan_borrow_position_on_liquidity=Pubkey.new_unique(),
        rate_model=Pubkey.new_unique(),
        vault=Pubkey.new_unique(),
        liquidity=Pubkey.new_unique(),
        liquidity_program=Pubkey.new_unique(),
        token_program=Pubkey.new_unique(),
    )


def _evidence(lender: str, program: Pubkey) -> FinancingEvidence:
    return FinancingEvidence(
        lender_id=lender,
        program_id=str(program),
        deployment_generation=1,
        evidence_sha256=SHA_A,
        decoder_identity=f"{lender}-decoder-v1",
        decoder_generation=1,
    )


def test_jupiter_lend_port_prepares_and_finalizes_exact_unsigned_sequence() -> None:
    accounts = _jupiter_accounts()
    port = JupiterLendFinancingPort(
        _evidence("jupiter-lend", JUPITER_LEND_FLASHLOAN_PROGRAM_ID)
    )
    snapshot = JupiterLendFinancingSnapshot(
        accounts=accounts,
        asset_id=f"spl:{accounts.mint}:6",
        available_liquidity_base_units=500,
        required_repayment_base_units=100,
        slot=42,
        evidence_sha256=SHA_A,
        state_fingerprint=SHA_B,
    )
    prepared = port.prepare(
        snapshot=snapshot,
        amount=100,
        destination_account=str(accounts.signer_borrow_token_account),
        repayment_source_account=str(accounts.signer_borrow_token_account),
        minimum_terminal_balance=100,
    )
    assert prepared.obligation.role is FinancingRole.PRIMARY
    sequence = (
        prepared.borrow_instructions[0],
        Instruction(Pubkey.new_unique(), b"x", []),
        prepared.repay_instructions[0],
    )
    finalized = port.finalize(prepared, sequence)
    assert finalized.instructions == sequence
    assert len(finalized.sequence_fingerprint) == 64


def test_jupiter_lend_port_refuses_unproven_dynamic_repayment_contract() -> None:
    accounts = _jupiter_accounts()
    port = JupiterLendFinancingPort(
        _evidence("jupiter-lend", JUPITER_LEND_FLASHLOAN_PROGRAM_ID)
    )
    snapshot = JupiterLendFinancingSnapshot(
        accounts=accounts,
        asset_id=f"spl:{accounts.mint}:6",
        available_liquidity_base_units=500,
        required_repayment_base_units=101,
        slot=42,
        evidence_sha256=SHA_A,
        state_fingerprint=SHA_B,
    )
    with pytest.raises(
        FinancingContractError,
        match="DYNAMIC_REPAYMENT_UNSUPPORTED",
    ):
        port.prepare(
            snapshot=snapshot,
            amount=100,
            destination_account=str(accounts.signer_borrow_token_account),
            repayment_source_account=str(accounts.signer_borrow_token_account),
            minimum_terminal_balance=101,
        )


def test_slumlord_port_preserves_rent_role_and_check_repaid_order() -> None:
    port = SlumlordFinancingPort(_evidence("slumlord", SLUMLORD_PROGRAM_ID))
    reserve = SlumlordReserveState(
        address=SLUMLORD_PDA,
        owner=SLUMLORD_PROGRAM_ID,
        lamports=101,
        data=b"",
        slot=77,
    )
    snapshot = SlumlordFinancingSnapshot(
        reserve=reserve,
        evidence_sha256=SHA_A,
        state_fingerprint=SHA_B,
    )
    payer = Pubkey.new_unique()
    prepared = port.prepare(
        snapshot=snapshot,
        amount=100,
        destination_account=str(payer),
        repayment_source_account=str(payer),
        minimum_terminal_balance=100,
        role=FinancingRole.RENT,
    )
    assert prepared.obligation.role is FinancingRole.RENT
    assert prepared.obligation.principal_base_units == 100
    sequence = (
        prepared.borrow_instructions[0],
        Instruction(Pubkey.new_unique(), b"x", []),
        prepared.repay_instructions[0],
        prepared.repay_instructions[1],
    )
    finalized = port.finalize(prepared, sequence)
    assert finalized.instructions == sequence


def test_ports_reject_evidence_from_another_program_or_snapshot_generation() -> None:
    with pytest.raises(FinancingContractError, match="FINANCING_PROGRAM_MISMATCH"):
        JupiterLendFinancingPort(
            _evidence("jupiter-lend", Pubkey.new_unique())
        )

    port = SlumlordFinancingPort(_evidence("slumlord", SLUMLORD_PROGRAM_ID))
    reserve = SlumlordReserveState(
        address=SLUMLORD_PDA,
        owner=SLUMLORD_PROGRAM_ID,
        lamports=101,
        data=b"",
        slot=77,
    )
    bad = SlumlordFinancingSnapshot(
        reserve=reserve,
        evidence_sha256="c" * 64,
        state_fingerprint=SHA_B,
    )
    payer = Pubkey.new_unique()
    with pytest.raises(FinancingContractError, match="FINANCING_EVIDENCE_MISMATCH"):
        port.prepare(
            snapshot=bad,
            amount=100,
            destination_account=str(payer),
            repayment_source_account=str(payer),
            minimum_terminal_balance=100,
            role=FinancingRole.RENT,
        )
