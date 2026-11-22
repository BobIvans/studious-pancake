"""CAM-04: durable campaign-global attempt + storage budgets (fail closed)."""

import threading
from dataclasses import replace

import pytest

from src.market.streams import RecoverableStreamJournal
from src.qualification_campaign.evidence import (
    CampaignBudgets,
    CampaignEvidenceStore,
)
from src.qualification_campaign.identity import CampaignManifest
from src.qualification_campaign.profiles import ProviderProfile

pytestmark = pytest.mark.unit


def profile(profile_id="rpc-a", cap=100):
    return ProviderProfile(
        profile_id,
        "provider-" + profile_id,
        "operator-" + profile_id,
        "group-" + profile_id,
        "https://" + profile_id + ".test",
        "https://docs.test/" + profile_id,
        campaign_attempt_cap=cap,
    )


def manifest_for(ps):
    return CampaignManifest(
        "a" * 40,
        "b" * 40,
        "c" * 64,
        (("capture", "d" * 64),),
        tuple((p.profile_id, p.generation) for p in ps),
    )


def budgets(attempts=200, storage=104857600):
    return CampaignBudgets(
        rpc_physical_attempts_max=attempts,
        storage_bytes_max=storage,
        external_data_spend_usd_max=0,
    )


def test_two_profiles_cannot_exceed_campaign_global_cap(tmp_path):
    a = profile("rpc-a", cap=100)
    b = profile("rpc-b", cap=100)
    store = CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / "events.sqlite"),
        manifest_for((a, b)),
        campaign_budgets=budgets(attempts=3),
    )
    store.claim_attempt(a)
    store.claim_attempt(a)
    store.claim_attempt(b)  # per-profile caps (100) untouched; global pool at 3/3
    with pytest.raises(ValueError, match="GLOBAL_ATTEMPT_BUDGET_EXHAUSTED"):
        store.claim_attempt(b)


def test_per_profile_cap_still_enforced_under_global_budget(tmp_path):
    a = profile("rpc-a", cap=1)
    store = CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / "events.sqlite"),
        manifest_for((a,)),
        campaign_budgets=budgets(attempts=10),
    )
    store.claim_attempt(a)
    with pytest.raises(ValueError, match="CAMPAIGN_ATTEMPT_BUDGET_EXHAUSTED"):
        store.claim_attempt(a)


def test_every_retry_consumes_the_global_pool(tmp_path):
    a = profile("rpc-a", cap=100)
    store = CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / "events.sqlite"),
        manifest_for((a,)),
        campaign_budgets=budgets(attempts=2),
    )
    store.claim_attempt(a)
    store.claim_attempt(a)  # a retry is a physical attempt
    with pytest.raises(ValueError, match="GLOBAL_ATTEMPT_BUDGET_EXHAUSTED"):
        store.claim_attempt(a)


def test_budget_survives_restart(tmp_path):
    a = profile("rpc-a", cap=100)
    journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
    store = CampaignEvidenceStore(
        journal, manifest_for((a,)), campaign_budgets=budgets(attempts=1)
    )
    store.claim_attempt(a)
    journal.close()
    journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
    try:
        reopened = CampaignEvidenceStore(
            journal, manifest_for((a,)), campaign_budgets=budgets(attempts=1)
        )
        with pytest.raises(ValueError, match="GLOBAL_ATTEMPT_BUDGET_EXHAUSTED"):
            reopened.claim_attempt(a)
    finally:
        journal.close()


