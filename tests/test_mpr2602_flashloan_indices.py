"""Source-derived vectors, not SDK or deployed-conformance qualification."""

from dataclasses import replace

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from src.execution.models import (
    BlockhashContext,
    ComputeBudgetPolicy,
    PlannedInstruction,
    TransactionPlan,
)
from src.execution.transaction_compiler import (
    TransactionCompiler,
    TransactionCompileError,
)
from src.providers.marginfi.pin import load_marginfi_contract_pin


def _plan():
    pin = load_marginfi_contract_pin()
    program = Pubkey.from_string(pin.program_id)
    payer = Pubkey.from_bytes(bytes([1]) * 32)
    account = Pubkey.from_bytes(bytes([2]) * 32)
    metas = [AccountMeta(account, False, True), AccountMeta(payer, True, False)]
    start = Instruction(
        program,
        pin.ix_discriminator("lending_account_start_flashloan")
        + (2).to_bytes(8, "little"),
        [
            *metas,
            AccountMeta(
                Pubkey.from_string(pin.raw["programs"]["instructions_sysvar"]),
                False,
                False,
            ),
        ],
    )
    middle = Instruction(
        program, pin.ix_discriminator("lending_account_repay") + bytes(10), metas
    )
    end = Instruction(
        program, pin.ix_discriminator("lending_account_end_flashloan"), metas
    )
    return TransactionPlan(
        "index-vector",
        payer,
        tuple(PlannedInstruction(ix) for ix in (start, middle, end)),
        required_signers=(payer,),
    )


def _compile(plan):
    return TransactionCompiler().compile(
        plan,
        BlockhashContext(Hash.from_bytes(bytes([8]) * 32), 1000, 900, 1.0, "confirmed"),
    )


@pytest.mark.parametrize(
    "policy,prefix",
    [
        (ComputeBudgetPolicy(), 0),
        (ComputeBudgetPolicy(unit_limit=200000), 1),
        (ComputeBudgetPolicy(micro_lamports_per_cu=0), 1),
        (ComputeBudgetPolicy(unit_limit=200000, micro_lamports_per_cu=1), 2),
    ],
)
def test_actual_compiled_index_points_to_exact_end_after_compute_prefix(policy, prefix):
    plan = replace(_plan(), compute_budget_policy=policy)
    compiled = _compile(plan)
    actual = compiled.message.instructions
    end_index = int.from_bytes(actual[prefix].data[8:], "little")
    assert end_index == 2 + prefix
    assert actual[end_index].data == plan.instructions[-1].instruction.data
    assert actual[end_index].accounts[0] == actual[prefix].accounts[0]
    assert int.from_bytes(plan.instructions[0].instruction.data[8:], "little") == 2
    assert not compiled.is_fully_signed


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-index",
        "missing-end",
        "duplicate-start",
        "wrong-account",
        "bad-sysvar",
        "truncated-start",
    ],
)
def test_malformed_boundaries_are_rejected_before_compilation(mutation):
    plan = _plan()
    ixs = [entry.instruction for entry in plan.instructions]
    if mutation == "wrong-index":
        ixs[0] = Instruction(
            ixs[0].program_id, ixs[0].data[:8] + bytes(8), ixs[0].accounts
        )
    elif mutation == "missing-end":
        ixs.pop()
    elif mutation == "duplicate-start":
        ixs.append(ixs[0])
    elif mutation == "wrong-account":
        ixs[-1] = Instruction(
            ixs[-1].program_id,
            ixs[-1].data,
            [
                AccountMeta(Pubkey.from_bytes(bytes([5]) * 32), False, True),
                ixs[-1].accounts[1],
            ],
        )
    elif mutation == "bad-sysvar":
        ixs[0] = Instruction(
            ixs[0].program_id,
            ixs[0].data,
            [*ixs[0].accounts[:2], AccountMeta(plan.payer, False, False)],
        )
    else:
        ixs[0] = Instruction(ixs[0].program_id, ixs[0].data[:8], ixs[0].accounts)
    with pytest.raises(TransactionCompileError, match="MarginFi flashloan boundary"):
        _compile(
            replace(plan, instructions=tuple(PlannedInstruction(ix) for ix in ixs))
        )


def test_recompilation_rebinds_each_message_without_accumulating_offsets():
    plan = _plan()
    a = _compile(
        replace(plan, compute_budget_policy=ComputeBudgetPolicy(unit_limit=100000))
    )
    b = _compile(
        replace(
            plan,
            compute_budget_policy=ComputeBudgetPolicy(
                unit_limit=110000, micro_lamports_per_cu=1
            ),
        )
    )
    assert int.from_bytes(a.message.instructions[1].data[8:], "little") == 3
    assert int.from_bytes(b.message.instructions[2].data[8:], "little") == 4
    assert a.message_hash != b.message_hash
