"""CAM-04: durable campaign-global attempt + storage budgets (fail closed)."""

import subprocess
import threading
from dataclasses import replace

import pytest

from src.market.streams import RecoverableStreamJournal
from src.qualification_campaign import cli
from src.qualification_campaign.evidence import (
    CampaignBudgets,
    CampaignEvidenceStore,
    journal_growth_bound,
    prepare_event,
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
    from src.qualification_campaign.identity import canonical_bytes, digest

    payload = {"kind": "observation", "data": "x" * 4096}
    blob_payload = {"kind": "observation", "data": "y" * 750_000}
    cid = manifest_for((profile("rpc-a"),)).campaign_id
    blob_encoded_len = len(
        canonical_bytes({**blob_payload, "campaign_manifest_hash": cid})
    )


    def make_store(name, cap, *, journal=None):
        return CampaignEvidenceStore(
            journal or RecoverableStreamJournal(tmp_path / name),
            manifest_for((profile("rpc-a"),)),
            campaign_budgets=CampaignBudgets(
                rpc_physical_attempts_max=10,
                storage_bytes_max=cap,
                external_data_spend_usd_max=0,
            ),
        )

    # Exact-limit store: cap == footprint + blob bytes + journal bound -> PASS.
    exact = make_store("events-exact.sqlite", 2**30)
    exact.append("probe", payload, observed_at_ns=1)
    page = exact.page_size
    needed = (
        exact.campaign_storage_bytes()
        + blob_encoded_len
        + journal_growth_bound(_row_len(exact, blob_payload), exact.page_size)
    )
    exact_at_limit = make_store("unused.sqlite", needed, journal=exact.journal)
    exact_at_limit.append("probe", blob_payload, observed_at_ns=1)  # PASS at limit
    exact.journal.close()

    # One byte under the required reservation -> blocked BEFORE persist.
    guarded = make_store("events-over.sqlite", 2**30)
    guarded.append("probe", payload, observed_at_ns=1)
    blobs_before = list((tmp_path / "events-over.sqlite.blobs").glob("*"))
    tight = make_store(
        "unused2.sqlite",
        guarded.campaign_storage_bytes()
        + blob_encoded_len
        + journal_growth_bound(_row_len(guarded, blob_payload), guarded.page_size)
        - 1,
        journal=guarded.journal,
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


def _store(tmp_path, name, cap, *, ledger_path=None):
    return CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / name),
        manifest_for((profile("rpc-a"),)),
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=cap,
            external_data_spend_usd_max=0,
        ),
        ledger_path=ledger_path,
    )


def _row_len(store, payload, observed_at_ns=1):
    """Exact serialized journal-row length for the NEXT append of payload.

    Replicates the real append's availability semantics (wall-clock fallback)
    so the digit count matches; epoch-ns stays 19 digits for the foreseeable
    future, making the serialized length identical to the real row.
    """

    import json as _json
    import time as _time
    from dataclasses import asdict
    from src.market.streams import RawStreamEvent
    from src.qualification_campaign.identity import canonical_bytes, digest

    body = {**payload, "campaign_manifest_hash": store.manifest.campaign_id}
    encoded = canonical_bytes(body)
    if len(encoded) > 750_000:
        name = digest(body)
        stored = {
            "kind": "blob_reference",
            "raw_payload_ref": name,
            "raw_payload_hash": name,
            "campaign_manifest_hash": store.manifest.campaign_id,
        }
    else:
        stored = body
    previous = [
        e
        for e in store.journal.events(available_at_ns=2**63 - 1)
        if e.source == "probe"
    ]
    event = RawStreamEvent(
        "probe",
        store.manifest.campaign_id,
        1,
        previous[-1].cursor + 1 if previous else 1,
        max(observed_at_ns, _time.time_ns()),
        observed_at_ns,
        "probe",
        "prequal.observation.v1",
        canonical_bytes(stored).decode(),
        digest(stored),
        previous[-1].block_hash if previous else "GENESIS",
    )
    return len(_json.dumps(asdict(event), sort_keys=True))


