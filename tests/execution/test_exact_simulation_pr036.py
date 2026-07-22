from __future__ import annotations

from collections import defaultdict
from typing import Any

import pytest
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from src.execution.exact_simulation import (
    ExactSimulationError,
    ExactSimulationErrorCode,
    ExactSimulationFinalizer,
    ExactSimulationPolicy,
    FailureDisposition,
    validate_exact_submission_binding,
)
from src.execution.models import (
    BlockhashContext,
    ComputeBudgetPolicy,
    PlannedInstruction,
    TipPolicy,
    TransactionPlan,
)


class FakeRpc:
    def __init__(self, responses: dict[str, list[Any]]) -> None:
        self.responses = {name: list(values) for name, values in responses.items()}
        self.calls: list[tuple[str, list[Any]]] = []

    async def call(self, method: str, params: list[Any]) -> Any:
        self.calls.append((method, params))
        if method not in self.responses or not self.responses[method]:
            raise AssertionError(f"unexpected RPC call: {method}")
        value = self.responses[method].pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def _plan(
    payer: Pubkey,
    *,
    monitored: tuple[Pubkey, ...] = (),
    micro_lamports_per_cu: int = 7,
) -> TransactionPlan:
    instruction = Instruction(Pubkey.default(), b"pr036", [])
    return TransactionPlan(
        opportunity_id="pr036-fixture",
        payer=payer,
        instructions=(
            PlannedInstruction(instruction, role="application", name="fixture"),
        ),
        compute_budget_policy=ComputeBudgetPolicy(
            micro_lamports_per_cu=micro_lamports_per_cu,
        ),
        tip_policy=TipPolicy(),
        required_signers=(payer,),
        quote_slot=9,
        market_state_slot=11,
        oracle_slot=10,
        monitored_accounts=monitored,
    )


def _blockhash(*, last_valid_block_height: int = 100) -> BlockhashContext:
    return BlockhashContext(
        blockhash=Hash.from_bytes(bytes(range(32))),
        last_valid_block_height=last_valid_block_height,
        source_slot=20,
        fetched_at=0.0,
        commitment="confirmed",
    )


def _blockhash_valid(*, slot: int = 21, value: bool = True) -> dict[str, Any]:
    return {"context": {"slot": slot}, "value": value}


def _simulation(
    *,
    slot: int,
    units: int | None,
    account_count: int = 1,
    loaded_size: int | None = 1_024,
    error: object | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "err": error,
        "logs": ["Program fixture invoke [1]", "Program fixture success"],
        "innerInstructions": [],
        "loadedAccountsDataSize": loaded_size,
        "returnData": None,
        "replacementBlockhash": None,
        "accounts": [None] * account_count,
    }
    if units is not None:
        value["unitsConsumed"] = units
    return {"context": {"slot": slot}, "value": value}


def _success_rpc(*, provisional_units: int = 200_000) -> FakeRpc:
    return FakeRpc(
        {
            "getBlockHeight": [50, 51],
            "isBlockhashValid": [_blockhash_valid(slot=21), _blockhash_valid(slot=22)],
            "simulateTransaction": [
                _simulation(slot=21, units=provisional_units),
                _simulation(slot=22, units=210_000),
            ],
            "getFeeForMessage": [
                {"context": {"slot": 23}, "value": 5_000},
            ],
        }
    )


