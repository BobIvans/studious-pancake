import base64
import pytest

from solders.address_lookup_table_account import (
    AddressLookupTable,
    AddressLookupTableAccount,
    LookupTableMeta,
    ID as ADDRESS_LOOKUP_TABLE_ID,
)
from solders.compute_budget import (
    ID as COMPUTE_BUDGET_ID,
    set_compute_unit_limit,
    set_compute_unit_price,
)
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0, from_bytes_versioned, to_bytes_versioned
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_ID, TransferParams, transfer
from solders.transaction import VersionedTransaction

from src.execution import (
    AltValidator,
    BlockhashContext,
    CompiledTransaction,
    ComputeBudgetPolicy,
    ExecutionErrorCode,
    InMemoryExecutionJournal,
    PlannedInstruction,
    SubmissionResult,
    TipPolicy,
    TransactionCompileError,
    TransactionCompiler,
    TransactionPlan,
    TransactionSimulator,
    get_fee_for_message,
)
from src.execution.state_machine import ExecutionStateMachine


def kp(seed: int) -> Keypair:
    return Keypair.from_seed(bytes([seed]) * 32)


PAYER = kp(1)
RECIPIENT = kp(2).pubkey()
ALT_KEY = kp(3).pubkey()
BLOCKHASH = Hash.from_string("4vJ9JU1bJJE96FwsLAZ2uK3F9Uwh9qF7XHDNK9KHdxhU")
BLOCKHASH2 = Hash.from_string("8opHzTAnfzRpPEx21XtnrVTX28YQuCpAjcn1PczScKh")


def bh(h=BLOCKHASH):
    return BlockhashContext(h, 999, 50, 1.0, "processed")


def transfer_ix(to=RECIPIENT, lamports=1, signer=None):
    return transfer(
        TransferParams(
            from_pubkey=(signer or PAYER.pubkey()), to_pubkey=to, lamports=lamports
        )
    )


def memo_ix(data=b"opaque", extra=None):
    metas = [AccountMeta(PAYER.pubkey(), True, True)]
    if extra:
        metas.append(extra)
    return Instruction(Pubkey.new_unique(), bytes(data), metas)


def plan(
    *,
    ixs=None,
    cb=ComputeBudgetPolicy(400_000, 10),
    tip=TipPolicy(),
    signers=None,
    alts=(),
    required_lookup=(),
):
    return TransactionPlan(
        "opp",
        PAYER.pubkey(),
        tuple(
            PlannedInstruction(ix, "application", "ix")
            for ix in (ixs or [transfer_ix()])
        ),
        cb,
        tip,
        tuple(signers or (PAYER.pubkey(),)),
        tuple(alts),
        tuple(required_lookup),
        7,
        8,
        9,
        (PAYER.pubkey(), RECIPIENT),
    )


def alt_raw(addresses, *, deactivation=2**64 - 1, last_extended_slot=1):
    meta = LookupTableMeta(deactivation, last_extended_slot, 0, None, 0)
    return bytes(AddressLookupTable(meta, list(addresses)))


def resolved_alt(addresses=(RECIPIENT,), source_slot=50):
    return AltValidator().deserialize(
        ALT_KEY, alt_raw(addresses), ADDRESS_LOOKUP_TABLE_ID, source_slot, addresses
    )


def compile_default(**kwargs) -> CompiledTransaction:
    return TransactionCompiler().compile(
        plan(**kwargs), bh(), tuple(kwargs.get("lookup_tables", ()))
    )


def test_real_system_transfer_compiles_to_v0_and_round_trips():
    c = TransactionCompiler().compile(plan(), bh())
    assert c.message.header.num_required_signatures == 1
    assert c.required_signers == (PAYER.pubkey(),)
    assert c.message.account_keys[0] == PAYER.pubkey()
    assert c.serialized_message == bytes(to_bytes_versioned(c.message))
    assert from_bytes_versioned(c.serialized_message) == c.message
    tx = VersionedTransaction.from_bytes(c.serialized_transaction)
    tx.sanitize()
    assert tx.version() == 0
    assert b"unsigned:" not in c.serialized_transaction
    assert b"limit:" not in c.serialized_transaction
    assert c.instructions[-1].program_id == SYSTEM_ID
    assert c.message_hash


