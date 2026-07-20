from __future__ import annotations

from dataclasses import replace

import pytest
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from src.execution import (
    BlockhashContext,
    CanonicalExecutionContractError,
    ComputeBudgetPolicy,
    ExecutionReceipt,
    PlannedInstruction,
    TipPolicy,
    TransactionCompiler,
    TransactionPlan,
    validate_canonical_plan,
    validate_compiled_identity,
)


def _plan(payer: Pubkey) -> TransactionPlan:
    ix = Instruction(Pubkey.default(), b"", [])
    return TransactionPlan(
        opportunity_id="pr029-fixture",
        payer=payer,
        instructions=(PlannedInstruction(ix, role="application", name="noop"),),
        compute_budget_policy=ComputeBudgetPolicy(),
        tip_policy=TipPolicy(),
        required_signers=(payer,),
    )


def _blockhash() -> BlockhashContext:
    return BlockhashContext(
        blockhash=Hash.from_bytes(bytes(range(32))),
        last_valid_block_height=10,
        source_slot=1,
        fetched_at=0.0,
        commitment="confirmed",
    )


def test_public_compiler_rejects_legacy_string_payer_before_delegate() -> None:
    plan = _plan(Keypair().pubkey())
    object.__setattr__(plan, "payer", "legacy-payer")

    with pytest.raises(CanonicalExecutionContractError, match="payer must be"):
        TransactionCompiler().compile(plan, _blockhash())


def test_public_plan_requires_solders_instructions() -> None:
    plan = _plan(Keypair().pubkey())
    object.__setattr__(plan, "instructions", ("legacy-instruction",))

    with pytest.raises(CanonicalExecutionContractError, match="PlannedInstruction"):
        validate_canonical_plan(plan)


def test_canonical_compile_has_real_v0_identity_and_no_synthetic_prefix() -> None:
    payer = Keypair()
    compiled = TransactionCompiler().compile(_plan(payer.pubkey()), _blockhash())

    validate_compiled_identity(compiled)
    assert len(compiled.message_hash) == 64
    assert not compiled.serialized_transaction.startswith(b"unsigned:")


def test_message_hash_mutation_is_rejected() -> None:
    payer = Keypair()
    compiled = TransactionCompiler().compile(_plan(payer.pubkey()), _blockhash())
    corrupted = replace(compiled, message_hash="0" * 64)

    with pytest.raises(CanonicalExecutionContractError, match="hash mismatch"):
        validate_compiled_identity(corrupted)


def test_execution_receipt_is_bound_to_hash_and_state() -> None:
    receipt = ExecutionReceipt(
        message_hash="a" * 64,
        transport="paper",
        accepted=True,
        landed=False,
    )
    assert receipt.message_hash == "a" * 64

    with pytest.raises(CanonicalExecutionContractError, match="must be accepted"):
        ExecutionReceipt(
            message_hash="a" * 64,
            transport="rpc",
            accepted=False,
            landed=True,
        )
