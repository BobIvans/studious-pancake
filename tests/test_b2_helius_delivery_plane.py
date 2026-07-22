from __future__ import annotations

import gzip
import json
import sqlite3

from src.providers.helius.delivery import (
    DeliveryDecision,
    DeliveryLimits,
    FailedTransactionPolicy,
    HeliusDeliveryConfig,
    HeliusDeliveryPlane,
    HeliusDeliveryStore,
)


def plane(tmp_path, *, auth="Bearer secret", limits=None, failed_policy=FailedTransactionPolicy.PRESERVE):
    return HeliusDeliveryPlane(
        HeliusDeliveryConfig(
            auth_header=auth,
            store_path=tmp_path / "helius_delivery.sqlite3",
            limits=limits or DeliveryLimits(max_json_depth=10, max_json_nodes=200, max_events=10),
            failed_transaction_policy=failed_policy,
            webhook_id="wh-main",
        )
    )


def body(events):
    return json.dumps(events).encode("utf-8")


def event(sig="sig1", slot=100, **extra):
    data = {"signature": sig, "slot": slot, "type": "SWAP", "timestamp": 1}
    data.update(extra)
    return data


def test_valid_delivery_is_durable_before_ack(tmp_path):
    p = plane(tmp_path)
    out = p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=body([event()]))
    assert out.decision == DeliveryDecision.ACK_DURABLE
    assert out.http_status == 200
    assert out.accepted_event_count == 1
    assert p.store.inbox_count() == 1
    assert not out.live_enabled
    assert not out.sender_reachable


def test_missing_or_invalid_auth_rejected_without_secret_leak(tmp_path):
    p = plane(tmp_path)
    missing = p.accept_delivery(headers={}, raw_body=body([event()]))
    invalid = p.accept_delivery(headers={"Authorization": "Bearer wrong"}, raw_body=body([event()]))
    assert missing.http_status == 401
    assert missing.reason == "MISSING_AUTH"
    assert invalid.http_status == 401
    assert invalid.reason == "INVALID_AUTH"
    assert p.store.inbox_count() == 0


def test_gzip_body_is_bounded_and_decoded(tmp_path):
    p = plane(tmp_path)
    out = p.accept_delivery(
        headers={"Authorization": "Bearer secret", "Content-Encoding": "gzip"},
        raw_body=gzip.compress(body([event("sig-gzip", 101)])),
    )
    assert out.http_status == 200
    assert p.store.inbox_count() == 1


def test_compressed_and_decompressed_limits_are_enforced(tmp_path):
    p = plane(tmp_path, limits=DeliveryLimits(max_compressed_bytes=5, max_decompressed_bytes=50))
    too_big = p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=b"x" * 10)
    assert too_big.http_status == 413
    assert too_big.reason == "BODY_TOO_LARGE"

    p2 = plane(tmp_path / "p2", limits=DeliveryLimits(max_compressed_bytes=1000, max_decompressed_bytes=10))
    out = p2.accept_delivery(
        headers={"Authorization": "Bearer secret", "Content-Encoding": "gzip"},
        raw_body=gzip.compress(body([event("sig-big", 102)])),
    )
    assert out.http_status == 413
    assert out.reason == "DECOMPRESSED_BODY_TOO_LARGE"


def test_malformed_utf8_and_json_rejected(tmp_path):
    p = plane(tmp_path)
    bad_utf8 = p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=b"\xff")
    bad_json = p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=b"{")
    assert bad_utf8.reason == "BAD_ENCODING"
    assert bad_json.reason == "BAD_JSON"
    assert p.store.inbox_count() == 0