@pytest.mark.asyncio
async def test_two_pass_finalization_binds_exact_message_and_fee() -> None:
    payer = Keypair().pubkey()
    rpc = _success_rpc()

    finalized = await ExactSimulationFinalizer(rpc).finalize(
        _plan(payer),
        _blockhash(),
    )

    assert finalized.report.final_compute_unit_limit == 240_000
    assert finalized.report.final_compute_unit_price == 7
    assert finalized.report.final_fee_lamports == 5_000
    assert finalized.report.fee_context_slot == 23
    assert finalized.report.min_context_slot == 11
    assert finalized.report.monitored_accounts == (str(payer),)
    assert finalized.report.provisional.message_hash != finalized.report.message_hash
    assert finalized.report.message_hash == finalized.compiled.message_hash
    assert len(finalized.report.final.response_hash) == 64
    assert len(finalized.report.final.logs_hash) == 64
    assert len(finalized.report.blockhash_validations) == 2
    assert all(item.valid for item in finalized.report.blockhash_validations)
    assert all(
        item.min_context_slot == 11 for item in finalized.report.blockhash_validations
    )

    methods = [method for method, _ in rpc.calls]
    assert methods == [
        "getBlockHeight",
        "isBlockhashValid",
        "simulateTransaction",
        "getBlockHeight",
        "isBlockhashValid",
        "simulateTransaction",
        "getFeeForMessage",
    ]
    blockhash_configs = [
        params[1] for method, params in rpc.calls if method == "isBlockhashValid"
    ]
    assert all(config["commitment"] == "confirmed" for config in blockhash_configs)
    assert all(config["minContextSlot"] == 11 for config in blockhash_configs)
    assert all(
        params[0] == str(_blockhash().blockhash)
        for method, params in rpc.calls
        if method == "isBlockhashValid"
    )
    simulation_configs = [
        params[1] for method, params in rpc.calls if method == "simulateTransaction"
    ]
    assert all(
        config["replaceRecentBlockhash"] is False for config in simulation_configs
    )
    assert all(config["sigVerify"] is False for config in simulation_configs)
    assert all(config["commitment"] == "confirmed" for config in simulation_configs)
    assert all(config["minContextSlot"] == 11 for config in simulation_configs)
    assert all(
        config["accounts"]["addresses"] == [str(payer)] for config in simulation_configs
    )


@pytest.mark.asyncio
async def test_blockhash_height_low_but_invalid_for_fork_is_retryable() -> None:
    rpc = FakeRpc(
        {
            "getBlockHeight": [50],
            "isBlockhashValid": [_blockhash_valid(slot=21, value=False)],
        }
    )

    with pytest.raises(ExactSimulationError, match="not valid") as captured:
        await ExactSimulationFinalizer(rpc).finalize(
            _plan(Keypair().pubkey()),
            _blockhash(),
        )

    assert captured.value.code == ExactSimulationErrorCode.BLOCKHASH_INVALID
    assert captured.value.disposition == FailureDisposition.RETRYABLE
    assert [method for method, _ in rpc.calls] == [
        "getBlockHeight",
        "isBlockhashValid",
    ]


@pytest.mark.asyncio
async def test_is_blockhash_valid_must_satisfy_min_context_slot() -> None:
    rpc = FakeRpc(
        {
            "getBlockHeight": [50],
            "isBlockhashValid": [_blockhash_valid(slot=10, value=True)],
        }
    )

    with pytest.raises(ExactSimulationError, match="isBlockhashValid") as captured:
        await ExactSimulationFinalizer(rpc).finalize(
            _plan(Keypair().pubkey()),
            _blockhash(),
        )

    assert captured.value.code == ExactSimulationErrorCode.CONTEXT_SLOT_VIOLATION
    assert captured.value.disposition == FailureDisposition.RETRYABLE


@pytest.mark.asyncio
async def test_one_byte_mutation_invalidates_final_report() -> None:
    finalized = await ExactSimulationFinalizer(_success_rpc()).finalize(
        _plan(Keypair().pubkey()),
        _blockhash(),
    )

    with pytest.raises(
        ExactSimulationError,
        match="no longer matches final simulation",
    ) as captured:
        finalized.report.validate_message_bytes(
            finalized.compiled.serialized_message + b"x"
        )

    assert captured.value.code == ExactSimulationErrorCode.MESSAGE_IDENTITY_MISMATCH
    assert captured.value.disposition == FailureDisposition.FATAL


@pytest.mark.asyncio
async def test_permit_and_submission_must_match_final_simulation() -> None:
    finalized = await ExactSimulationFinalizer(_success_rpc()).finalize(
        _plan(Keypair().pubkey()),
        _blockhash(),
    )

    validate_exact_submission_binding(
        finalized,
        permit_message_hash=finalized.report.message_hash,
        submission_message_hash=finalized.report.message_hash,
        serialized_submission_message=finalized.compiled.serialized_message,
    )

    with pytest.raises(ExactSimulationError, match="permit hash"):
        validate_exact_submission_binding(
            finalized,
            permit_message_hash="0" * 64,
            submission_message_hash=finalized.report.message_hash,
        )


