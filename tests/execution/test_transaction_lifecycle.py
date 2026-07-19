import pytest
from src.execution import *
from src.execution.jito_status import parse_inflight_bundle_status
from src.execution.senders.jito_bundle_sender import JitoBundleSender
from src.execution.senders.jito_single_sender import JitoSingleTransactionSender
from src.execution.transaction_compiler import ADDRESS_LOOKUP_TABLE_PROGRAM_ID

BH = BlockhashContext("So11111111111111111111111111111111111111112", 99, 10, 0.0, "processed")

def ix(name, kind="generic", accounts=("a",), program="Prog"):
    return Instruction(program, accounts, name.encode(), name, kind)

def plan(setup=(), cleanup=(), tip=0, alt=()):
    fl = FlashLoanPlan("mfi", "payer", "group", ix("borrow", "marginfi_borrow"), ix("repay", "marginfi_repay"), ix("end", "marginfi_end"), ("bal",), ("bank", "oracle"), marginfi_bank_slot=12)
    return TransactionPlan("opp", "payer", ComputeBudgetPolicy(400000, 10), setup, fl, (ix("swap", accounts=("usdc_ata","wsol_ata")),), cleanup, TipPolicy(tip, "tipacct" if tip else None), ("payer",), alt, 7, 8, 9, ("payer", "usdc_ata", "wsol_ata"))

def test_marginfi_end_index_matches_final_instruction_position():
    c = TransactionCompiler().compile(plan(tip=1000), BH)
    assert c.instructions[c.marginfi_end_index].kind == "marginfi_end"
    assert c.instructions[c.marginfi_end_index - 1].kind == "marginfi_repay"
    assert c.instructions[c.marginfi_end_index + 1].kind == "tip"
    assert c.instructions[2].data == f"end_index:{c.marginfi_end_index}".encode()

def test_end_index_changes_after_setup_instruction_added():
    c1 = TransactionCompiler().compile(plan(), BH)
    c2 = TransactionCompiler().compile(plan(setup=(ix("setup"),)), BH)
    assert c2.marginfi_end_index == c1.marginfi_end_index + 1

def test_projected_active_balances_are_passed_to_marginfi_end():
    c = TransactionCompiler().compile(plan(), BH)
    assert c.instructions[c.marginfi_end_index].accounts[:1] == ("bal",)

@pytest.mark.parametrize("bad_ix", [ix("cb", program="ComputeBudget111111111111111111111111111111"), ix("sender", kind="sender")])
def test_duplicate_compute_budget_and_sender_are_rejected(bad_ix):
    with pytest.raises(Exception):
        TransactionCompiler().compile(plan(setup=(bad_ix,)), BH)

def test_default_blockhash_is_rejected():
    with pytest.raises(ValueError):
        TransactionCompiler().compile(plan(), BlockhashContext("11111111111111111111111111111111", 1, 1, 0, "processed"))

def test_transaction_over_1232_bytes_is_rejected():
    big = ix("big", accounts=("x"*1400,))
    with pytest.raises(Exception):
        TransactionCompiler().compile(plan(setup=(big,)), BH)

def test_empty_alt_and_unresolved_alt_are_rejected():
    empty = ResolvedAddressLookupTable("ALT", ADDRESS_LOOKUP_TABLE_PROGRAM_ID, (), None, 1, "h")
    with pytest.raises(Exception): TransactionCompiler().compile(plan(alt=("ALT",)), BH, (empty,))
    with pytest.raises(Exception): TransactionCompiler().compile(plan(alt=("ALT",)), BH, ())

def test_alt_uses_library_deserializer_and_preserves_source_slot():
    alt = AltValidator().deserialize("ALT", b"needed\n", ADDRESS_LOOKUP_TABLE_PROGRAM_ID, 55, ["needed"])
    assert alt.library_deserialized and alt.source_slot == 55 and alt.addresses == ("needed",)

