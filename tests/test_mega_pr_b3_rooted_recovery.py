from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3

import pytest

from src.providers.helius.delivery import (
    DeliveryDecision,
    DeliveryLimits,
    HeliusDeliveryConfig,
    HeliusDeliveryPlane,
)
from src.providers.helius.receiver import collect_bounded_body
from src.providers.helius.rooted_recovery import (
    RecoveryPolicy,
    RecoveryStatus,
    RootedBackfillResult,
    RootedRecoveryStore,
    RootedRecoveryWorker,
    VerifiedProviderEvent,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def event(signature: str, slot: int) -> dict[str, object]:
    return {
        "signature": signature,
        "slot": slot,
        "type": "SWAP",
        "timestamp": 1,
    }


def body(events: list[dict[str, object]]) -> bytes:
    return json.dumps(events).encode()


def plane(tmp_path, *, max_slot_gap: int = 3, clock=None):
    return HeliusDeliveryPlane(
        HeliusDeliveryConfig(
            auth_header="Bearer secret",
            store_path=tmp_path / "helius.sqlite3",
            webhook_id="wh-main",
            limits=DeliveryLimits(
                max_slot_gap=max_slot_gap,
                max_json_depth=10,
                max_json_nodes=200,
                max_events=20,
            ),
        ),
        **({} if clock is None else {"clock_monotonic_ns": clock}),
    )


def deliver(delivery, events):
    return delivery.accept_delivery(
        headers={"Authorization": "Bearer secret"},
        raw_body=body(events),
    )


def test_reordered_duplicate_events_do_not_create_new_inbox_rows(tmp_path):
    delivery = plane(tmp_path)
    first = deliver(delivery, [event("a", 100), event("b", 101)])
    second = deliver(delivery, [event("b", 101), event("a", 100)])

    assert first.accepted_event_count == 2
    assert second.decision is DeliveryDecision.ACK_DUPLICATE
    assert second.accepted_event_count == 0
    assert second.duplicate_event_count == 2
    assert delivery.store.inbox_count() == 2


def test_gap_does_not_advance_contiguous_cursor(tmp_path):
    delivery = plane(tmp_path, max_slot_gap=3)
    assert deliver(delivery, [event("a", 100)]).http_status == 200
    outcome = deliver(delivery, [event("b", 110)])

    assert outcome.backfill_required
    with sqlite3.connect(tmp_path / "helius.sqlite3") as connection:
        row = connection.execute(
            """
            SELECT last_slot, gap_from_slot, gap_to_slot
            FROM helius_gap_state
            WHERE webhook_id = 'wh-main'
            """
        ).fetchone()
    assert row == (100, 101, 109)


def test_streaming_gzip_bomb_is_bounded_before_delivery(tmp_path):
    delivery = plane(tmp_path)
    compressed = gzip.compress(b"x" * 10_000)

    outcome = delivery.accept_delivery(
        headers={
            "Authorization": "Bearer secret",
            "Content-Encoding": "gzip",
        },
        raw_body=compressed,
    )

    assert outcome.reason in {
        "BAD_JSON",
        "JSON_TOO_LARGE",
        "COMPRESSION_RATIO_EXCEEDED",
    }


@pytest.mark.asyncio
async def test_receiver_body_collection_enforces_limit_and_deadline():
    async def chunks():
        yield b"abc"
        yield b"def"

    assert await collect_bounded_body(
        chunks(),
        max_compressed_bytes=6,
        deadline_monotonic_ns=10,
        clock_monotonic_ns=lambda: 1,
    ) == b"abcdef"

    with pytest.raises(OverflowError):
        await collect_bounded_body(
            chunks(),
            max_compressed_bytes=5,
            deadline_monotonic_ns=10,
            clock_monotonic_ns=lambda: 1,
        )

    with pytest.raises(TimeoutError):
        await collect_bounded_body(
            chunks(),
            max_compressed_bytes=6,
            deadline_monotonic_ns=0,
            clock_monotonic_ns=lambda: 1,
        )


class Backfill:
    def __init__(self, *, accepted=True):
        self.accepted = accepted
        self.calls = 0

    def recover(
        self,
        *,
        webhook_id,
        gap_from_slot,
        gap_to_slot,
        release_digest,
        policy_bundle_hash,
        now_monotonic_ns,
    ):
        self.calls += 1
        return RootedBackfillResult(
            accepted=self.accepted,
            webhook_id=webhook_id,
            gap_from_slot=gap_from_slot,
            gap_to_slot=gap_to_slot,
            rooted_through_slot=gap_to_slot if self.accepted else None,
            rpc_evidence_hash=digest("rpc") if self.accepted else None,
            chain_context_hash=digest("chain") if self.accepted else None,
            release_digest=release_digest,
            policy_bundle_hash=policy_bundle_hash,
            expires_at_monotonic_ns=now_monotonic_ns + 1_000_000,
            reason=(
                "ROOTED_RECOVERED"
                if self.accepted
                else "RPC_DISAGREEMENT"
            ),
        )


class Verifier:
    def __init__(self, *, fail=False):
        self.fail = fail

    def verify(
        self,
        claim,
        *,
        release_digest,
        policy_bundle_hash,
        now_monotonic_ns,
    ):
        if self.fail:
            raise ValueError("secret raw provider error")
        return VerifiedProviderEvent(
            event_identity=claim.event_identity,
            inbox_id=claim.inbox_id,
            webhook_id=claim.webhook_id,
            signature=claim.signature,
            slot=claim.slot,
            payload_hash=claim.payload_hash,
            payload_json=claim.payload_json,
            release_digest=release_digest,
            policy_bundle_hash=policy_bundle_hash,
            provider_evidence_hash=digest("provider"),
            rpc_evidence_hash=digest("rpc"),
            chain_context_hash=digest("chain"),
            expires_at_monotonic_ns=now_monotonic_ns + 1_000_000,
            verifier_identity="independent-verifier",
        )


class Sink:
    def commit(self, connection, evidence):
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS a3_provider_admission (
                event_identity TEXT PRIMARY KEY,
                evidence_hash TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO a3_provider_admission(event_identity, evidence_hash)
            VALUES (?, ?)
            """,
            (evidence.event_identity, evidence.evidence_hash),
        )
        return f"a3-{evidence.event_identity[:12]}"


def worker(db, clock, *, backfill=None, verifier=None, max_attempts=5):
    return RootedRecoveryWorker(
        store=RootedRecoveryStore(db),
        backfill=backfill or Backfill(),
        verifier=verifier or Verifier(),
        sink=Sink(),
        release_digest=digest("release"),
        policy_bundle_hash=digest("policy"),
        policy=RecoveryPolicy(
            lease_duration_ns=100,
            retry_delay_ns=10,
            max_attempts=max_attempts,
        ),
        clock_monotonic_ns=lambda: clock[0],
    )


def test_rooted_gap_recovery_and_a3_handoff_are_durable(tmp_path):
    delivery = plane(tmp_path, max_slot_gap=3)
    deliver(delivery, [event("a", 100)])
    deliver(delivery, [event("b", 110)])
    clock = [1_000]
    backfill = Backfill()
    recovery = worker(
        tmp_path / "helius.sqlite3",
        clock,
        backfill=backfill,
    )

    first = recovery.run_once("worker-a")
    second = recovery.run_once("worker-a")

    assert first.status is RecoveryStatus.ADMITTED
    assert second.status is RecoveryStatus.ADMITTED
    assert backfill.calls == 1
    with sqlite3.connect(tmp_path / "helius.sqlite3") as connection:
        gap = connection.execute(
            """
            SELECT last_slot, gap_from_slot, gap_to_slot
            FROM helius_gap_state
            WHERE webhook_id = 'wh-main'
            """
        ).fetchone()
        handoffs = connection.execute(
            "SELECT COUNT(*) FROM helius_a3_handoff"
        ).fetchone()[0]
        a3_rows = connection.execute(
            "SELECT COUNT(*) FROM a3_provider_admission"
        ).fetchone()[0]
    assert gap == (109, None, None)
    assert handoffs == 2
    assert a3_rows == 2


def test_unresolved_gap_never_advances_cursor_or_hands_off(tmp_path):
    delivery = plane(tmp_path, max_slot_gap=3)
    deliver(delivery, [event("a", 100)])
    deliver(delivery, [event("b", 110)])
    clock = [1_000]
    recovery = worker(
        tmp_path / "helius.sqlite3",
        clock,
        backfill=Backfill(accepted=False),
    )

    outcome = recovery.run_once("worker-a")

    assert outcome.status is RecoveryStatus.GAP_BLOCKED
    with sqlite3.connect(tmp_path / "helius.sqlite3") as connection:
        gap = connection.execute(
            """
            SELECT last_slot, gap_from_slot, gap_to_slot
            FROM helius_gap_state
            WHERE webhook_id = 'wh-main'
            """
        ).fetchone()
        handoffs = connection.execute(
            "SELECT COUNT(*) FROM helius_a3_handoff"
        ).fetchone()[0]
    assert gap == (100, 101, 109)
    assert handoffs == 0


def test_expired_worker_lease_is_reclaimed_with_new_fence(tmp_path):
    delivery = plane(tmp_path)
    deliver(delivery, [event("lease", 100)])
    store = RootedRecoveryStore(tmp_path / "helius.sqlite3")
    policy = RecoveryPolicy(
        lease_duration_ns=100,
        retry_delay_ns=10,
        max_attempts=5,
    )

    first = store.claim_next(
        worker_id="worker-a",
        now_monotonic_ns=1_000,
        policy=policy,
    )
    assert first is not None
    assert store.claim_next(
        worker_id="worker-b",
        now_monotonic_ns=1_050,
        policy=policy,
    ) is None
    reclaimed = store.claim_next(
        worker_id="worker-b",
        now_monotonic_ns=1_101,
        policy=policy,
    )

    assert reclaimed is not None
    assert reclaimed.fencing_token == first.fencing_token + 1
    assert reclaimed.attempt == first.attempt + 1


def test_retries_end_in_dead_letter_without_raw_exception(tmp_path):
    delivery = plane(tmp_path)
    deliver(delivery, [event("bad", 100)])
    clock = [1_000]
    recovery = worker(
        tmp_path / "helius.sqlite3",
        clock,
        verifier=Verifier(fail=True),
        max_attempts=2,
    )

    first = recovery.run_once("worker-a")
    clock[0] += 20
    second = recovery.run_once("worker-b")

    assert first.status is RecoveryStatus.RETRY
    assert second.status is RecoveryStatus.DEAD_LETTER
    assert "SECRET" not in second.reason
    with sqlite3.connect(tmp_path / "helius.sqlite3") as connection:
        row = connection.execute(
            "SELECT reason, attempts FROM helius_dead_letter"
        ).fetchone()
    assert row == ("B3_VERIFY_OR_HANDOFF_VALUEERROR", 2)