def test_inline_payload_under_budget_passes(tmp_path):
    store = _store(tmp_path, "events.sqlite", 2**30)
    store.append("probe", {"kind": "observation", "data": "x" * 4096}, observed_at_ns=1)
    store.append("probe", {"kind": "observation", "data": "y" * 4096}, observed_at_ns=2)
    assert len(store.replay()) >= 3  # manifest + two inline events


def test_inline_payload_exact_limit_passes_one_byte_over_blocks(tmp_path):
    from src.qualification_campaign.identity import canonical_bytes

    store = _store(tmp_path, "events.sqlite", 2**30)
    store.append("probe", {"kind": "observation", "data": "x" * 64}, observed_at_ns=1)
    cid = store.manifest.campaign_id
    inline_encoded = len(
        canonical_bytes(
            {
                "kind": "observation",
                "data": "z" * 4096,
                "campaign_manifest_hash": cid,
            }
        )
    )
    at_limit = CampaignEvidenceStore(
        store.journal,
        store.manifest,
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=store.campaign_storage_bytes()
            + journal_growth_bound(inline_encoded, store.page_size),
            external_data_spend_usd_max=0,
        ),
    )
    at_limit.append(
        "probe", {"kind": "observation", "data": "z" * 4096}, observed_at_ns=2
    )
    tight = CampaignEvidenceStore(
        store.journal,
        store.manifest,
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=store.campaign_storage_bytes()
            + journal_growth_bound(inline_encoded, store.page_size)
            - 1,
            external_data_spend_usd_max=0,
        ),
    )
    before = len(store.replay())
    with pytest.raises(ValueError, match="CAMPAIGN_STORAGE_BUDGET_EXHAUSTED"):
        tight.append(
            "probe", {"kind": "observation", "data": "w" * 4096}, observed_at_ns=3
        )
    assert len(store.replay()) == before  # reservation failure = no write


def test_many_small_appends_cannot_exceed_total_limit(tmp_path):
    from src.qualification_campaign.identity import canonical_bytes

    store = _store(tmp_path, "events.sqlite", 2**30)
    small = {"kind": "observation", "data": "s" * 512}
    cid = store.manifest.campaign_id
    per_event = len(canonical_bytes({**small, "campaign_manifest_hash": cid}))
    tight = CampaignEvidenceStore(
        store.journal,
        store.manifest,
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=store.campaign_storage_bytes()
            + 3 * (per_event + journal_growth_bound(per_event, store.page_size)),
            external_data_spend_usd_max=0,
        ),
    )
    blocked = 0
    for i in range(10):
        try:
            tight.append("probe", small, observed_at_ns=i + 1)
        except ValueError as exc:
            assert "CAMPAIGN_STORAGE_BUDGET_EXHAUSTED" in str(exc)
            blocked += 1
    assert blocked >= 1


def test_manifest_append_is_subject_to_storage_budget(tmp_path):
    # A budget smaller than the initial manifest footprint must fail closed
    # at construction time - the first (manifest) append is enforced too.
    with pytest.raises(ValueError, match="CAMPAIGN_STORAGE_BUDGET_EXHAUSTED"):
        _store(tmp_path, "events.sqlite", 128)


def test_approval_ledger_db_and_sidecars_count_into_budget(tmp_path):
    ledger = tmp_path / "campaign-approval-ledger.sqlite"
    ledger.write_bytes(b"L" * 64_000)
    (tmp_path / "campaign-approval-ledger.sqlite-wal").write_bytes(b"W" * 8_000)
    store = _store(
        tmp_path,
        "events.sqlite",
        2**30,
        ledger_path=tmp_path / "campaign-approval-ledger.sqlite",
    )
    plain = _store(tmp_path, "events-plain.sqlite", 2**30)
    delta = store.campaign_storage_bytes() - plain.campaign_storage_bytes()
    assert delta >= 64_000 + 8_000  # ledger db + wal counted