def test_json_depth_node_and_event_count_limits(tmp_path):
    deep = {"events": [{"a": {"b": {"c": {"d": {"e": 1}}}}}]}
    p = plane(tmp_path, limits=DeliveryLimits(max_json_depth=3, max_json_nodes=100, max_events=10))
    assert p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=json.dumps(deep).encode()).reason == "JSON_TOO_DEEP"

    p2 = plane(tmp_path / "p2", limits=DeliveryLimits(max_json_depth=20, max_json_nodes=3, max_events=10))
    assert p2.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=body([event("n", 1)])).reason == "JSON_TOO_LARGE"

    p3 = plane(tmp_path / "p3", limits=DeliveryLimits(max_json_depth=20, max_json_nodes=100, max_events=1))
    assert p3.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=body([event("a", 1), event("b", 2)])).reason == "TOO_MANY_EVENTS"


def test_duplicate_delivery_acknowledged_but_not_requeued(tmp_path):
    p = plane(tmp_path)
    raw = body([event("dup", 10)])
    first = p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=raw)
    second = p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=raw)
    assert first.accepted_event_count == 1
    assert second.decision == DeliveryDecision.ACK_DUPLICATE
    assert second.duplicate_event_count == 1
    assert p.store.inbox_count() == 1


def test_persistent_dedup_survives_new_plane_instance(tmp_path):
    db = tmp_path / "shared.sqlite3"
    cfg = HeliusDeliveryConfig(auth_header="Bearer secret", store_path=db)
    p1 = HeliusDeliveryPlane(cfg)
    raw = body([event("restart", 10)])
    assert p1.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=raw).accepted_event_count == 1
    p2 = HeliusDeliveryPlane(cfg)
    assert p2.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=raw).decision == DeliveryDecision.ACK_DUPLICATE
    assert p2.store.inbox_count() == 1


def test_two_instances_do_not_create_duplicate_rows(tmp_path):
    db = tmp_path / "shared.sqlite3"
    cfg = HeliusDeliveryConfig(auth_header="Bearer secret", store_path=db)
    p1 = HeliusDeliveryPlane(cfg)
    p2 = HeliusDeliveryPlane(cfg)
    raw = body([event("two-instance", 44)])
    assert p1.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=raw).accepted_event_count == 1
    assert p2.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=raw).duplicate_event_count == 1
    assert HeliusDeliveryStore(db).inbox_count() == 1


def test_slot_gap_sets_backfill_required(tmp_path):
    p = plane(tmp_path, limits=DeliveryLimits(max_slot_gap=3))
    assert p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=body([event("a", 100)])).http_status == 200
    out = p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=body([event("b", 110)]))
    assert out.gap_detected
    assert out.backfill_required


def test_failed_transactions_preserved_by_default(tmp_path):
    p = plane(tmp_path)
    out = p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=body([event("fail", 1, transactionError={"code": 1})]))
    assert out.http_status == 200
    assert out.accepted_event_count == 1
    with sqlite3.connect(tmp_path / "helius_delivery.sqlite3") as con:
        assert con.execute("SELECT failed FROM helius_event_inbox").fetchone()[0] == 1


def test_failed_transaction_reject_policy_is_explicit(tmp_path):
    p = plane(tmp_path, failed_policy=FailedTransactionPolicy.REJECT)
    out = p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=body([event("fail", 1, error="boom")]))
    assert out.http_status == 400
    assert out.reason == "FAILED_TX_REJECTED_BY_POLICY"
    assert p.store.inbox_count() == 0


def test_drop_with_audit_policy_records_reason(tmp_path):
    p = plane(tmp_path, failed_policy=FailedTransactionPolicy.DROP_WITH_AUDIT)
    out = p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=body([event("fail", 1, error="boom")]))
    assert out.http_status == 200
    assert out.accepted_event_count == 0
    assert "failed_event_dropped_by_policy" in p.store.audit_reasons()


def test_payload_hash_not_secret_and_delivery_id_stable(tmp_path):
    p = plane(tmp_path)
    raw = body([event("stable", 1)])
    out = p.accept_delivery(headers={"Authorization": "Bearer secret"}, raw_body=raw)
    assert "secret" not in (out.payload_hash or "")
    assert out.delivery_id
    assert len(out.delivery_id) == 64
