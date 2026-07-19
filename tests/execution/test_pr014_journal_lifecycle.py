import asyncio, sqlite3
import pytest
from src.execution import *
from src.execution.jito_status import bundle_status_batches, parse_inflight_bundle_status
from src.execution.senders.jito_single_sender import JitoSingleTransactionSender
from src.execution.senders.jito_bundle_sender import JitoBundleSender

BH = BlockhashContext("So11111111111111111111111111111111111111112", 99, 10, 0.0, "confirmed")

@pytest.mark.asyncio
async def test_sqlite_migration_wal_reopen_unique_and_recovery(tmp_path):
    db=tmp_path/"attempts.sqlite"
    j=SQLiteAttemptJournal(db)
    rec=await j.create_attempt("opp","plan",0,state=ExecutionState.SIGNED)
    assert j.db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    with pytest.raises(sqlite3.IntegrityError):
        await j.create_attempt("opp","plan",0)
    assert await j.record_submission_intent(("opp","plan",0), owner="w1", lease_seconds=60, transport="rpc", signatures=("sig",), message_digest="m", signed_transaction_digest="s", blockhash_context=BH)
    j2=SQLiteAttemptJournal(db)
    assert await j2.recover_ambiguous_intents() == 1
    assert (await j2.get("opp","plan",0)).state == ExecutionState.SUBMISSION_UNCERTAIN

@pytest.mark.asyncio
async def test_cas_and_concurrent_claim_allow_one_submitter(tmp_path):
    j=SQLiteAttemptJournal(tmp_path/"a.db")
    await j.create_attempt("opp","plan",0,state=ExecutionState.SIGNED)
    async def claim(owner):
        return await j.record_submission_intent(("opp","plan",0), owner=owner, lease_seconds=60, transport="rpc", signatures=(owner,), message_digest="m", signed_transaction_digest="s", blockhash_context=BH)
    assert sum(await asyncio.gather(*(claim(str(i)) for i in range(10)))) == 1

def test_state_machine_retry_blocking_and_rebuild_path():
    sm=ExecutionStateMachine()
    for state in (ExecutionState.ACCEPTED, ExecutionState.PENDING, ExecutionState.LANDED, ExecutionState.SUBMISSION_UNCERTAIN, ExecutionState.AMBIGUOUS_MANUAL_REVIEW):
        assert sm.retry_blocked(state)
        assert not sm.can_submit(state)
    assert sm.can_transition(ExecutionState.PROVEN_EXPIRED, ExecutionState.REBUILD_ELIGIBLE)

@pytest.mark.asyncio
async def test_live_gate_blocks_sender_even_if_configured(tmp_path):
    j=SQLiteAttemptJournal(tmp_path/"g.db")
    await j.create_attempt("opp","plan",0,state=ExecutionState.SIGNED)
    class Sender:
        called=False
        async def submit(self,*a,**k):
            self.called=True
    sender=Sender()
    env=SubmissionEnvelope("opp","plan",0,(b"tx",),("sig",),"m",BH,"rpc")
    res=await TransactionLifecycleService(j).submit_live(env, sender)
    assert not res.submitted and res.reason == "live_gate_not_open" and not sender.called

@pytest.mark.asyncio
async def test_jito_single_signature_and_header_are_separate_and_bundle_only_query():
    calls=[]
    class Http:
        async def post_json(self,url,payload,headers=None):
            calls.append((url,payload,headers)); return ({"result":"txsig"},{"x-bundle-id":"bundle123"})
    res=await JitoSingleTransactionSender(Http(),"https://block").submit((b"abc",), ExecutionAttempt("opp",1,"hash",ExecutionState.SIGNED,BH))
    assert res.transaction_signatures == ("txsig",) and res.bundle_id == "bundle123"
    assert calls[0][0].endswith("?bundleOnly=true")
    assert "bundleOnly" not in calls[0][1]["params"][1]
    assert not res.landed

@pytest.mark.asyncio
async def test_jito_bundle_limit_and_status_ambiguity():
    class Http:
        async def post_json(self,url,payload,headers=None): return {"result":"bundleid"}
    with pytest.raises(ValueError):
        await JitoBundleSender(Http(),"https://block").submit(tuple([b"x"]*6), ExecutionAttempt("opp",1,"hash",ExecutionState.SIGNED,BH))
    assert bundle_status_batches(tuple(str(i) for i in range(12))) == (("0","1","2","3","4"),("5","6","7","8","9"),("10","11"))
    assert parse_inflight_bundle_status(None).ambiguous
    assert parse_inflight_bundle_status({"status":"Invalid"}).ambiguous

@pytest.mark.parametrize("e,state", [
    (ReconciliationEvidence(True, True, True, 12, 10), ExecutionState.RECONCILED_SUCCESS),
    (ReconciliationEvidence(True, False, True, 12, 10), ExecutionState.RECONCILED_FAILURE),
    (ReconciliationEvidence(True, True, True, 9, 10), ExecutionState.AMBIGUOUS_MANUAL_REVIEW),
])
def test_reconciliation_is_source_of_truth(e,state):
    assert classify_reconciliation(e)[1] == state