def test_large_ledger_reduces_inline_headroom(tmp_path):
    ledger = tmp_path / "campaign-approval-ledger.sqlite"
    ledger.write_bytes(b"L" * 100_000)
    journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
    store = CampaignEvidenceStore(
        journal,
        manifest_for((profile("rpc-a"),)),
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=2**30,
            external_data_spend_usd_max=0,
        ),
        ledger_path=ledger,
    )
    footprint_with_ledger = store.campaign_storage_bytes()
    assert footprint_with_ledger >= 100_000
    # One byte less than the footprint + slack needed for the next inline
    # append: the ledger bytes consumed the headroom.
    tight = CampaignEvidenceStore(
        journal,
        store.manifest,
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=footprint_with_ledger
            + journal_growth_bound(
                _row_len(store, {"kind": "observation", "data": "q" * 1024}),
                store.page_size,
            )
            - 1,
            external_data_spend_usd_max=0,
        ),
        ledger_path=ledger,
    )
    before = len(store.replay())
    with pytest.raises(ValueError, match="CAMPAIGN_STORAGE_BUDGET_EXHAUSTED"):
        tight.append(
            "probe", {"kind": "observation", "data": "q" * 1024}, observed_at_ns=1
        )
    assert len(store.replay()) == before
    journal.close()


def test_storage_budget_survives_restart(tmp_path):
    journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
    store = _store(tmp_path, "events.sqlite", 2**30)
    store.append("probe", {"kind": "observation", "data": "x" * 4096}, observed_at_ns=1)
    used = store.campaign_storage_bytes()
    journal.close()
    journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
    try:
        reopened = CampaignEvidenceStore(
            journal,
            store.manifest,
            campaign_budgets=CampaignBudgets(
                rpc_physical_attempts_max=10,
                storage_bytes_max=used,  # no headroom for another event
                external_data_spend_usd_max=0,
            ),
        )
        with pytest.raises(ValueError, match="CAMPAIGN_STORAGE_BUDGET_EXHAUSTED"):
            reopened.append(
                "probe", {"kind": "observation", "data": "n" * 4096}, observed_at_ns=2
            )
    finally:
        journal.close()


def test_concurrent_writers_respect_shared_storage_budget(tmp_path):
    import threading

    from src.qualification_campaign.identity import canonical_bytes

    small = {"kind": "observation", "data": "s" * 256}
    cid = manifest_for((profile("rpc-a"),))
    probe_store = CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / "probe.sqlite"),
        cid,
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10_000,
            storage_bytes_max=2**30,
            external_data_spend_usd_max=0,
        ),
    )
    row = _row_len(probe_store, small)
    probe_store.journal.close()
    budget = CampaignBudgets(
        rpc_physical_attempts_max=10_000,
        # room for a bounded number of events across ALL writers
        storage_bytes_max=row * 8 + journal_growth_bound(row, 4096) * 8,
        external_data_spend_usd_max=0,
    )
    errors = []
    writes = []
    lock = threading.Lock()
    init_lock = threading.Lock()

    def writer(worker):
        try:
            with init_lock:
                journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
                store = CampaignEvidenceStore(journal, cid, campaign_budgets=budget)
            accepted = 0
            for i in range(6):
                try:
                    store.append(
                        "shared",
                        {**small, "w": worker, "i": i},
                        observed_at_ns=i + 1,
                    )
                    accepted += 1
                except ValueError as exc:
                    assert "CAMPAIGN_STORAGE_BUDGET_EXHAUSTED" in str(exc)
                    break
            with lock:
                writes.append(accepted)
            journal.close()
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=writer, args=(w,)) for w in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sum(writes) >= 1  # at least the earliest writer got its events in
    reopened = RecoverableStreamJournal(tmp_path / "events.sqlite")
    try:
        events = [
            e
            for e in reopened.events(available_at_ns=2**63 - 1)
            if e.source == "shared"
        ]
        assert len(events) == sum(writes)
        assert CampaignEvidenceStore(reopened, cid).replay()  # hash chain intact
    finally:
        reopened.close()


