from __future__ import annotations

from dataclasses import replace

import pytest
from solders.address_lookup_table_account import (
    ID as ADDRESS_LOOKUP_TABLE_ID,
    AddressLookupTable,
    LookupTableMeta,
)
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer

from src.execution import (
    AltValidator,
    BlockhashContext,
    CompileRuntimeContext,
    ComputeBudgetPolicy,
    HardenedV0Compiler,
    PlannedInstruction,
    TipPolicy,
    TransactionPlan,
    V0CompileFailureReason,
    V0CompilePolicy,
    V0HardeningError,
)


def _kp(seed: int) -> Keypair:
    return Keypair.from_seed(bytes([seed]) * 32)


PAYER = _kp(31)
RECIPIENT = _kp(32).pubkey()
ALT_A = _kp(33).pubkey()
ALT_B = _kp(34).pubkey()
BLOCKHASH = Hash.from_string("4vJ9JU1bJJE96FwsLAZ2uK3F9Uwh9qF7XHDNK9KHdxhU")


def _blockhash(
    *, last_valid: int = 1_000, fetched_at: float = 100.0
) -> BlockhashContext:
    return BlockhashContext(
        blockhash=BLOCKHASH,
        last_valid_block_height=last_valid,
        source_slot=90,
        fetched_at=fetched_at,
        commitment="confirmed",
    )


def _context(
    *,
    height: int = 900,
    slot: int = 100,
    observed_at: float = 110.0,
) -> CompileRuntimeContext:
    return CompileRuntimeContext(
        current_block_height=height,
        current_slot=slot,
        observed_at=observed_at,
    )


def _plan(
    *,
    lookup_tables: tuple[Pubkey, ...] = (),
    required_lookup: tuple[Pubkey, ...] = (),
    extra_accounts: tuple[Pubkey, ...] = (),
) -> TransactionPlan:
    ix = transfer(
        TransferParams(
            from_pubkey=PAYER.pubkey(),
            to_pubkey=RECIPIENT,
            lamports=1,
        )
    )
    if extra_accounts:
        ix = Instruction(
            Pubkey.new_unique(),
            b"pr035",
            [
                AccountMeta(PAYER.pubkey(), True, True),
                *[AccountMeta(key, False, False) for key in extra_accounts],
            ],
        )
    return TransactionPlan(
        opportunity_id="pr035",
        payer=PAYER.pubkey(),
        instructions=(PlannedInstruction(ix, "application", "transfer"),),
        compute_budget_policy=ComputeBudgetPolicy(300_000, 1),
        tip_policy=TipPolicy(),
        required_signers=(PAYER.pubkey(),),
        lookup_table_addresses=lookup_tables,
        required_lookup_addresses=required_lookup,
        quote_slot=80,
        market_state_slot=81,
        oracle_slot=82,
        monitored_accounts=(PAYER.pubkey(), RECIPIENT),
    )


def _alt_raw(
    addresses: tuple[Pubkey, ...],
    *,
    deactivation_slot: int = 2**64 - 1,
    last_extended_slot: int = 70,
) -> bytes:
    meta = LookupTableMeta(deactivation_slot, last_extended_slot, 0, None, 0)
    return bytes(AddressLookupTable(meta, list(addresses)))


def _resolved_alt(
    key: Pubkey,
    addresses: tuple[Pubkey, ...],
    *,
    source_slot: int = 90,
    deactivation_slot: int = 2**64 - 1,
    last_extended_slot: int = 70,
):
    return AltValidator().deserialize(
        key,
        _alt_raw(
            addresses,
            deactivation_slot=deactivation_slot,
            last_extended_slot=last_extended_slot,
        ),
        ADDRESS_LOOKUP_TABLE_ID,
        source_slot,
        addresses,
        deactivation_slot=deactivation_slot,
    )


def test_hardened_compile_produces_deterministic_v0_proof() -> None:
    compiler = HardenedV0Compiler()
    first = compiler.compile(_plan(), _blockhash(), runtime_context=_context())
    second = compiler.compile(_plan(), _blockhash(), runtime_context=_context())

    assert first.compiled.message_hash == second.compiled.message_hash
    assert first.fingerprints == second.fingerprints
    assert first.compiled.diagnostics.wire_size <= 1232
    compiler.revalidate(first, _plan(), runtime_context=_context())