@pytest.mark.asyncio
async def test_expired_blockhash_is_retryable_and_never_simulated() -> None:
    rpc = FakeRpc({"getBlockHeight": [101]})

    with pytest.raises(ExactSimulationError, match="blockhash is expired") as captured:
        await ExactSimulationFinalizer(rpc).finalize(
            _plan(Keypair().pubkey()),
            _blockhash(last_valid_block_height=100),
        )

    assert captured.value.code == ExactSimulationErrorCode.BLOCKHASH_EXPIRED
    assert captured.value.disposition == FailureDisposition.RETRYABLE
    assert [method for method, _ in rpc.calls] == ["getBlockHeight"]


@pytest.mark.asyncio
async def test_blockhash_expiry_between_passes_forces_rebuild() -> None:
    rpc = FakeRpc(
        {
            "getBlockHeight": [50, 101],
            "isBlockhashValid": [_blockhash_valid(slot=21)],
            "simulateTransaction": [_simulation(slot=21, units=200_000)],
        }
    )

    with pytest.raises(ExactSimulationError) as captured:
        await ExactSimulationFinalizer(rpc).finalize(
            _plan(Keypair().pubkey()),
            _blockhash(last_valid_block_height=100),
        )

    assert captured.value.code == ExactSimulationErrorCode.BLOCKHASH_EXPIRED
    assert [method for method, _ in rpc.calls] == [
        "getBlockHeight",
        "isBlockhashValid",
        "simulateTransaction",
        "getBlockHeight",
    ]


@pytest.mark.asyncio
async def test_targeted_account_return_limit_is_enforced_before_rpc() -> None:
    payer = Keypair().pubkey()
    monitored = (Keypair().pubkey(), Keypair().pubkey())
    finalizer = ExactSimulationFinalizer(
        FakeRpc({}),
        policy=ExactSimulationPolicy(max_return_accounts=2),
    )

    with pytest.raises(ExactSimulationError, match="account limit") as captured:
        await finalizer.finalize(
            _plan(payer, monitored=monitored),
            _blockhash(),
        )

    assert captured.value.code == ExactSimulationErrorCode.ACCOUNT_LIMIT_EXCEEDED
    assert captured.value.disposition == FailureDisposition.FATAL


@pytest.mark.asyncio
async def test_rpc_must_return_exact_targeted_account_count() -> None:
    rpc = FakeRpc(
        {
            "getBlockHeight": [50],
            "isBlockhashValid": [_blockhash_valid(slot=21)],
            "simulateTransaction": [
                _simulation(slot=21, units=200_000, account_count=0),
            ],
        }
    )

    with pytest.raises(ExactSimulationError, match="targeted account") as captured:
        await ExactSimulationFinalizer(rpc).finalize(
            _plan(Keypair().pubkey()),
            _blockhash(),
        )

    assert captured.value.code == ExactSimulationErrorCode.ACCOUNT_LIMIT_EXCEEDED
    assert captured.value.disposition == FailureDisposition.RETRYABLE


@pytest.mark.asyncio
async def test_wire_and_transaction_account_caps_are_enforced() -> None:
    payer = Keypair().pubkey()

    with pytest.raises(ExactSimulationError) as wire_error:
        await ExactSimulationFinalizer(
            FakeRpc(
                {
                    "getBlockHeight": [50],
                    "isBlockhashValid": [_blockhash_valid(slot=21)],
                }
            ),
            policy=ExactSimulationPolicy(max_wire_bytes=1),
        ).finalize(_plan(payer), _blockhash())
    assert wire_error.value.code == ExactSimulationErrorCode.WIRE_SIZE_EXCEEDED

    with pytest.raises(ExactSimulationError) as account_error:
        await ExactSimulationFinalizer(
            FakeRpc(
                {
                    "getBlockHeight": [50],
                    "isBlockhashValid": [_blockhash_valid(slot=21)],
                }
            ),
            policy=ExactSimulationPolicy(max_transaction_accounts=1),
        ).finalize(_plan(payer), _blockhash())
    assert account_error.value.code == ExactSimulationErrorCode.ACCOUNT_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_loaded_account_byte_cap_is_enforced() -> None:
    rpc = FakeRpc(
        {
            "getBlockHeight": [50],
            "isBlockhashValid": [_blockhash_valid(slot=21)],
            "simulateTransaction": [
                _simulation(slot=21, units=200_000, loaded_size=1_025),
            ],
        }
    )

    with pytest.raises(ExactSimulationError) as captured:
        await ExactSimulationFinalizer(
            rpc,
            policy=ExactSimulationPolicy(max_loaded_accounts_data_size=1_024),
        ).finalize(_plan(Keypair().pubkey()), _blockhash())

    assert captured.value.code == ExactSimulationErrorCode.LOADED_ACCOUNT_BYTES_EXCEEDED
    assert captured.value.disposition == FailureDisposition.FATAL