def test_strict_ceiling_never_exceeded_by_accepted_appends(tmp_path):
    """Security closure R-A: every accepted append leaves the actual
    campaign footprint at or under the approved cap (strict physical
    ceiling, worst-case journal growth bound reserved pre-write)."""
    store = _store(tmp_path, "events.sqlite", 2**30)
    cid = store.manifest.campaign_id
    from src.qualification_campaign.identity import canonical_bytes

    event_payload = {"kind": "observation", "data": "k" * 2048}
    row = _row_len(store, event_payload)
    bound = journal_growth_bound(row, store.page_size)
    # Cap admits exactly 5 events under the worst-case bound.
    tight = CampaignEvidenceStore(
        store.journal,
        store.manifest,
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=store.campaign_storage_bytes() + 5 * (row + bound),
            external_data_spend_usd_max=0,
        ),
    )
    accepted = 0
    for i in range(9):
        try:
            tight.append(
                "probe",
                {"kind": "observation", "data": "k" * 2048},
                observed_at_ns=i + 1,
            )
            accepted += 1
            assert (
                tight.campaign_storage_bytes()
                <= tight.campaign_budgets.storage_bytes_max
            )
        except ValueError as exc:
            assert "CAMPAIGN_STORAGE_BUDGET_EXHAUSTED" in str(exc)
            break
    assert accepted >= 1
    assert tight.campaign_storage_bytes() <= tight.campaign_budgets.storage_bytes_max
    store.journal.close()
    tight.journal.close()


def test_page_granularity_blocks_large_inline_that_flat_slack_missed(tmp_path):
    """Adversarial page-granularity case: a ~700 KB inline row grows the DB
    AND its WAL by roughly the row size again (full page images per frame);
    the old flat 16 KB slack reservation would have admitted it, the strict
    bound correctly blocks it."""
    from src.qualification_campaign.identity import canonical_bytes

    store = _store(tmp_path, "events.sqlite", 2**30)
    store.append("probe", {"kind": "observation", "data": "x" * 64}, observed_at_ns=1)
    cid = store.manifest.campaign_id
    big_encoded = len(
        canonical_bytes(
            {
                "kind": "observation",
                "data": "z" * 700_000,
                "campaign_manifest_hash": cid,
            }
        )
    )
    # Cap sized for the OLD flat-slack reservation (encoded + 16 KB).
    legacy_cap = CampaignEvidenceStore(
        store.journal,
        store.manifest,
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=store.campaign_storage_bytes() + big_encoded + 16_384,
            external_data_spend_usd_max=0,
        ),
    )
    with pytest.raises(ValueError, match="CAMPAIGN_STORAGE_BUDGET_EXHAUSTED"):
        legacy_cap.append(
            "probe", {"kind": "observation", "data": "z" * 700_000}, observed_at_ns=2
        )