def test_blockhash_near_expiry_is_retryable() -> None:
    with pytest.raises(V0HardeningError) as raised:
        HardenedV0Compiler().compile(
            _plan(),
            _blockhash(last_valid=910),
            runtime_context=_context(height=900),
        )

    assert raised.value.reason is V0CompileFailureReason.BLOCKHASH_NEAR_EXPIRY
    assert raised.value.retryable is True


def test_blockhash_age_and_future_slot_fail_closed() -> None:
    with pytest.raises(V0HardeningError) as stale:
        HardenedV0Compiler().compile(
            _plan(),
            _blockhash(fetched_at=1.0),
            runtime_context=_context(observed_at=100.0),
        )
    assert stale.value.reason is V0CompileFailureReason.BLOCKHASH_STALE

    future = replace(_blockhash(), source_slot=101)
    with pytest.raises(V0HardeningError) as ahead:
        HardenedV0Compiler().compile(
            _plan(),
            future,
            runtime_context=_context(slot=100),
        )
    assert ahead.value.reason is V0CompileFailureReason.BLOCKHASH_SLOT_AHEAD


def test_lookup_tables_must_match_plan_order_and_context() -> None:
    lookup_a = _resolved_alt(ALT_A, (RECIPIENT,))
    lookup_b = _resolved_alt(ALT_B, (Pubkey.new_unique(),))
    plan = _plan(
        lookup_tables=(ALT_A, ALT_B),
        required_lookup=(RECIPIENT,),
    )

    with pytest.raises(V0HardeningError) as raised:
        HardenedV0Compiler().compile(
            plan,
            _blockhash(),
            (lookup_b, lookup_a),
            runtime_context=_context(),
        )
    assert raised.value.reason is V0CompileFailureReason.ALT_ORDER_MISMATCH

    stale = replace(lookup_a, source_slot=70)
    with pytest.raises(V0HardeningError) as stale_error:
        HardenedV0Compiler().compile(
            _plan(lookup_tables=(ALT_A,), required_lookup=(RECIPIENT,)),
            _blockhash(),
            (stale,),
            runtime_context=_context(),
        )
    assert stale_error.value.reason is V0CompileFailureReason.ALT_CONTEXT_STALE


def test_deactivated_lookup_table_is_rejected() -> None:
    lookup = replace(
        _resolved_alt(ALT_A, (RECIPIENT,)),
        deactivation_slot=99,
    )
    with pytest.raises(V0HardeningError) as raised:
        HardenedV0Compiler().compile(
            _plan(lookup_tables=(ALT_A,), required_lookup=(RECIPIENT,)),
            _blockhash(),
            (lookup,),
            runtime_context=_context(),
        )
    assert raised.value.reason is V0CompileFailureReason.ALT_DEACTIVATED


def test_account_lock_policy_returns_structured_retry_reason() -> None:
    policy = V0CompilePolicy(max_account_locks=1)
    with pytest.raises(V0HardeningError) as raised:
        HardenedV0Compiler(policy).compile(
            _plan(extra_accounts=(Pubkey.new_unique(), Pubkey.new_unique())),
            _blockhash(),
            runtime_context=_context(),
        )

    assert raised.value.reason is V0CompileFailureReason.ACCOUNT_LOCK_LIMIT
    assert raised.value.retryable is True
    assert raised.value.diagnostics["actual_count"] > 1


def test_plan_change_after_compile_invalidates_proof() -> None:
    compiler = HardenedV0Compiler()
    original = _plan()
    hardened = compiler.compile(
        original,
        _blockhash(),
        runtime_context=_context(),
    )
    changed = replace(
        original,
        compute_budget_policy=ComputeBudgetPolicy(400_000, 1),
    )

    with pytest.raises(V0HardeningError) as raised:
        compiler.revalidate(hardened, changed, runtime_context=_context())

    assert raised.value.reason is V0CompileFailureReason.PLAN_MUTATED
    assert raised.value.retryable is False