def test_compute_budget_and_tip_golden_ordering():
    tip_account = kp(4).pubkey()
    c = TransactionCompiler().compile(plan(tip=TipPolicy(123, tip_account)), bh())
    assert bytes(c.instructions[0]) == bytes(set_compute_unit_limit(400_000))
    assert bytes(c.instructions[1]) == bytes(set_compute_unit_price(10))
    assert bytes(c.instructions[-1]) == bytes(
        transfer(
            TransferParams(
                from_pubkey=PAYER.pubkey(), to_pubkey=tip_account, lamports=123
            )
        )
    )
    no_tip = TransactionCompiler().compile(plan(tip=TipPolicy(0, tip_account)), bh())
    assert len(no_tip.instructions) == 3


@pytest.mark.parametrize(
    "bad",
    [
        PlannedInstruction(set_compute_unit_limit(1), "application"),
        PlannedInstruction(transfer_ix(), "tip"),
    ],
)
def test_duplicate_compiler_owned_instructions_rejected(bad):
    p = TransactionPlan(
        "opp",
        PAYER.pubkey(),
        (bad,),
        ComputeBudgetPolicy(400_000, 10),
        required_signers=(PAYER.pubkey(),),
    )
    with pytest.raises(TransactionCompileError) as e:
        TransactionCompiler().compile(p, bh())
    assert e.value.code == ExecutionErrorCode.INVALID_PLAN


@pytest.mark.parametrize(
    "cb,tip",
    [
        (ComputeBudgetPolicy(0, 1), TipPolicy()),
        (ComputeBudgetPolicy(1_400_001, 1), TipPolicy()),
        (ComputeBudgetPolicy(1, -1), TipPolicy()),
        (ComputeBudgetPolicy(1, 1), TipPolicy(-1, None)),
        (ComputeBudgetPolicy(1, 1), TipPolicy(1, None)),
    ],
)
def test_invalid_policy_rejected(cb, tip):
    with pytest.raises(TransactionCompileError):
        TransactionCompiler().compile(plan(cb=cb, tip=tip), bh())


def test_sign_fully_single_and_message_hash_stable():
    compiler = TransactionCompiler()
    c = compiler.compile(plan(), bh())
    s = compiler.sign_fully(c, [PAYER])
    assert s.is_fully_signed
    assert all(s.versioned_transaction.verify_with_results())
    assert (
        bytes(to_bytes_versioned(s.versioned_transaction.message))
        == c.serialized_message
    )
    assert s.message_hash == c.message_hash


def test_multi_signer_requires_exact_set_and_rejects_bad_sets():
    other = kp(5)
    ix = Instruction(
        Pubkey.new_unique(),
        b"x",
        [
            AccountMeta(PAYER.pubkey(), True, True),
            AccountMeta(other.pubkey(), True, False),
        ],
    )
    c = TransactionCompiler().compile(
        plan(ixs=[ix], signers=(PAYER.pubkey(), other.pubkey())), bh()
    )
    compiler = TransactionCompiler()
    assert compiler.sign_fully(c, [other, PAYER]).is_fully_signed
    for signers in ([PAYER], [PAYER, PAYER], [PAYER, kp(6)]):
        with pytest.raises(TransactionCompileError):
            compiler.sign_fully(c, signers)


def test_unsigned_envelope_not_allowed_for_sigverify_simulation():
    class Rpc:
        async def call(self, method, params):
            if method == "getMultipleAccounts":
                return {"value": []}
            return {"context": {"slot": 1}, "value": {"err": None, "accounts": []}}

    with pytest.raises(ValueError):
        import asyncio

        asyncio.run(
            TransactionSimulator(Rpc()).simulate(
                TransactionCompiler().compile(plan(), bh()), final_signed=True
            )
        )


