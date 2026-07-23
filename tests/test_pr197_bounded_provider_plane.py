from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from src.data_plane.bounded_provider_plane_pr197 import (
    DiscoverySnapshot,
    DurableWebhookInbox,
    HardenedEndpointPolicy,
    ProviderPlaneDecision,
    ProviderPlaneError,
    RetryBudget,
    RootedRpcObservation,
    SQLiteQuotaAuthority,
    canonicalize_snapshots,
    deterministic_cycle_id,
    evaluate_rooted_rpc_quorum,
    parse_bounded_json_response,
    provider_plane_report,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def test_endpoint_policy_resolves_and_rejects_private_targets() -> None:
    policy = HardenedEndpointPolicy(allowed_hosts=frozenset({"quote.example.com"}))
    good = policy.validate_url(
        "https://quote.example.com/v1/quote",
        resolver=lambda host: ["8.8.8.8"],
    )
    assert good.hostname == "quote.example.com"
    assert good.addresses == ("8.8.8.8",)

    with pytest.raises(
        ProviderPlaneError, match="PR197_ENDPOINT_PRIVATE_OR_LOCAL_ADDRESS"
    ):
        policy.validate_url(
            "https://quote.example.com/v1/quote",
            resolver=lambda host: ["127.0.0.1"],
        )

    with pytest.raises(ProviderPlaneError, match="PR197_ENDPOINT_HOST_NOT_ALLOWED"):
        policy.validate_url(
            "https://evil.example.com/v1",
            resolver=lambda host: ["8.8.8.8"],
        )


def test_bounded_json_enforces_size_type_depth_and_duplicates() -> None:
    policy = HardenedEndpointPolicy(
        allowed_hosts=frozenset({"quote.example.com"}),
        max_body_bytes=64,
        max_decompressed_bytes=128,
        max_json_depth=4,
    )
    result = parse_bounded_json_response(
        b'{"ok":true,"items":[1,2]}',
        content_type="application/json; charset=utf-8",
        policy=policy,
    )
    assert result.value == {"ok": True, "items": [1, 2]}
    assert result.max_depth_observed == 3

    compressed = gzip.compress(b'{"ok":true}')
    compressed_result = parse_bounded_json_response(
        compressed,
        content_type="application/json",
        content_encoding="gzip",
        policy=policy,
    )
    assert compressed_result.value == {"ok": True}

    with pytest.raises(ProviderPlaneError, match="PR197_UNSUPPORTED_CONTENT_TYPE"):
        parse_bounded_json_response(b"{}", content_type="text/html", policy=policy)

    with pytest.raises(ProviderPlaneError, match="PR197_BODY_TOO_LARGE"):
        parse_bounded_json_response(
            b"{" + b'"x":' + b'"' + b"a" * 70 + b'"}',
            content_type="application/json",
            policy=policy,
        )

    with pytest.raises(ValueError, match="duplicate JSON key"):
        parse_bounded_json_response(
            b'{"x":1,"x":2}',
            content_type="application/json",
            policy=policy,
        )

    with pytest.raises(ProviderPlaneError, match="PR197_JSON_TOO_DEEP"):
        parse_bounded_json_response(
            b'{"a":{"b":{"c":{"d":1}}}}',
            content_type="application/json",
            policy=policy,
        )


def test_retry_budget_is_absolute_across_attempts() -> None:
    budget = RetryBudget(max_attempts=2, total_deadline_ms=100, started_at_ms=1_000)
    budget.assert_attempt_allowed(attempt_number=1, now_ms=1_050)
    assert budget.clamp_retry_after_ms(20, now_ms=1_050) == 20

    with pytest.raises(ProviderPlaneError, match="PR197_RETRY_AFTER_EXCEEDS_DEADLINE"):
        budget.clamp_retry_after_ms(60, now_ms=1_050)

    with pytest.raises(ProviderPlaneError, match="PR197_RETRY_ATTEMPT_EXHAUSTED"):
        budget.assert_attempt_allowed(attempt_number=3, now_ms=1_050)

    with pytest.raises(ProviderPlaneError, match="PR197_RETRY_DEADLINE_EXPIRED"):
        budget.assert_attempt_allowed(attempt_number=2, now_ms=1_101)


def test_sqlite_quota_authority_is_account_wide_across_instances(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "quota.sqlite3"
    first = SQLiteQuotaAuthority(db_path)
    second = SQLiteQuotaAuthority(db_path)
    first.reserve(
        provider="jupiter",
        key_fingerprint=HASH_A,
        now_ms=10_000,
        limit=2,
        bucket_span_ms=60_000,
    )
    reservation = second.reserve(
        provider="jupiter",
        key_fingerprint=HASH_A,
        now_ms=10_100,
        limit=2,
        bucket_span_ms=60_000,
    )
    assert reservation.used_after == 2
    with pytest.raises(ProviderPlaneError, match="PR197_QUOTA_EXHAUSTED"):
        first.reserve(
            provider="jupiter",
            key_fingerprint=HASH_A,
            now_ms=10_200,
            limit=2,
            bucket_span_ms=60_000,
        )
    first.close()
    second.close()


def test_deterministic_cycle_and_snapshot_tie_break_are_replay_stable() -> None:
    first = deterministic_cycle_id(
        opportunity_identity="opportunity/1",
        evidence_generation="generation/1",
        request_payload_hash=HASH_A,
        provider_set=["openocean", "jupiter"],
    )
    second = deterministic_cycle_id(
        opportunity_identity="opportunity/1",
        evidence_generation="generation/1",
        request_payload_hash=HASH_A,
        provider_set=["jupiter", "openocean"],
    )
    assert first == second

    old = DiscoverySnapshot(
        provider="openocean",
        route_id="r1",
        input_mint="SOL",
        output_mint="USDC",
        in_amount=100,
        out_amount=101,
        context_slot=10,
        observed_at_ms=1_000,
        response_hash=HASH_A,
    )
    better = DiscoverySnapshot(
        provider="jupiter",
        route_id="r2",
        input_mint="SOL",
        output_mint="USDC",
        in_amount=100,
        out_amount=105,
        context_slot=11,
        observed_at_ms=1_001,
        response_hash=HASH_B,
    )
    assert canonicalize_snapshots([old, better]) == (better,)


def test_rooted_rpc_quorum_accepts_only_coherent_independent_sources() -> None:
    one = RootedRpcObservation(
        provider="helius",
        correlation_group="a",
        genesis_hash=HASH_A,
        rooted_slot=1_000,
        min_context_slot=900,
        state_hash=HASH_B,
    )
    two = RootedRpcObservation(
        provider="triton",
        correlation_group="b",
        genesis_hash=HASH_A,
        rooted_slot=990,
        min_context_slot=900,
        state_hash=HASH_B,
    )
    verdict = evaluate_rooted_rpc_quorum([one, two])
    assert verdict.accepted is True
    assert verdict.rooted_slot == 990
    assert verdict.generation_id is not None

    forked = RootedRpcObservation(
        provider="fork",
        correlation_group="c",
        genesis_hash=HASH_A,
        rooted_slot=991,
        min_context_slot=900,
        state_hash=HASH_C,
    )
    blocked = evaluate_rooted_rpc_quorum([one, forked])
    assert blocked.accepted is False
    assert "PR197_RPC_STATE_DISAGREEMENT" in blocked.blockers


def test_webhook_inbox_persists_before_200_and_rejects_rebound_delivery(
    tmp_path: Path,
) -> None:
    token = "Bearer secret-token"
    inbox = DurableWebhookInbox(
        tmp_path / "inbox.sqlite3",
        auth_token_hash=HASH_A.replace("a", "0"),
    )
    # Recreate with a real token hash so the test does not depend on fixture constants.
    inbox.close()
    import hashlib

    inbox = DurableWebhookInbox(
        tmp_path / "inbox.sqlite3",
        auth_token_hash=hashlib.sha256(token.encode()).hexdigest(),
    )
    body = json.dumps({"signature": "sig1", "slot": 100}).encode()
    accepted = inbox.receive(
        delivery_id="delivery-1",
        body=body,
        authorization=token,
        received_at_ms=1_000,
    )
    assert accepted.decision is ProviderPlaneDecision.ACCEPTED
    assert accepted.status_code == 200
    assert inbox.pending_payloads() == ({"signature": "sig1", "slot": 100},)

    duplicate = inbox.receive(
        delivery_id="delivery-1",
        body=body,
        authorization=token,
        received_at_ms=1_001,
    )
    assert duplicate.decision is ProviderPlaneDecision.DUPLICATE
    assert duplicate.status_code == 200

    rebound = inbox.receive(
        delivery_id="delivery-1",
        body=json.dumps({"signature": "sig2", "slot": 101}).encode(),
        authorization=token,
        received_at_ms=1_002,
    )
    assert rebound.decision is ProviderPlaneDecision.REJECTED
    assert rebound.status_code == 409
    inbox.close()


def test_report_is_sender_free_and_binds_candidate_hash(tmp_path: Path) -> None:
    quota = SQLiteQuotaAuthority(tmp_path / "quota.sqlite3")
    reservation = quota.reserve(
        provider="jupiter",
        key_fingerprint=HASH_A,
        now_ms=10_000,
        limit=10,
        bucket_span_ms=60_000,
    )
    observation = RootedRpcObservation(
        provider="helius",
        correlation_group="a",
        genesis_hash=HASH_A,
        rooted_slot=1_000,
        min_context_slot=900,
        state_hash=HASH_B,
    )
    observation_two = RootedRpcObservation(
        provider="triton",
        correlation_group="b",
        genesis_hash=HASH_A,
        rooted_slot=1_000,
        min_context_slot=900,
        state_hash=HASH_B,
    )
    cycle_id = deterministic_cycle_id(
        opportunity_identity="opportunity/1",
        evidence_generation="generation/1",
        request_payload_hash=HASH_C,
        provider_set=["helius", "triton"],
    )
    snapshot = DiscoverySnapshot(
        provider="jupiter",
        route_id="route-1",
        input_mint="SOL",
        output_mint="USDC",
        in_amount=1,
        out_amount=2,
        context_slot=1_000,
        observed_at_ms=10_000,
        response_hash=HASH_A,
    )
    report = provider_plane_report(
        cycle_id=cycle_id,
        quota_reservation=reservation,
        rpc_quorum=evaluate_rooted_rpc_quorum([observation, observation_two]),
        snapshots=[snapshot],
    )
    assert report["live_enabled"] is False
    assert report["signer_reachable"] is False
    assert report["sender_reachable"] is False
    assert report["submission_allowed"] is False
    assert report["candidate_count"] == 1
    assert isinstance(report["candidate_hash"], str)
    quota.close()
