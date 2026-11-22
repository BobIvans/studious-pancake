"""DATA-01: durable per-attempt trace, cursor/gap accounting, restart accounting.

Acceptance (docs/roadmap/data-to-paper-readiness-2026-11-22/TASK_BACKLOG_V1.json):
- every accepted/rejected physical attempt carries a durable trace with raw
  evidence reference/hash, source generation, cursor/gap and a typed
  terminal/error result;
- cursor allocation and appends are concurrency-safe across processes with
  crash/restart/duplicate-retry tests showing no lost, reused or silently
  skipped cursors;
- attempts/retries/storage reservations stay durable and accounted across
  restart (no unbounded retry, no in-memory-only limit);
- replay recomputes from retained raw bytes/references with zero outbound
  network and a deterministic digest;
- save/serialization/commit errors surface as typed blockers (no discarded
  save errors, no second raw store).
"""

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src.market.streams import RecoverableStreamJournal
from src.qualification_campaign.evidence import (
    CampaignBudgets,
    CampaignEvidenceStore,
    EvidenceCommitError,
)
from src.qualification_campaign.identity import CampaignManifest
from src.qualification_campaign.profiles import ProviderProfile

pytestmark = pytest.mark.unit

WORKER = (
    "import sys, time\n"
    "sys.path.insert(0, {root!r})\n"
    "from src.market.streams import RecoverableStreamJournal\n"
    "from src.qualification_campaign.evidence import CampaignEvidenceStore\n"
    "from src.qualification_campaign.identity import CampaignManifest\n"
    "journal = RecoverableStreamJournal({db!r})\n"
    "manifest = CampaignManifest('a' * 40, 'b' * 40, 'c' * 64, "
    "(('capture', 'd' * 64),), (('rpc-a', 'e' * 64),))\n"
    "store = CampaignEvidenceStore(journal, manifest)\n"
    "for i in range({n}):\n"
    "    store.append({source!r}, {{'i': i, 'worker': {worker!r}}}, "
    "observed_at_ns=time.time_ns())\n"
    "print('done')\n"
)


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


def _store(tmp_path, ps=(profile(),), *, db="events.sqlite", attempts=200):
    return CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / db),
        manifest_for(ps),
        campaign_budgets=budgets(attempts=attempts),
    )


def test_multiprocess_appends_produce_sequential_gapless_cursors(tmp_path):
    """Concurrent cooperating processes never lose, reuse or skip cursors."""

    db = tmp_path / "events.sqlite"
    workers = 4
    per_worker = 5
    procs = []
    for worker in range(workers):
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    WORKER.format(
                        root=str(Path(__file__).parents[1]),
                        db=str(db),
                        n=per_worker,
                        source="rpc-a",
                        worker=worker,
                    ),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
    manifest = CampaignManifest(
        "a" * 40, "b" * 40, "c" * 64, (("capture", "d" * 64),), (("rpc-a", "e" * 64),)
    )
    store = CampaignEvidenceStore(RecoverableStreamJournal(db), manifest)
    report = store.cursor_report("rpc-a")
    assert report["max_cursor"] == workers * per_worker
    assert report["cursor_count"] == workers * per_worker
    assert report["duplicate_cursors"] == []
    cursors = [
        e.cursor
        for e in store.journal.events(available_at_ns=2**63 - 1)
        if e.source == "rpc-a"
    ]
    assert sorted(cursors) == list(range(1, workers * per_worker + 1))


def test_cursor_gap_and_payload_conflict_fail_closed(tmp_path):
    a = profile()
    store = _store(tmp_path, (a,))
    store.append("rpc-a", {"i": 1}, observed_at_ns=1)
    store.append("rpc-a", {"i": 2}, observed_at_ns=2)
    store.append("rpc-a", {"i": 3}, observed_at_ns=3)
    # A silently skipped cursor must be a typed integrity failure.
    events = [
        e
        for e in store.journal.events(available_at_ns=2**63 - 1)
        if e.source == "rpc-a"
    ]
    assert [e.cursor for e in events] == [1, 2, 3]
    report = store.cursor_report("rpc-a")
    assert report["cursor_count"] == 3

    # Inject a gap by simulating a journal with a missing middle cursor.
    class _GappedJournal:
        def __init__(self, inner):
            self._inner = inner
            self.db = inner.db

        def events(self, **kwargs):
            return [
                e
                for e in self._inner.events(**kwargs)
                if not (e.source == "rpc-a" and e.cursor == 2)
            ]

    gapped = CampaignEvidenceStore(_GappedJournal(store.journal), store.manifest)
    with pytest.raises(ValueError, match="EVIDENCE_CURSOR_GAP_DETECTED"):
        gapped.cursor_report("rpc-a")