def test_manual_header_offset_decoder_is_removed():
    import inspect, src.execution.transaction_compiler as tc
    assert "header_len" not in inspect.getsource(tc)
    assert "raw[21]" not in inspect.getsource(tc)

def test_deactivated_and_missing_lookup_address_rejected():
    with pytest.raises(Exception): AltValidator().deserialize("ALT", b"needed\n", ADDRESS_LOOKUP_TABLE_PROGRAM_ID, 1, ["needed"], deactivation_slot=42)
    with pytest.raises(Exception): AltValidator().deserialize("ALT", b"other\n", ADDRESS_LOOKUP_TABLE_PROGRAM_ID, 1, ["needed"])

def test_state_machine_terminal_states_never_submit():
    sm = ExecutionStateMachine()
    for state in (ExecutionState.LANDED, ExecutionState.FAILED, ExecutionState.RECONCILED):
        assert not sm.can_transition(state, ExecutionState.SUBMITTED)
        with pytest.raises(ValueError): sm.transition(state, ExecutionState.SUBMITTED)

@pytest.mark.asyncio
async def test_simulator_does_not_expect_preBalances_and_binds_hash():
    class Rpc:
        async def call(self, method, params):
            if method == "getMultipleAccounts":
                return {"value": [{"lamports": 10, "owner": "o", "data": ["", "base64"]} for _ in params[0]]}
            assert method == "simulateTransaction"
            assert params[1]["accounts"]["addresses"]
            return {"context": {"slot": 12}, "value": {"err": None, "logs": ["ok"], "unitsConsumed": 123, "accounts": [{"lamports": 11, "owner": "o", "data": ["", "base64"]} for _ in params[1]["accounts"]["addresses"]]}}
    c = TransactionCompiler().compile(plan(), BH)
    report = await TransactionSimulator(Rpc()).simulate(c, final_signed=True, estimated_network_fee=5)
    assert report.transaction_message_hash == c.message_hash
    assert report.units_consumed == 123
    assert report.native_delta_before_fee > 0

@pytest.mark.asyncio
async def test_missing_fee_estimate_fails_closed():
    class Rpc:
        async def call(self, method, params): return {"value": None}
    c = TransactionCompiler().compile(plan(), BH)
    assert await get_fee_for_message(Rpc(), c.serialized_message) is None

@pytest.mark.asyncio
async def test_message_hash_can_be_submitted_only_once():
    j = InMemoryExecutionJournal()
    assert await j.reserve_submission("opp", "hash") is True
    assert await j.reserve_submission("opp", "hash") is False

def test_jito_status_parsing_acceptance_is_not_landing():
    assert parse_inflight_bundle_status({"status":"Pending"}).landed is False
    landed = parse_inflight_bundle_status({"status":"Landed", "landed_slot": 9})
    assert landed.landed and landed.landed_slot == 9
    assert parse_inflight_bundle_status({"status":"Invalid"}).error_code == ExecutionErrorCode.BUNDLE_INVALID

@pytest.mark.asyncio
async def test_jito_uses_base64_bundle_only_and_bundle_limit():
    calls=[]
    class Http:
        async def post_json(self, url, payload, headers=None):
            calls.append((url,payload,headers)); return {"result":"bundleid"}
    attempt = ExecutionAttempt("opp",1,"hash",ExecutionState.SIGNED,BH)
    res = await JitoSingleTransactionSender(Http(), "https://block").submit((b"abc",), attempt)
    assert res.accepted and not res.landed and calls[-1][1]["params"][1]["encoding"] == "base64" and calls[-1][0].endswith("?bundleOnly=true") and "bundleOnly" not in calls[-1][1]["params"][1]
    with pytest.raises(ValueError):
        await JitoBundleSender(Http(), "https://block").submit((b"1", b"2", b"3", b"4", b"5", b"6"), attempt)

def test_paper_mode_never_creates_fake_bundle_id():
    result = SubmissionResult(False, "shadow", "submission_blocked_by_shadow_mode")
    assert not result.submitted and result.bundle_id is None