@pytest.mark.asyncio
async def test_timeout_and_unknown_success_shape_fail_closed() -> None:
    timeout_rpc = FakeRpc({"getBlockHeight": [TimeoutError()]})
    with pytest.raises(ExactSimulationError) as timeout_error:
        await ExactSimulationFinalizer(timeout_rpc).finalize(
            _plan(Keypair().pubkey()),
            _blockhash(),
        )
    assert timeout_error.value.code == ExactSimulationErrorCode.RPC_TIMEOUT
    assert timeout_error.value.disposition == FailureDisposition.RETRYABLE

    malformed_rpc = FakeRpc(
        {
            "getBlockHeight": [50],
            "isBlockhashValid": [_blockhash_valid(slot=21)],
            "simulateTransaction": [
                _simulation(slot=21, units=None),
            ],
        }
    )
    with pytest.raises(ExactSimulationError) as malformed_error:
        await ExactSimulationFinalizer(malformed_rpc).finalize(
            _plan(Keypair().pubkey()),
            _blockhash(),
        )
    assert malformed_error.value.code == ExactSimulationErrorCode.MALFORMED_RPC_RESPONSE


@pytest.mark.asyncio
async def test_null_fee_and_stale_context_never_become_success() -> None:
    null_fee_rpc = FakeRpc(
        {
            "getBlockHeight": [50, 51],
            "isBlockhashValid": [_blockhash_valid(slot=21), _blockhash_valid(slot=22)],
            "simulateTransaction": [
                _simulation(slot=21, units=200_000),
                _simulation(slot=22, units=210_000),
            ],
            "getFeeForMessage": [
                {"context": {"slot": 23}, "value": None},
            ],
        }
    )
    with pytest.raises(ExactSimulationError) as fee_error:
        await ExactSimulationFinalizer(null_fee_rpc).finalize(
            _plan(Keypair().pubkey()),
            _blockhash(),
        )
    assert fee_error.value.code == ExactSimulationErrorCode.FEE_UNAVAILABLE
    assert fee_error.value.disposition == FailureDisposition.RETRYABLE

    stale_rpc = FakeRpc(
        {
            "getBlockHeight": [50],
            "isBlockhashValid": [_blockhash_valid(slot=21)],
            "simulateTransaction": [
                _simulation(slot=10, units=200_000),
            ],
        }
    )
    with pytest.raises(ExactSimulationError) as stale_error:
        await ExactSimulationFinalizer(stale_rpc).finalize(
            _plan(Keypair().pubkey()),
            _blockhash(),
        )
    assert stale_error.value.code == ExactSimulationErrorCode.CONTEXT_SLOT_VIOLATION


@pytest.mark.asyncio
async def test_program_failure_is_fatal_but_blockhash_error_is_retryable() -> None:
    errors: dict[str, list[FailureDisposition]] = defaultdict(list)
    for name, provider_error in (
        ("program", {"InstructionError": [0, "Custom"]}),
        ("blockhash", "BlockhashNotFound"),
    ):
        rpc = FakeRpc(
            {
                "getBlockHeight": [50],
                "isBlockhashValid": [_blockhash_valid(slot=21)],
                "simulateTransaction": [
                    _simulation(slot=21, units=1, error=provider_error),
                ],
            }
        )
        with pytest.raises(ExactSimulationError) as captured:
            await ExactSimulationFinalizer(rpc).finalize(
                _plan(Keypair().pubkey()),
                _blockhash(),
            )
        errors[name].append(captured.value.disposition)

    assert errors == {
        "program": [FailureDisposition.FATAL],
        "blockhash": [FailureDisposition.RETRYABLE],
    }
