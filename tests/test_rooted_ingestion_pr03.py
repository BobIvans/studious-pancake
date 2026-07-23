from __future__ import annotations

import hashlib
import json
import sqlite3
import time

import pytest

from src.providers.rooted_ingestion_pr03 import (
    A3RootedProviderBatchSource,
    HmacSha256EvidenceAuthenticator,
    ProviderAdmissionBinding,
    ProviderVerificationError,
    RootedProviderEvidenceVerifier,
    RootedProviderIngestionStore,
    RootedProviderIngestionWorker,
    RootedRpcEvidence,
    RpcRootObservation,
    WorkerDecision,
)


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def seed(db_path, *, gap=False):
    payload = json.dumps(
        {"signature": "sig-1", "slot": 120},
        sort_keys=True,
        separators=(",", ":"),
    )
    event_id = h("event-1")
    delivery_id = h("delivery-1")
    now = time.time_ns()
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE helius_delivery(
            delivery_id TEXT PRIMARY KEY,
            webhook_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            received_at_ns INTEGER NOT NULL,
            event_count INTEGER NOT NULL,
            duplicate_count INTEGER NOT NULL,
            failed_event_count INTEGER NOT NULL,
            gap_detected INTEGER NOT NULL,
            backfill_required INTEGER NOT NULL
        );
        CREATE TABLE helius_event_inbox(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dedup_key TEXT UNIQUE NOT NULL,
            delivery_id TEXT NOT NULL,
            signature TEXT NOT NULL,
            slot INTEGER,
            event_index INTEGER NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json TEXT,
            failed INTEGER NOT NULL,
            queued_at_ns INTEGER NOT NULL,
            processed_at_ns INTEGER,
            state TEXT NOT NULL DEFAULT 'queued',
            correction_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE helius_gap_state(
            webhook_id TEXT PRIMARY KEY,
            last_slot INTEGER,
            gap_from_slot INTEGER,
            gap_to_slot INTEGER,
            updated_at_ns INTEGER NOT NULL
        );
        """)
    con.execute(
        "INSERT INTO helius_delivery VALUES(?,?,?,?,?,?,?,?,?)",
        (delivery_id, "webhook-1", h(payload), now, 1, 0, 0, int(gap), int(gap)),
    )
    con.execute(
        "INSERT INTO helius_event_inbox"
        "(dedup_key,delivery_id,signature,slot,event_index,payload_hash,"
        "payload_json,failed,queued_at_ns,state)"
        " VALUES(?,?,?,?,?,?,?,?,?,'queued')",
        (event_id, delivery_id, "sig-1", 120, 0, h(payload), payload, 0, now),
    )
    if gap:
        con.execute(
            "INSERT INTO helius_gap_state VALUES(?,?,?,?,?)",
            ("webhook-1", 100, 101, 119, now),
        )
    con.commit()
    con.close()
    return event_id


def admission(now):
    return ProviderAdmissionBinding(
        provider="helius",
        decision="admitted",
        evidence_hash=h("admission"),
        endpoint_identity_hash=h("helius-endpoint"),
        expires_at_ns=now + 60_000_000_000,
    )


def quorum(now, *, same_group=False, stale=False):
    observed = now - (60_000_000_000 if stale else 1_000_000)
    return RootedRpcEvidence(
        (
            RpcRootObservation(
                provider_id="rpc-a",
                correlation_group="group-a",
                endpoint_identity_hash=h("rpc-a"),
                genesis_hash="mainnet-beta",
                rooted_slot=125,
                transaction_signature="sig-1",
                transaction_slot=120,
                transaction_found=True,
                response_hash=h("response-a"),
                observed_at_ns=observed,
            ),
            RpcRootObservation(
                provider_id="rpc-b",
                correlation_group="group-a" if same_group else "group-b",
                endpoint_identity_hash=h("rpc-b"),
                genesis_hash="mainnet-beta",
                rooted_slot=126,
                transaction_signature="sig-1",
                transaction_slot=120,
                transaction_found=True,
                response_hash=h("response-b"),
                observed_at_ns=observed,
            ),
        )
    )


class Collector:
    def __init__(self, evidence=None, error=None):
        self.evidence = evidence
        self.error = error

    def collect(self, *, signature, slot):
        assert signature == "sig-1"
        assert slot == 120
        if self.error:
            raise ProviderVerificationError(self.error)
        return self.evidence


def build(db_path, now, evidence):
    auth = HmacSha256EvidenceAuthenticator(
        trust_anchor_id="pr03-test-anchor",
        secret=b"x" * 32,
    )
    store = RootedProviderIngestionStore(db_path, now_ns=lambda: now)
    verifier = RootedProviderEvidenceVerifier(
        expected_genesis="mainnet-beta",
        release_id="release-1",
        policy_bundle_hash=h("policy-1"),
        authenticator=auth,
        now_ns=lambda: now,
    )
    worker = RootedProviderIngestionWorker(
        store=store,
        verifier=verifier,
        collector=Collector(evidence),
    )
    return auth, store, verifier, worker


def test_rooted_event_is_atomically_handed_to_a3(tmp_path):
    db = tmp_path / "helius.sqlite3"
    event_id = seed(db)
    now = time.time_ns()
    auth, store, _, worker = build(db, now, quorum(now))

    outcome = worker.run_once(admission(now))

    assert outcome.decision is WorkerDecision.ADMITTED
    assert outcome.event_id == event_id
    assert outcome.evidence_hash
    assert outcome.handoff_id
    with sqlite3.connect(db) as con:
        state = con.execute("SELECT state FROM helius_event_inbox").fetchone()[0]
        assert state == "verified"
        count = con.execute("SELECT COUNT(*) FROM pr03_provider_handoff").fetchone()[0]
        assert count == 1

    batch = A3RootedProviderBatchSource(store=store, authenticator=auth)()
    assert batch.evidence.ready is True
    assert batch.evidence.blockers == ()
    assert len(batch.items) == 1
    assert batch.items[0].event_id == event_id


def test_unresolved_gap_blocks_and_keeps_event_queued(tmp_path):
    db = tmp_path / "helius.sqlite3"
    seed(db, gap=True)
    now = time.time_ns()
    _, _, _, worker = build(db, now, quorum(now))

    outcome = worker.run_once(admission(now))

    assert outcome.decision is WorkerDecision.RETRYABLE_BLOCKED
    assert outcome.reason_code == "PR03_ROOTED_GAP_RECOVERY_REQUIRED"
    with sqlite3.connect(db) as con:
        state = con.execute("SELECT state FROM helius_event_inbox").fetchone()[0]
        assert state == "queued"
        count = con.execute("SELECT COUNT(*) FROM pr03_provider_handoff").fetchone()[0]
        assert count == 0


def test_rpc_quorum_requires_independent_correlation_groups(tmp_path):
    db = tmp_path / "helius.sqlite3"
    seed(db)
    now = time.time_ns()
    _, _, _, worker = build(db, now, quorum(now, same_group=True))

    outcome = worker.run_once(admission(now))

    assert outcome.decision is WorkerDecision.RETRYABLE_BLOCKED
    assert outcome.reason_code == "PR03_RPC_CORRELATION_GROUPS_INSUFFICIENT"


def test_provider_drift_revokes_admission(tmp_path):
    db = tmp_path / "helius.sqlite3"
    seed(db)
    now = time.time_ns()
    _, _, _, worker = build(db, now, quorum(now))
    drifted = ProviderAdmissionBinding(
        provider="helius",
        decision="admitted",
        evidence_hash=h("admission"),
        endpoint_identity_hash=h("helius-endpoint"),
        expires_at_ns=now + 60_000_000_000,
        drift_detected=True,
    )

    outcome = worker.run_once(drifted)

    assert outcome.decision is WorkerDecision.RETRYABLE_BLOCKED
    assert outcome.reason_code == "PR03_PROVIDER_DRIFT_DETECTED"


def test_upstream_outage_does_not_dead_letter_valid_event(tmp_path):
    db = tmp_path / "helius.sqlite3"
    seed(db)
    now = time.time_ns()
    auth, store, verifier, _ = build(db, now, quorum(now))
    worker = RootedProviderIngestionWorker(
        store=store,
        verifier=verifier,
        collector=Collector(error="PR03_RPC_UPSTREAM_UNAVAILABLE"),
    )

    outcome = worker.run_once(admission(now))

    assert outcome.decision is WorkerDecision.RETRYABLE_BLOCKED
    with sqlite3.connect(db) as con:
        state = con.execute("SELECT state FROM helius_event_inbox").fetchone()[0]
        assert state == "queued"
        count = con.execute(
            "SELECT COUNT(*) FROM pr03_provider_handoff_audit"
        ).fetchone()[0]
        assert count == 1
    batch = A3RootedProviderBatchSource(store=store, authenticator=auth)()
    assert batch.evidence.ready is False


def test_tampered_stored_evidence_fails_closed_at_a3_boundary(tmp_path):
    db = tmp_path / "helius.sqlite3"
    seed(db)
    now = time.time_ns()
    auth, store, _, worker = build(db, now, quorum(now))
    assert worker.run_once(admission(now)).decision is WorkerDecision.ADMITTED
    with sqlite3.connect(db) as con:
        raw = con.execute(
            "SELECT evidence_json FROM pr03_verified_provider_evidence"
        ).fetchone()[0]
        payload = json.loads(raw)
        payload["slot"] = 121
        con.execute(
            "UPDATE pr03_verified_provider_evidence SET evidence_json=?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
        )
        con.commit()

    batch = A3RootedProviderBatchSource(store=store, authenticator=auth)()

    assert batch.evidence.ready is False
    assert batch.evidence.blockers == ("PR03_STORED_EVIDENCE_AUTHENTICATION_FAILED",)


def test_duplicate_handoff_rejects_changed_policy_identity(tmp_path):
    db = tmp_path / "helius.sqlite3"
    seed(db)
    now = time.time_ns()
    auth, store, verifier, worker = build(db, now, quorum(now))
    assert worker.run_once(admission(now)).decision is WorkerDecision.ADMITTED
    event = store.next_queued_event()
    assert event is None
    with sqlite3.connect(db) as con:
        con.execute("UPDATE helius_event_inbox SET state='queued'")
        con.commit()
    event = store.next_queued_event()
    assert event is not None
    changed = RootedProviderEvidenceVerifier(
        expected_genesis="mainnet-beta",
        release_id="release-1",
        policy_bundle_hash=h("policy-2"),
        authenticator=auth,
        now_ns=lambda: now + 1,
    ).verify(event=event, admission=admission(now), quorum=quorum(now))

    with pytest.raises(
        ProviderVerificationError,
        match="PR03_DUPLICATE_HANDOFF_IDENTITY_CONFLICT",
    ):
        store.commit_verified(event=event, evidence=changed)


def test_expired_stored_evidence_fails_closed_before_a3(tmp_path):
    db = tmp_path / "helius.sqlite3"
    seed(db)
    now = time.time_ns()
    auth, _, _, worker = build(db, now, quorum(now))
    assert worker.run_once(admission(now)).decision is WorkerDecision.ADMITTED
    expired_store = RootedProviderIngestionStore(
        db,
        now_ns=lambda: now + 31_000_000_000,
    )

    batch = A3RootedProviderBatchSource(
        store=expired_store,
        authenticator=auth,
    )()

    assert batch.evidence.ready is False
    assert batch.evidence.blockers == ("PR03_STORED_EVIDENCE_EXPIRED",)


def test_tampered_handoff_metadata_fails_closed_at_a3_boundary(tmp_path):
    db = tmp_path / "helius.sqlite3"
    seed(db)
    now = time.time_ns()
    auth, store, _, worker = build(db, now, quorum(now))
    assert worker.run_once(admission(now)).decision is WorkerDecision.ADMITTED
    with sqlite3.connect(db) as con:
        con.execute(
            "UPDATE pr03_provider_handoff SET release_id=?",
            ("release-tampered",),
        )
        con.commit()

    batch = A3RootedProviderBatchSource(store=store, authenticator=auth)()

    assert batch.evidence.ready is False
    assert batch.evidence.blockers == ("PR03_STORED_EVIDENCE_BINDING_MISMATCH",)