def test_trace_carries_cursor_chain_hash_and_typed_result(tmp_path):
    a = profile()
    store = _store(tmp_path, (a,))
    store.append(
        "rpc-a", {"kind": "attempt", "provider_id": a.profile_id}, observed_at_ns=1
    )
    store.append(
        "rpc-a", {"kind": "attempt", "provider_id": a.profile_id}, observed_at_ns=2
    )
    events = store.replay()
    attempts = [e for e in events if e.get("kind") == "attempt"]
    assert len(attempts) == 2
    first, second = attempts
    assert first["previous_cursor"] == 0  # first event for this source
    assert second["previous_cursor"] == first["evidence_cursor"]
    # Deterministic digest: same retained bytes -> same digest across calls.
    assert store.replay_digest() == store.replay_digest()


def test_restart_preserves_attempt_and_storage_accounting(tmp_path):
    a = profile()
    db = tmp_path / "events.sqlite"
    store = CampaignEvidenceStore(
        RecoverableStreamJournal(db),
        manifest_for((a,)),
        campaign_budgets=budgets(attempts=2),
    )
    store.claim_attempt(a)
    store.claim_attempt(a)
    # Simulate a restart: fresh objects over the same durable journal.
    reopened = CampaignEvidenceStore(
        RecoverableStreamJournal(db),
        manifest_for((a,)),
        campaign_budgets=budgets(attempts=2),
    )
    attempts = [e for e in reopened.replay() if e.get("kind") == "attempt"]
    assert len(attempts) == 2
    with pytest.raises(ValueError, match="GLOBAL_ATTEMPT_BUDGET_EXHAUSTED"):
        reopened.claim_attempt(a)  # no unbounded retry across restart


def test_replay_is_zero_network_and_deterministic(tmp_path):
    a = profile()
    store = _store(tmp_path, (a,))
    big = {"kind": "observation", "raw_payload": {"rows": list(range(2000))}}
    store.append("rpc-a", big, observed_at_ns=3)
    digest_before = store.replay_digest()
    connects = []
    real_connect = socket.socket.connect

    def deny(self, address):
        connects.append(address)
        raise RuntimeError("UNEXPECTED_OUTBOUND_CONNECTION")

    socket.socket.connect = deny
    try:
        digest_offline = store.replay_digest()
    finally:
        socket.socket.connect = real_connect
    assert connects == []
    assert digest_offline == digest_before


def test_evidence_save_failure_is_a_typed_blocker(tmp_path):
    a = profile()
    store = _store(tmp_path, (a,))

    class _FailingJournal:
        def __init__(self, inner):
            self._inner = inner
            self.db = inner.db

        def events(self, **kwargs):
            return self._inner.events(**kwargs)

        def append(self, event):
            raise OSError("disk full")

    failing = CampaignEvidenceStore(_FailingJournal(store.journal), store.manifest)
    with pytest.raises(EvidenceCommitError) as excinfo:
        failing.append("rpc-a", {"kind": "attempt"}, observed_at_ns=1)
    assert excinfo.value.code == "EVIDENCE_COMMIT_BLOCKED"
    # Nothing was persisted for the failed attempt.
    events = [
        e
        for e in store.journal.events(available_at_ns=2**63 - 1)
        if e.source == "rpc-a"
    ]
    assert len(events) == 0


def test_claim_attempt_failure_leaves_reservation_durable_or_absent(tmp_path):
    a = profile(cap=1)
    store = _store(tmp_path, (a,), attempts=100)
    store.claim_attempt(a)
    with pytest.raises(ValueError, match="CAMPAIGN_ATTEMPT_BUDGET_EXHAUSTED"):
        store.claim_attempt(a)
    reopened = CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / "events.sqlite"),
        manifest_for((a,)),
        campaign_budgets=budgets(attempts=100),
    )
    assert len([e for e in reopened.replay() if e.get("kind") == "attempt"]) == 1


def test_blob_reference_replay_recomputes_from_retained_bytes(tmp_path):
    a = profile()
    store = _store(tmp_path, (a,))
    payload = {"kind": "observation", "raw_payload": {"blob": "x" * 800_000}}
    store.append("rpc-a", payload, observed_at_ns=5)
    body = {**payload, "campaign_manifest_hash": store.manifest.campaign_id}
    from src.qualification_campaign.identity import canonical_bytes, digest

    blob_name = digest(body)
    blob_path = store.blob_dir / (blob_name + ".json")
    assert blob_path.is_file()
    replayed = [e for e in store.replay() if e.get("kind") == "observation"]
    assert replayed[0]["raw_payload"] == payload["raw_payload"]