def test_storage_budget_exactly_at_limit_passes_one_byte_over_blocks(tmp_path):
    from src.qualification_campaign.identity import canonical_bytes

    payload = {"kind": "observation", "data": "x" * 4096}
    blob_payload = {"kind": "observation", "data": "y" * 750_000}
    cid = manifest_for((profile("rpc-a"),)).campaign_id
    blob_encoded_len = len(
        canonical_bytes({**blob_payload, "campaign_manifest_hash": cid})
    )
    slack = 1024  # must match evidence._STORAGE_RESERVATION_SLACK

    def make_store(name, cap):
        return CampaignEvidenceStore(
            RecoverableStreamJournal(tmp_path / name),
            manifest_for((profile("rpc-a"),)),
            campaign_budgets=CampaignBudgets(
                rpc_physical_attempts_max=10,
                storage_bytes_max=cap,
                external_data_spend_usd_max=0,
            ),
        )

    # Exact-limit store: cap == footprint + blob bytes + slack -> PASS.
    exact = make_store("events-exact.sqlite", 2**30)
    exact.append("probe", payload, observed_at_ns=1)
    needed = exact.campaign_storage_bytes() + blob_encoded_len + slack
    exact_at_limit = CampaignEvidenceStore(
        exact.journal,
        manifest_for((profile("rpc-a"),)),
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=needed,
            external_data_spend_usd_max=0,
        ),
    )
    exact_at_limit.append("probe", blob_payload, observed_at_ns=1)  # PASS at limit
    exact.journal.close()

    # One byte under the required reservation -> blocked BEFORE persist.
    guarded = make_store("events-over.sqlite", 2**30)
    guarded.append("probe", payload, observed_at_ns=1)
    blobs_before = list((tmp_path / "events-over.sqlite.blobs").glob("*"))
    tight = CampaignEvidenceStore(
        guarded.journal,
        manifest_for((profile("rpc-a"),)),
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=guarded.campaign_storage_bytes()
            + blob_encoded_len
            + slack
            - 1,
            external_data_spend_usd_max=0,
        ),
    )
    with pytest.raises(ValueError, match="CAMPAIGN_STORAGE_BUDGET_EXHAUSTED"):
        tight.append("probe", blob_payload, observed_at_ns=1)
    blobs_after = list((tmp_path / "events-over.sqlite.blobs").glob("*"))
    assert blobs_before == blobs_after  # blocked BEFORE persist
    guarded.journal.close()


def test_unbounded_or_paid_budgets_fail_closed():
    with pytest.raises(ValueError, match="ATTEMPT_BUDGET_UNBOUNDED"):
        CampaignBudgets(rpc_physical_attempts_max=0, storage_bytes_max=1024)
    with pytest.raises(ValueError, match="STORAGE_BUDGET_UNBOUNDED"):
        CampaignBudgets(rpc_physical_attempts_max=10, storage_bytes_max=0)
    with pytest.raises(ValueError, match="PAID_SPEND_FORBIDDEN"):
        CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=1024,
            external_data_spend_usd_max=5,
        )


def test_appends_are_serialized_under_one_campaign_lock(tmp_path):
    """The append/cursor race hypothesis: with one shared cross-process
    flock around every append, concurrent writers with independent journal
    connections must produce a replayable journal with sequential cursors.
    (The pre-fix behavior is a REPRODUCTION_REQUIRED backlog item.)"""
    a = profile("rpc-a")
    cid = manifest_for((a,))
    errors = []
    lock = threading.Lock()

    init_lock = threading.Lock()
    stores = []

    def writer(worker):
        try:
            # sqlite3 connections are thread-bound: construct this writer's
            # journal under a mutex (constructor reads are not the
            # serialization target), then append under the cross-process
            # flock only.
            with init_lock:
                journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
                store = CampaignEvidenceStore(journal, cid, campaign_budgets=budgets())
            for i in range(10):
                store.append(
                    "shared",
                    {"kind": "observation", "worker": worker, "i": i},
                    observed_at_ns=1_000 + worker * 100 + i,
                )
            journal.close()
        except Exception as exc:  # pragma: no cover - surfaced below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=writer, args=(w,)) for w in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
    try:
        events = [
            e for e in journal.events(available_at_ns=2**63 - 1) if e.source == "shared"
        ]
        assert len(events) == 40
        assert [e.cursor for e in events] == list(range(1, 41))
        assert CampaignEvidenceStore(journal, cid).replay()  # hash chain intact
    finally:
        journal.close()


def test_campaign_storage_bytes_counts_db_wal_shm_lock_and_blobs(tmp_path):
    a = profile("rpc-a")
    journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
    store = CampaignEvidenceStore(
        journal, manifest_for((a,)), campaign_budgets=budgets()
    )
    before = store.campaign_storage_bytes()
    assert before > 0  # journal db + lock file at minimum
    store.append(
        "probe", {"kind": "observation", "data": "z" * 800_000}, observed_at_ns=1
    )
    after = store.campaign_storage_bytes()
    assert after > before + 750_000  # blob bytes counted
    journal.close()
