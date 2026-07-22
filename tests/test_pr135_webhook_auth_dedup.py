from __future__ import annotations

import pytest

from src.webhook_ingest_pr135 import (
    DurableWebhookStore,
    ExpectedWebhookConfig,
    HeliusWebhookAuthConfig,
    ObservedWebhookConfig,
    WebhookAuthDecision,
    WebhookConfigDecision,
    WebhookGapDecision,
    WebhookPayloadKind,
    WebhookQueueDecision,
    WebhookSchemaError,
    build_helius_envelope,
    compare_webhook_config,
    evaluate_gap_recovery,
    extract_helius_identity,
    redacted_secret_hash,
    verify_helius_authorization,
)


def _auth_config() -> HeliusWebhookAuthConfig:
    return HeliusWebhookAuthConfig(
        expected_authorization="Bearer whsec_test_value",
        secret_ref="env:HELIUS_WEBHOOK_AUTH_HEADER",
        network="mainnet",
        webhook_type=WebhookPayloadKind.ENHANCED_TRANSACTION,
    )


def _enhanced_payload(signature: str = "sig_1", slot: int = 101) -> dict[str, object]:
    return {
        "signature": signature,
        "slot": slot,
        "type": "SWAP",
        "transactionError": None,
        "source": "JUPITER",
    }


def _raw_payload(signature: str = "raw_sig_1", slot: int = 201) -> dict[str, object]:
    return {
        "slot": slot,
        "transaction": {"signatures": [signature]},
        "meta": {"err": None},
    }


def _accepted_auth():
    return verify_helius_authorization(
        {"Authorization": "Bearer whsec_test_value"},
        _auth_config(),
    )


def test_pr135_helius_auth_uses_authorization_header_constant_time_contract() -> None:
    result = _accepted_auth()

    assert result.decision is WebhookAuthDecision.ACCEPTED
    assert result.reason == "authorization_header_matches_configured_auth_header"
    assert result.redacted_auth_hash == redacted_secret_hash("Bearer whsec_test_value")


def test_pr135_helius_auth_rejects_missing_or_wrong_authorization() -> None:
    missing = verify_helius_authorization({}, _auth_config())
    wrong = verify_helius_authorization(
        {"authorization": "Bearer attacker"},
        _auth_config(),
    )

    assert missing.decision is WebhookAuthDecision.REJECTED
    assert wrong.decision is WebhookAuthDecision.REJECTED
    assert "whsec_test_value" not in repr(_auth_config())


def test_pr135_does_not_claim_body_hmac_signature_headers() -> None:
    result = verify_helius_authorization(
        {
            "Authorization": "Bearer whsec_test_value",
            "X-Signature": "ignored-body-hmac",
        },
        _auth_config(),
    )

    assert result.decision is WebhookAuthDecision.ACCEPTED


def test_pr135_durable_identity_uses_signature_slot_index_and_payload_hash() -> None:
    first = extract_helius_identity(_enhanced_payload(), event_index=0)
    second = extract_helius_identity(
        {
            **_enhanced_payload(),
            "source": "RAYDIUM",
        },
        event_index=0,
    )

    assert first.signature == "sig_1"
    assert first.slot == 101
    assert first.event_index == 0
    assert first.key != second.key


def test_pr135_persistent_dedup_survives_store_restart(tmp_path) -> None:
    db_path = tmp_path / "webhooks.sqlite3"
    envelope = build_helius_envelope(
        _enhanced_payload(),
        payload_kind=WebhookPayloadKind.ENHANCED_TRANSACTION,
        received_unix_ms=1_800_000_000_000,
        auth_result=_accepted_auth(),
    )

    store = DurableWebhookStore(db_path)
    first = store.enqueue(envelope)
    store.close()

    restarted = DurableWebhookStore(db_path)
    duplicate = restarted.enqueue(envelope)

    assert first.decision is WebhookQueueDecision.ENQUEUED
    assert first.status_code == 200
    assert duplicate.decision is WebhookQueueDecision.DUPLICATE
    assert duplicate.status_code == 200
    assert restarted.count() == 1
    restarted.close()


def test_pr135_enqueue_returns_immediate_200_after_enqueue(tmp_path) -> None:
    store = DurableWebhookStore(tmp_path / "webhooks.sqlite3")
    envelope = build_helius_envelope(
        _enhanced_payload(signature="sig_2"),
        payload_kind=WebhookPayloadKind.ENHANCED_TRANSACTION,
        received_unix_ms=1_800_000_000_001,
        auth_result=_accepted_auth(),
    )

    result = store.enqueue(envelope)

    assert result.status_code == 200
    assert result.should_process_async is True
    assert result.stored_sequence == 1
    store.close()