@pytest.mark.skipif(
    subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "origin/main^{commit}"],
        capture_output=True,
    ).returncode
    != 0,
    reason="requires a full clone with the origin/main ref",
)
def test_pre_ledger_ceiling_blocks_before_ledger_creation(tmp_path, monkeypatch):
    """Security closure item 2 (pre-ledger): a manifest artifact that does
    not fit the approved budget blocks the start before the approval ledger
    database is even created."""
    import asyncio
    import json
    from datetime import datetime, timezone

    calls = []

    def _forbidden_transport(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("transport must not be constructed for a blocked start")

    monkeypatch.setattr(cli, "campaign_transport", _forbidden_transport)
    source_config = tmp_path / "source-config.json"
    checked = datetime.now(timezone.utc).isoformat()
    source_config.write_text(
        json.dumps(
            {
                "schema_version": "prequal.source-intake-config.v1",
                "sources": [
                    {
                        "dossier": {
                            "source_id": "dexscreener",
                            "label": "d",
                            "profile": {
                                "profile_id": "discovery-dexscreener",
                                "provider": "dexscreener",
                                "operator": "dexscreener",
                                "correlation_group": "dexscreener",
                                "endpoint": "https://api.dexscreener.invalid/token-pairs/v1/solana/x",
                                "official_docs": "https://docs.dexscreener.invalid/api/reference",
                                "role": "discovery",
                                "request_limit": 1,
                                "window_seconds": 60,
                                "campaign_attempt_cap": 10,
                            },
                            "checked_at": checked,
                            "docs_sha256": "a" * 64,
                            "request_schema_version": "DiscoveryRequest.v1",
                            "response_schema_version": "DiscoveredMarket.v1",
                            "schema_fingerprint": "b" * 64,
                            "terms_url": "https://docs.dexscreener.invalid/terms",
                            "classification": "DISCOVERY_ONLY",
                        },
                        "adapter": {
                            "kind": "catalog",
                            "request": {
                                "source_id": "dexscreener",
                                "token_mint": "So11111111111111111111111111111111111111112",
                            },
                        },
                    }
                ],
            }
        )
    )
    plan = tmp_path / "campaign-plan.json"
    plan.write_text(json.dumps(_tiny_budget_plan()))
    output = tmp_path / "campaign-output"
    result = asyncio.run(cli.capture(source_config, output, None, 1, plan, None))
    assert calls == []
    assert result["physical_network_attempts"] == 0
    assert result["campaign_start_gate"]["blockers"] == [
        "CAMPAIGN_STORAGE_BUDGET_EXHAUSTED"
    ]
    assert not (output / "campaign-approval-ledger.sqlite").exists()


def _tiny_budget_plan() -> dict:
    # Reuses the unapproved-plan shape from the transport-sentinel test but
    # with a storage budget too small for the manifest artifact, so the
    # pre-ledger ceiling check fires first.
    import hashlib

    plan = {
        "schema_version": "prequal.campaign-plan.v2",
        "gate_set": "CAMPAIGN_START_V1",
        "mode": "CAPTURE_ONLY",
        "discovery_only": True,
        "campaign_label": "20261121-market-capture-001",
        "environment": "research",
        "approved_manifest_digest": "0" * 64,
        "repository_sha": "1" * 40,
        "main_sha": "2" * 40,
        "runtime_authority_sha256": "0" * 64,
        "policy_bundle_sha256": "0" * 64,
        "trust_registry_generation": "test-gen-1",
        "configuration_digests": {"capture": "0" * 64},
        "source_generations": {"dexscreener": "0" * 64},
        "profiles_digests": {"rpc-primary": "0" * 64},
        "budgets": {
            "rpc_physical_attempts_max": 200,
            "storage_bytes_max": 64,
            "per_source_quotas": {
                "dexscreener": {"requests": 12, "window_seconds": 60, "attempts": 100}
            },
            "external_data_spend_usd_max": 0,
        },
        "retention": {"journal_retention_days": 30},
        "capture_window_seconds": 86400,
        "source_semantics": {"dexscreener": "PUBLIC_DISCOVERY"},
        "source_method_allowlists": {"rpc-primary": ["getSlot"]},
        "offline_evidence": {
            "journal_durability": {"test_id": "t", "receipt_sha256": "c" * 64},
            "replay_zero_network": {"test_id": "t", "receipt_sha256": "d" * 64},
        },
        "approval_payload": {"placeholder": True},
        "envelope": {"placeholder": True},
    }
    return plan


def test_extra_artifacts_count_into_footprint(tmp_path):
    manifest_artifact = tmp_path / "campaign-manifest.json"
    manifest_artifact.write_bytes(b"M" * 2_048)
    blocked = tmp_path / "campaign-start-blocked.json"
    blocked.write_bytes(b"B" * 512)
    report = tmp_path / "report.json"
    report.write_bytes(b"R" * 1_024)
    journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
    store = CampaignEvidenceStore(
        journal,
        manifest_for((profile("rpc-a"),)),
        campaign_budgets=CampaignBudgets(
            rpc_physical_attempts_max=10,
            storage_bytes_max=2**30,
            external_data_spend_usd_max=0,
        ),
        extra_artifacts=(manifest_artifact, blocked, report),
    )
    plain = CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / "events-plain.sqlite"),
        manifest_for((profile("rpc-a"),)),
    )
    delta = store.campaign_storage_bytes() - plain.campaign_storage_bytes()
    assert delta >= 2_048 + 512 + 1_024
    journal.close()
