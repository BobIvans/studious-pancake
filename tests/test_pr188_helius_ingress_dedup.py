from __future__ import annotations

# CI regression note: ordinary tests use a relaxed helper deadline so cold
# SQLite/WAL setup on shared runners cannot mask dedup semantics.
import gzip
import json
import os
from pathlib import Path
import sqlite3

from src.providers.helius.delivery import (
    DeliveryDecision,
    DeliveryLimits,
    HeliusDeliveryConfig,
    HeliusDeliveryPlane,
    RejectReason,
)


def _plane(tmp_path: Path, **limit_overrides) -> HeliusDeliveryPlane:
    limits = DeliveryLimits(
        # CI runners can spend more than the production ingress budget on cold
        # SQLite/WAL setup. Keep production defaults in source, but make the
        # ordinary unit-test helper non-flaky; deadline-specific tests override
        # this with intentionally tiny values below.
        delivery_deadline_ms=5_000,
        **limit_overrides,
    )
    return HeliusDeliveryPlane(
        HeliusDeliveryConfig(
            auth_header="Bearer test",
            store_path=tmp_path / "helius.sqlite3",
            limits=limits,
            webhook_id="helius-mainnet",
            cluster_genesis="mainnet-genesis",
        )
    )


def _accept(plane: HeliusDeliveryPlane, payload, *, gzip_body=False):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"authorization": "Bearer test"}
    if gzip_body:
        raw = gzip.compress(raw)
        headers["content-encoding"] = "gzip"
    return plane.accept_delivery(headers=headers, raw_body=raw)


def test_same_signature_changed_payload_is_correction_not_second_queue(
    tmp_path: Path,
) -> None:
    plane = _plane(tmp_path)

    first = _accept(
        plane,
        [{"signature": "SIG1", "slot": 100, "data": "a"}],
    )
    second = _accept(
        plane,
        [{"signature": "SIG1", "slot": 100, "data": "b"}],
    )

    assert first.decision is DeliveryDecision.ACK_DURABLE
    assert first.accepted_event_count == 1
    assert second.decision is DeliveryDecision.ACK_DUPLICATE
    assert second.accepted_event_count == 0
    assert second.duplicate_event_count == 1
    assert plane.store.inbox_count() == 1
    assert plane.store.representation_classifications() == ["new", "correction"]
    assert "event_correction" in plane.store.audit_reasons()


def test_batch_reordering_does_not_change_primary_identity(tmp_path: Path) -> None:
    plane = _plane(tmp_path)
    first_batch = [
        {"signature": "SIG-A", "slot": 100, "data": "a"},
        {"signature": "SIG-B", "slot": 101, "data": "b"},
    ]
    reordered = list(reversed(first_batch))

    first = _accept(plane, first_batch)
    second = _accept(plane, reordered)

    assert first.accepted_event_count == 2
    assert second.accepted_event_count == 0
    assert second.duplicate_event_count == 2
    assert plane.store.inbox_count() == 2


def test_gzip_bomb_is_rejected_by_streaming_bound(tmp_path: Path) -> None:
    plane = _plane(
        tmp_path,
        max_compressed_bytes=100_000,
        max_decompressed_bytes=100_000,
        max_compression_ratio=50,
    )
    raw = gzip.compress(b"[" + b" " * 500_000 + b"]")

    outcome = plane.accept_delivery(
        headers={
            "authorization": "Bearer test",
            "content-encoding": "gzip",
        },
        raw_body=raw,
    )

    assert outcome.http_status == 413
    assert outcome.reason in {
        RejectReason.DECOMPRESSED_BODY_TOO_LARGE.value,
        RejectReason.COMPRESSION_RATIO_EXCEEDED.value,
    }
    assert plane.store.inbox_count() == 0


def test_duplicate_json_keys_and_non_finite_numbers_are_rejected(
    tmp_path: Path,
) -> None:
    plane = _plane(tmp_path)

    duplicate_key = plane.accept_delivery(
        headers={"authorization": "Bearer test"},
        raw_body=b'[{"signature":"SIG","signature":"OTHER","slot":1}]',
    )
    non_finite = plane.accept_delivery(
        headers={"authorization": "Bearer test"},
        raw_body=b'[{"signature":"SIG","slot":NaN}]',
    )

    assert duplicate_key.reason == RejectReason.DUPLICATE_JSON_KEY.value
    assert non_finite.reason == RejectReason.NON_FINITE_JSON_NUMBER.value
    assert plane.store.inbox_count() == 0


def test_slot_gap_creates_one_durable_backfill_job(tmp_path: Path) -> None:
    plane = _plane(tmp_path, max_slot_gap=2)

    _accept(plane, [{"signature": "SIG-1", "slot": 100}])
    gap = _accept(plane, [{"signature": "SIG-2", "slot": 110}])
    replay = _accept(
        plane,
        [{"signature": "SIG-2", "slot": 110, "extra": "correction"}],
    )

    assert gap.gap_detected is True
    assert gap.backfill_required is True
    assert replay.accepted_event_count == 0
    assert plane.store.backfill_count() == 1


def test_database_and_directory_are_owner_only(tmp_path: Path) -> None:
    plane = _plane(tmp_path)
    _accept(plane, [{"signature": "SIG", "slot": 1}])

    if os.name == "posix":
        assert (plane.store.path.stat().st_mode & 0o777) == 0o600
        assert (plane.store.path.parent.stat().st_mode & 0o777) == 0o700


def test_deadline_failure_returns_retryable_status_without_ack(
    tmp_path: Path,
) -> None:
    ticks = iter(
        [
            0,
            0,
            0,
            2_000_000,
            2_000_000,
            2_000_000,
            2_000_000,
        ]
    )

    def clock() -> int:
        return next(ticks, 2_000_000)

    plane = HeliusDeliveryPlane(
        HeliusDeliveryConfig(
            auth_header="Bearer test",
            store_path=tmp_path / "deadline.sqlite3",
            limits=DeliveryLimits(delivery_deadline_ms=1),
        ),
        monotonic_ns=clock,
    )
    outcome = plane.accept_delivery(
        headers={"authorization": "Bearer test"},
        raw_body=b'[{"signature":"SIG","slot":1}]',
    )

    assert outcome.decision is DeliveryDecision.REJECTED
    assert outcome.http_status == 503
    assert outcome.reason == RejectReason.DELIVERY_DEADLINE_EXCEEDED.value
    assert not outcome.acknowledged


def test_database_contention_cannot_return_false_200(tmp_path: Path) -> None:
    plane = _plane(
        tmp_path,
        delivery_deadline_ms=20,
        sqlite_busy_timeout_ms=5,
    )
    blocker = sqlite3.connect(str(plane.store.path), timeout=0)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        outcome = _accept(
            plane,
            [{"signature": "SIG", "slot": 1}],
        )
    finally:
        blocker.rollback()
        blocker.close()

    assert outcome.http_status == 503
    assert outcome.reason == RejectReason.DELIVERY_DEADLINE_EXCEEDED.value
    assert not outcome.acknowledged