def test_pr135_raw_and_enhanced_schema_are_distinct() -> None:
    enhanced = build_helius_envelope(
        _enhanced_payload(),
        payload_kind=WebhookPayloadKind.ENHANCED_TRANSACTION,
        received_unix_ms=1,
        auth_result=_accepted_auth(),
    )
    raw = build_helius_envelope(
        _raw_payload(),
        payload_kind=WebhookPayloadKind.RAW_TRANSACTION,
        received_unix_ms=2,
        auth_result=_accepted_auth(),
    )

    assert enhanced.payload_schema == "helius_enhanced_transaction"
    assert raw.payload_schema == "helius_raw_transaction"


def test_pr135_failed_transaction_policy_is_preserved_not_hidden() -> None:
    envelope = build_helius_envelope(
        {
            **_enhanced_payload(signature="failed_sig"),
            "transactionError": {"InstructionError": [1, "Custom"]},
        },
        payload_kind=WebhookPayloadKind.ENHANCED_TRANSACTION,
        received_unix_ms=1,
        auth_result=_accepted_auth(),
    )

    assert envelope.failed_transaction is True


def test_pr135_rejects_payload_without_signature_or_slot() -> None:
    with pytest.raises(WebhookSchemaError):
        extract_helius_identity({"type": "SWAP", "slot": 10})

    with pytest.raises(WebhookSchemaError):
        extract_helius_identity({"signature": "sig_without_slot", "type": "SWAP"})


def test_pr135_gap_recovery_requires_backfill_on_large_slot_jump(tmp_path) -> None:
    store = DurableWebhookStore(tmp_path / "webhooks.sqlite3")
    envelope = build_helius_envelope(
        _enhanced_payload(signature="sig_gap", slot=100),
        payload_kind=WebhookPayloadKind.ENHANCED_TRANSACTION,
        received_unix_ms=1,
        auth_result=_accepted_auth(),
    )
    store.enqueue(envelope)

    current = evaluate_gap_recovery(store, 102, max_allowed_slot_gap=3)
    gap = evaluate_gap_recovery(store, 110, max_allowed_slot_gap=3)

    assert current is WebhookGapDecision.CURRENT
    assert gap is WebhookGapDecision.GAP_RECOVERY_REQUIRED
    store.close()


def test_pr135_webhook_config_drift_detects_auth_addresses_and_active_state() -> None:
    expected = ExpectedWebhookConfig(
        webhook_id="wh_1",
        network="mainnet",
        webhook_type=WebhookPayloadKind.ENHANCED_TRANSACTION,
        monitored_addresses_hash="addr_hash_a",
        auth_header_secret_ref="env:HELIUS_WEBHOOK_AUTH_HEADER",
        active=True,
    )
    observed = ObservedWebhookConfig(
        webhook_id="wh_1",
        network="mainnet",
        webhook_type=WebhookPayloadKind.ENHANCED_TRANSACTION,
        monitored_addresses_hash="addr_hash_b",
        auth_header_secret_ref="env:OTHER_SECRET",
        active=False,
    )

    result = compare_webhook_config(expected, observed)

    assert result.decision is WebhookConfigDecision.DRIFTED
    assert result.drift_fields == (
        "monitored_addresses_hash",
        "auth_header_secret_ref",
        "active",
    )


def test_pr135_webhook_config_match_has_no_drift() -> None:
    expected = ExpectedWebhookConfig(
        webhook_id="wh_1",
        network="mainnet",
        webhook_type=WebhookPayloadKind.RAW_TRANSACTION,
        monitored_addresses_hash="addr_hash_a",
        auth_header_secret_ref="env:HELIUS_WEBHOOK_AUTH_HEADER",
        active=True,
    )
    observed = ObservedWebhookConfig(
        webhook_id="wh_1",
        network="mainnet",
        webhook_type=WebhookPayloadKind.RAW_TRANSACTION,
        monitored_addresses_hash="addr_hash_a",
        auth_header_secret_ref="env:HELIUS_WEBHOOK_AUTH_HEADER",
        active=True,
    )

    result = compare_webhook_config(expected, observed)

    assert result.decision is WebhookConfigDecision.MATCHED
    assert result.drift_fields == ()
