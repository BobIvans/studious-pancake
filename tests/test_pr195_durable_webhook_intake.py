from __future__ import annotations

import pytest

from src.pr195_durable_webhook_intake import (
    DurableWebhookInbox,
    WebhookClaimError,
    WebhookSchemaError,
)


def _event(*, slot: int = 100, signature: str = "sig-a", **extra: object):
    payload: dict[str, object] = {
        "signature": signature,
        "slot": slot,
        "type": "SWAP",
    }
    payload.update(extra)
    return payload


def test_receive_batch_commits_before_ack_and_survives_restart(tmp_path) -> None:
    db = tmp_path / "webhook.db"
    inbox = DurableWebhookInbox(db)

    receipt = inbox.receive_batch(
        provider="helius",
        webhook_id="lst-arb",
        events=[_event()],
    )

    assert receipt.ack_allowed is True
    assert receipt.events_committed == 1
    assert inbox.counts().pending == 1
    inbox.close()

    reopened = DurableWebhookInbox(db)
    assert reopened.counts().pending == 1


def test_receive_batch_rejects_malformed_payload_before_receipt(tmp_path) -> None:
    inbox = DurableWebhookInbox(tmp_path / "webhook.db")

    with pytest.raises(WebhookSchemaError):
        inbox.receive_batch(
            provider="helius",
            webhook_id="lst-arb",
            events=[_event(), "not-a-dict"],  # type: ignore[list-item]
        )

    assert inbox.counts().total_events == 0
    assert inbox.counts().conflicts == 0


def test_chain_identity_is_separate_from_payload_hash(tmp_path) -> None:
    inbox = DurableWebhookInbox(tmp_path / "webhook.db")
    first = _event(slot=7, signature="same-chain-event")
    enriched = _event(
        slot=7,
        signature="same-chain-event",
        provider_metadata={"enriched": True},
    )

    assert (
        inbox.receive_batch(
            provider="helius",
            webhook_id="lst-arb",
            events=[first],
        ).events_committed
        == 1
    )
    second = inbox.receive_batch(
        provider="helius",
        webhook_id="lst-arb",
        events=[enriched],
    )

    assert second.events_committed == 0
    assert second.conflicts_quarantined == 1
    assert inbox.counts().pending == 1
    assert inbox.counts().conflicts == 1


def test_claim_ack_is_owned_and_removes_pending_work(tmp_path) -> None:
    inbox = DurableWebhookInbox(tmp_path / "webhook.db")
    inbox.receive_batch(provider="helius", webhook_id="lst-arb", events=[_event()])

    claimed = inbox.claim_next(owner="worker-a", lease_expires_ns=10)

    assert claimed is not None
    assert claimed.attempt_count == 1
    assert inbox.counts().claimed == 1

    with pytest.raises(WebhookClaimError):
        inbox.ack_event(event_id=claimed.event_id, owner="worker-b")

    inbox.ack_event(event_id=claimed.event_id, owner="worker-a")
    counts = inbox.counts()
    assert counts.pending == 0
    assert counts.claimed == 0
    assert counts.processed == 1


def test_nack_retries_then_dead_letters_poison_event(tmp_path) -> None:
    inbox = DurableWebhookInbox(tmp_path / "webhook.db", max_attempts=2)
    inbox.receive_batch(provider="helius", webhook_id="lst-arb", events=[_event()])

    first = inbox.claim_next(owner="worker-a", lease_expires_ns=10)
    assert first is not None
    inbox.nack_event(
        event_id=first.event_id,
        owner="worker-a",
        error="TRANSIENT_DECODER_ERROR",
    )
    assert inbox.counts().pending == 1

    second = inbox.claim_next(owner="worker-a", lease_expires_ns=20)
    assert second is not None
    inbox.nack_event(
        event_id=second.event_id,
        owner="worker-a",
        error="PERMANENT_DECODER_ERROR",
    )

    counts = inbox.counts()
    assert counts.pending == 0
    assert counts.dead_letter == 1


def test_expired_claims_return_to_pending_for_restart_recovery(tmp_path) -> None:
    inbox = DurableWebhookInbox(tmp_path / "webhook.db")
    inbox.receive_batch(provider="helius", webhook_id="lst-arb", events=[_event()])
    claimed = inbox.claim_next(owner="worker-a", lease_expires_ns=10)

    assert claimed is not None
    assert inbox.reclaim_expired_claims(now_ns=9) == 0
    assert inbox.reclaim_expired_claims(now_ns=10) == 1
    assert inbox.counts().pending == 1
