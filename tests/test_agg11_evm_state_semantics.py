from __future__ import annotations

import pytest

from src.multichain import (
    ChainCapabilityRegistry,
    EvmBlockRef,
    EvmCall,
    EvmFinality,
    EvmOperationPlan,
    EvmStateFrame,
    MultiChainError,
)
from src.multichain.evm_state import (
    EvmAccountState,
    EvmAllowanceRequirement,
    EvmExecutionEnvelope,
    EvmExecutionReceipt,
    EvmLogObservation,
    EvmStateDelta,
    EvmStateSnapshot,
    validate_execution_receipt,
)


pytestmark = pytest.mark.unit

H1 = "1" * 64
H2 = "2" * 64
ADDR_A = "0x" + "11" * 20
ADDR_B = "0x" + "22" * 20
TOKEN = "0x" + "33" * 20
BLOCK = "0x" + "ab" * 32
PARENT = "0x" + "cd" * 32
TX = "0x" + "ef" * 32


def _plan() -> EvmOperationPlan:
    return EvmOperationPlan(
        chain_key="base-mainnet",
        chain_id=8453,
        sender=ADDR_B,
        nonce=7,
        state_digest=H2,
        calls=(EvmCall(ADDR_A, "0x1234"),),
        gas_limit=250_000,
        max_fee_per_gas=10,
        max_priority_fee_per_gas=2,
    )


def _frame() -> EvmStateFrame:
    capability = ChainCapabilityRegistry.packaged().capability(
        "base-mainnet:aave"
    )
    from src.multichain import DeploymentRef

    deployment = DeploymentRef(
        protocol="aave",
        chain_key="base-mainnet",
        deployment_id="fixture",
        version="v1",
        interface_digest=H1,
        artifact_digest=H2,
        generation="fixture",
    )
    assert capability.chain_key == deployment.chain_key
    return EvmStateFrame(
        chain_key="base-mainnet",
        block=EvmBlockRef(
            chain_id=8453,
            number=100,
            block_hash=BLOCK,
            parent_hash=PARENT,
            finality=EvmFinality.SAFE,
        ),
        deployment=deployment,
        interface_digest=H1,
        proxy_implementation=ADDR_A,
        state_digest=H2,
    )


def test_snapshot_binds_account_storage_log_to_one_block() -> None:
    account = EvmAccountState(
        address=ADDR_A,
        nonce=1,
        balance_wei=100,
        code_hash="0x" + "12" * 32,
        storage_digest=H1,
    )
    log = EvmLogObservation(
        block_hash=BLOCK,
        transaction_hash=TX,
        log_index=0,
        address=ADDR_A,
        topics=("0x" + "34" * 32,),
        data="0x",
    )
    snapshot = EvmStateSnapshot(_frame(), (account,), (log,))

    assert snapshot.require_account(ADDR_A) is account
    with pytest.raises(MultiChainError, match="EVM_ACCOUNT_STATE_MISSING"):
        snapshot.require_account(ADDR_B)


def test_allowance_is_exact_identity_and_lower_bound() -> None:
    plan = _plan()
    requirement = EvmAllowanceRequirement(TOKEN, ADDR_B, ADDR_A, 50)
    envelope = EvmExecutionEnvelope(
        plan,
        allowances=(requirement,),
        expected_callback_senders=(ADDR_A,),
    )

    envelope.validate_allowance(
        token=TOKEN,
        owner=ADDR_B,
        spender=ADDR_A,
        actual_units=50,
    )
    with pytest.raises(MultiChainError, match="EVM_ALLOWANCE_INSUFFICIENT"):
        envelope.validate_allowance(
            token=TOKEN,
            owner=ADDR_B,
            spender=ADDR_A,
            actual_units=49,
        )


def test_landed_receipt_binds_chain_nonce_plan_and_exact_fee() -> None:
    plan = _plan()
    receipt = EvmExecutionReceipt(
        chain_id=8453,
        plan_digest=plan.digest,
        transaction_hash=TX,
        block_hash=BLOCK,
        nonce=7,
        gas_used=100,
        effective_gas_price=10,
        fee_components_wei=(7, 3),
        state_deltas=(
            EvmStateDelta(ADDR_B, -1_010, 7, 8),
        ),
        status_success=True,
        landed=True,
    )

    validate_execution_receipt(plan, receipt)
    assert receipt.exact_fee_wei == 1_010

    with pytest.raises(MultiChainError, match="EVM_RECEIPT_NONCE_MISMATCH"):
        validate_execution_receipt(
            plan,
            EvmExecutionReceipt(
                chain_id=8453,
                plan_digest=plan.digest,
                transaction_hash=TX,
                block_hash=BLOCK,
                nonce=8,
                gas_used=100,
                effective_gas_price=10,
                fee_components_wei=(),
                state_deltas=(),
                status_success=True,
                landed=True,
            ),
        )
