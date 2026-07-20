from __future__ import annotations

import hashlib
import hmac

import pytest

from src.data_plane import (
    AuthenticatedWebhookGuard,
    DataConsistencyPolicy,
    DataPlaneError,
    DataPlaneReason,
    DetectorBackpressureGate,
    HmacSha256Verifier,
    OracleConsistencyGate,
    OraclePolicy,
    OracleSample,
    OracleStatus,
    PollingFallbackController,
    canonical_payload_hash,
)

NOW_WALL = 10_000_000
NOW_MONO = 5_000_000


def oracle(**changes) -> OracleSample:
    values = {
        "source": "pyth-push",
        "feed_id": "SOL/USD",
        "status": OracleStatus.TRADING,
        "price_mantissa": 150_000_000,
        "exponent": -6,
        "confidence_mantissa": 100_000,
        "publish_slot": 120,
        "publish_wall_ms": NOW_WALL - 100,
        "observed_monotonic_ms": NOW_MONO - 100,
        "payload_hash": canonical_payload_hash({"feed": "SOL/USD", "slot": 120}),
    }
    values.update(changes)
    return OracleSample(**values)


def gate() -> OracleConsistencyGate:
    return OracleConsistencyGate(
        DataConsistencyPolicy(),
        OraclePolicy(("pyth-push",), max_confidence_bps=10),
    )


def evaluate(sample: OracleSample):
    return gate().evaluate(
        sample,
        min_context_slot=118,
        now_wall_ms=NOW_WALL,
        now_monotonic_ms=NOW_MONO,
    )


def test_oracle_source_status_slot_age_and_integer_confidence() -> None:
    accepted = evaluate(oracle())
    assert accepted.accepted is True
    assert accepted.confidence_bps == 7
    assert (
        evaluate(oracle(source="unknown")).reason
        is DataPlaneReason.ORACLE_SOURCE_NOT_ALLOWED
    )
    assert (
        evaluate(oracle(status=OracleStatus.HALTED)).reason
        is DataPlaneReason.ORACLE_NOT_TRADING
    )
    assert (
        evaluate(oracle(publish_slot=117)).reason
        is DataPlaneReason.BELOW_MIN_CONTEXT_SLOT
    )
    assert (
        evaluate(
            oracle(
                publish_wall_ms=NOW_WALL - 10_000,
                observed_monotonic_ms=NOW_MONO - 10_000,
            )
        ).reason
        is DataPlaneReason.STALE_OBSERVATION
    )
    assert (
        evaluate(oracle(confidence_mantissa=1_000_000)).reason
        is DataPlaneReason.ORACLE_CONFIDENCE_TOO_WIDE
    )


def test_polling_fallback_and_detector_admission_are_bounded() -> None:
    polls = PollingFallbackController(
        DataConsistencyPolicy(polling_max_inflight=1, polling_min_interval_ms=100)
    )
    first = polls.acquire("pool-a", now_monotonic_ms=1_000)
    with pytest.raises(DataPlaneError) as capacity:
        polls.acquire("pool-b", now_monotonic_ms=1_000)
    assert capacity.value.reason is DataPlaneReason.POLL_CAPACITY_EXHAUSTED
    assert polls.release(first) is True
    with pytest.raises(DataPlaneError) as cooldown:
        polls.acquire("pool-a", now_monotonic_ms=1_050)
    assert cooldown.value.reason is DataPlaneReason.POLL_COOLDOWN

    detectors = DetectorBackpressureGate(DataConsistencyPolicy(detector_max_inflight=1))
    permit = detectors.acquire("candidate-a")
    assert detectors.acquire("candidate-a") == permit
    with pytest.raises(DataPlaneError) as full:
        detectors.acquire("candidate-b")
    assert full.value.reason is DataPlaneReason.BACKPRESSURE
    assert detectors.release(permit) is True


def test_authenticated_webhook_blocks_bad_auth_replay_stale_and_oversize() -> None:
    secret = b"0123456789abcdef0123456789abcdef"
    guard = AuthenticatedWebhookGuard(
        DataConsistencyPolicy(webhook_max_body_bytes=8, webhook_max_age_ms=100),
        HmacSha256Verifier(secret),
    )
    body = b"event"
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    accepted = guard.admit(
        delivery_id="delivery-1",
        sent_wall_ms=1_000,
        raw_body=body,
        signature=signature,
        now_wall_ms=1_050,
    )
    assert accepted.accepted is True
    assert (
        guard.admit(
            delivery_id="delivery-1",
            sent_wall_ms=1_000,
            raw_body=body,
            signature=signature,
            now_wall_ms=1_051,
        ).reason
        is DataPlaneReason.WEBHOOK_REPLAY
    )
    assert (
        guard.admit(
            delivery_id="delivery-2",
            sent_wall_ms=1_000,
            raw_body=body,
            signature="0" * 64,
            now_wall_ms=1_050,
        ).reason
        is DataPlaneReason.WEBHOOK_AUTH_FAILED
    )
    assert (
        guard.admit(
            delivery_id="delivery-3",
            sent_wall_ms=900,
            raw_body=body,
            signature=signature,
            now_wall_ms=1_001,
        ).reason
        is DataPlaneReason.WEBHOOK_TIMESTAMP_INVALID
    )
    large = b"123456789"
    assert (
        guard.admit(
            delivery_id="delivery-4",
            sent_wall_ms=1_000,
            raw_body=large,
            signature=hmac.new(secret, large, hashlib.sha256).hexdigest(),
            now_wall_ms=1_050,
        ).reason
        is DataPlaneReason.WEBHOOK_BODY_TOO_LARGE
    )