def test_blockhash_change_changes_hash():
    c1 = TransactionCompiler().compile(plan(), bh(BLOCKHASH))
    c2 = TransactionCompiler().compile(plan(), bh(BLOCKHASH2))
    assert c1.message_hash != c2.message_hash


def test_alt_binary_fixture_parses_and_compiles_lookup():
    alt = resolved_alt((RECIPIENT,))
    ix = Instruction(
        Pubkey.new_unique(),
        b"x",
        [AccountMeta(PAYER.pubkey(), True, True), AccountMeta(RECIPIENT, False, False)],
    )
    c = TransactionCompiler().compile(
        plan(ixs=[ix], alts=(ALT_KEY,), required_lookup=(RECIPIENT,)), bh(), (alt,)
    )
    assert c.message.address_table_lookups
    assert c.diagnostics.lookup_readonly_count == 1
    assert c.diagnostics.used_alt_pubkeys == (ALT_KEY,)


@pytest.mark.parametrize(
    "raw,owner,source,required",
    [
        (b"a\nb", ADDRESS_LOOKUP_TABLE_ID, 50, ()),
        (alt_raw(()), ADDRESS_LOOKUP_TABLE_ID, 50, ()),
        (alt_raw((RECIPIENT, RECIPIENT)), ADDRESS_LOOKUP_TABLE_ID, 50, ()),
        (alt_raw((RECIPIENT,), deactivation=1), ADDRESS_LOOKUP_TABLE_ID, 50, ()),
        (alt_raw((RECIPIENT,), last_extended_slot=50), ADDRESS_LOOKUP_TABLE_ID, 50, ()),
        (alt_raw((RECIPIENT,)), Pubkey.new_unique(), 50, ()),
        (alt_raw((RECIPIENT,)), ADDRESS_LOOKUP_TABLE_ID, 50, (kp(9).pubkey(),)),
    ],
)
def test_alt_rejects_invalid_states(raw, owner, source, required):
    with pytest.raises(TransactionCompileError):
        AltValidator().deserialize(ALT_KEY, raw, owner, source, required)


def test_signer_stays_static_even_if_in_alt():
    other = kp(10)
    alt = resolved_alt((other.pubkey(),))
    ix = Instruction(
        Pubkey.new_unique(),
        b"x",
        [
            AccountMeta(PAYER.pubkey(), True, True),
            AccountMeta(other.pubkey(), True, False),
        ],
    )
    c = TransactionCompiler().compile(
        plan(ixs=[ix], signers=(PAYER.pubkey(), other.pubkey()), alts=(ALT_KEY,)),
        bh(),
        (alt,),
    )
    assert (
        other.pubkey()
        in c.message.account_keys[: c.message.header.num_required_signatures]
    )


def test_oversize_typed_error_has_diagnostics_and_counts_signatures():
    big_ixs = [
        memo_ix(bytes([i % 255]) * 90, AccountMeta(Pubkey.new_unique(), False, False))
        for i in range(20)
    ]
    with pytest.raises(TransactionCompileError) as e:
        TransactionCompiler().compile(plan(ixs=big_ixs), bh())
    assert e.value.code == ExecutionErrorCode.TRANSACTION_TOO_LARGE
    assert e.value.diagnostics["actual_size"] > 1232
    assert e.value.diagnostics["required_signature_count"] == 1


def test_determinism_and_mutations_change_hash():
    compiler = TransactionCompiler()
    p = plan(ixs=[memo_ix(b"a")])
    assert (
        compiler.compile(p, bh()).message_hash == compiler.compile(p, bh()).message_hash
    )
    assert (
        compiler.compile(plan(ixs=[memo_ix(b"b")]), bh()).message_hash
        != compiler.compile(p, bh()).message_hash
    )
    assert (
        compiler.compile(
            plan(
                ixs=[
                    Instruction(
                        Pubkey.new_unique(),
                        b"a",
                        [AccountMeta(PAYER.pubkey(), True, False)],
                    )
                ]
            ),
            bh(),
        ).message_hash
        != compiler.compile(p, bh()).message_hash
    )


def test_default_blockhash_and_string_boundary_rejected():
    with pytest.raises(TransactionCompileError):
        TransactionCompiler().compile(plan(), bh(Hash.default()))
    bad = TransactionPlan(
        "opp", "payer", (), ComputeBudgetPolicy(1, 1), required_signers=("payer",)
    )
    with pytest.raises(TransactionCompileError):
        TransactionCompiler().compile(bad, bh())


REPORTED_CONFLICT_FILES = (
    "docs/external_contracts.yaml",
    "src/execution/__init__.py",
    "src/execution/transaction_compiler.py",
    "src/execution/transaction_simulator.py",
    "tests/execution/test_transaction_lifecycle.py",
)


def test_execution_conflict_files_have_no_markers():
    conflict_files = REPORTED_CONFLICT_FILES
    for filename in conflict_files:
        src = open(filename, encoding="utf-8").read()
        assert ("<" * 7) not in src
        assert ("=" * 7) not in src
        assert (">" * 7) not in src


def test_compiler_source_has_no_provider_or_live_imports():
    src = open("src/execution/transaction_compiler.py", encoding="utf-8").read()
    lower = src.lower()
    forbidden_words = ("marginfi", "jupiter", "send_transaction", "send_bundle")
    forbidden_words += ("os.environ", "getenv", "_pass2", "_serialize_message")
    forbidden_bytes = (b"unsigned" + b":", b"end_index" + b":")
    forbidden_bytes += (b"limit" + b":", b"price" + b":", b"tip" + b":")
    for forbidden in forbidden_words:
        assert forbidden not in lower
    for forbidden in forbidden_bytes:
        assert forbidden.decode() not in src


def test_rpc_shapes_for_simulate_and_fee_message():
    c = TransactionCompiler().compile(plan(), bh())

    class Rpc:
        def __init__(self):
            self.calls = []

        async def call(self, method, params):
            self.calls.append((method, params))
            if method == "getMultipleAccounts":
                return {"value": []}
            if method == "getFeeForMessage":
                return {"value": 5000}
            raw = base64.b64decode(params[0])
            VersionedTransaction.from_bytes(raw).sanitize()
            assert params[1]["sigVerify"] is False
            return {"context": {"slot": 11}, "value": {"err": None, "accounts": []}}

    import asyncio

    rpc = Rpc()
    report = asyncio.run(TransactionSimulator(rpc).simulate(c, final_signed=False))
    assert report.transaction_message_hash == c.message_hash
    assert asyncio.run(get_fee_for_message(rpc, c.serialized_message)) == 5000
    fee_call = [call for call in rpc.calls if call[0] == "getFeeForMessage"][0]
    assert base64.b64decode(fee_call[1][0]) == c.serialized_message


def test_state_machine_terminal_states_never_submit():
    sm = ExecutionStateMachine()
    from src.execution import ExecutionState

    assert sm.can_transition(ExecutionState.REJECTED, ExecutionState.SUBMITTED) is False


def test_message_hash_can_be_submitted_only_once():
    import asyncio

    j = InMemoryExecutionJournal()
    assert asyncio.run(j.reserve_submission("opp", "hash")) is True
    assert asyncio.run(j.reserve_submission("opp", "hash")) is False


def test_dependency_versions_and_symbols_importable():
    import solana, solders

    assert getattr(solana, "__version__", "0.40.1") in {"0.40.1", "solana import ok"}
    assert solders.__version__ == "0.28.0"
    assert MessageV0 and VersionedTransaction and AddressLookupTableAccount
