from __future__ import annotations

import pytest

from src.data_plane import (
    CommitmentLevel,
    DataConsistencyPolicy,
    DataPlaneError,
    DataPlaneReason,
    ReadinessState,
    RpcConsistencyGate,
    RpcSample,
    SubscriptionSpec,
    SubscriptionState,
    WebSocketSubscriptionSupervisor,
    canonical_payload_hash,
    canonical_request_hash,
)

GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
NOW_WALL = 10_000_000
NOW_MONO = 5_000_000
REQUEST = canonical_request_hash("getMultipleAccounts", ["A", "B"])
PAYLOAD = canonical_payload_hash({"context": {"slot": 120}, "value": [1, 2]})


def sample(endpoint: str, **changes) -> RpcSample:
    values = {
        "endpoint_id": endpoint,
        "genesis_hash": GENESIS,
        "method": "getMultipleAccounts",
        "request_hash": REQUEST,
        "context_slot": 120,
        "commitment": CommitmentLevel.CONFIRMED,
        "payload_hash": PAYLOAD,
        "observed_wall_ms": NOW_WALL - 10,
        "observed_monotonic_ms": NOW_MONO - 10,
        "latency_ms": 20,
        "error_code": None,
    }
    values.update(changes)
    return RpcSample(**values)


def evaluate(samples, policy: DataConsistencyPolicy | None = None, min_slot=118):
    return RpcConsistencyGate(policy or DataConsistencyPolicy()).evaluate(
        samples,
        expected_genesis_hash=GENESIS,
        expected_method="getMultipleAccounts",
        expected_request_hash=REQUEST,
        min_context_slot=min_slot,
        now_wall_ms=NOW_WALL,
        now_monotonic_ms=NOW_MONO,
    )


def test_rpc_exact_highest_slot_match_beats_older_numerical_majority() -> None:
    old = canonical_payload_hash({"slot": 119, "value": "old"})
    result = evaluate(
        [
            sample("fast", latency_ms=5),
            sample("slow", latency_ms=50),
            sample("old-a", context_slot=119, payload_hash=old),
            sample("old-b", context_slot=119, payload_hash=old),
            sample("old-c", context_slot=119, payload_hash=old),
        ]
    )
    assert result.accepted is True
    assert result.canonical_endpoint_id == "fast"
    assert result.matching_endpoints == ("fast", "slow")


def test_rpc_same_slot_conflict_and_slot_divergence_fail_closed() -> None:
    conflict = canonical_payload_hash({"slot": 120, "value": "conflict"})
    same_slot = evaluate([sample("a"), sample("b"), sample("c", payload_hash=conflict)])
    assert same_slot.reason is DataPlaneReason.RPC_SAME_SLOT_CONFLICT

    divergent = evaluate(
        [sample("a", context_slot=120), sample("b", context_slot=117)],
        DataConsistencyPolicy(minimum_matching_rpc_sources=1),
        min_slot=115,
    )
    assert divergent.reason is DataPlaneReason.RPC_SLOT_DIVERGENCE


def test_rpc_filters_foreign_stale_low_commitment_and_below_context() -> None:
    result = evaluate(
        [
            sample("good"),
            sample("foreign", genesis_hash="foreign"),
            sample(
                "stale",
                observed_wall_ms=NOW_WALL - 3_000,
                observed_monotonic_ms=NOW_MONO - 3_000,
            ),
        ]
    )
    assert result.reason is DataPlaneReason.RPC_INSUFFICIENT_EVIDENCE
    assert (
        "foreign",
        DataPlaneReason.RPC_GENESIS_MISMATCH.value,
    ) in result.rejected_endpoints
    assert (
        "stale",
        DataPlaneReason.STALE_OBSERVATION.value,
    ) in result.rejected_endpoints

    low = evaluate(
        [
            sample("a", commitment=CommitmentLevel.PROCESSED),
            sample("b", commitment=CommitmentLevel.PROCESSED),
        ]
    )
    assert low.reason is DataPlaneReason.LOW_COMMITMENT


def test_websocket_reconnect_resubscribe_gap_and_backfill() -> None:
    ws = WebSocketSubscriptionSupervisor(
        DataConsistencyPolicy(websocket_max_slot_gap=2)
    )
    ws.register(
        SubscriptionSpec(
            "pool",
            "accountSubscribe",
            canonical_payload_hash(["pool", {"commitment": "confirmed"}]),
            CommitmentLevel.CONFIRMED,
        )
    )
    generation = ws.on_connected("rpc-a", NOW_MONO)
    assert ws.snapshot("rpc-a").state is SubscriptionState.RESUBSCRIBE_REQUIRED
    ws.bind_subscription(
        "rpc-a", generation=generation, key="pool", server_subscription_id=7
    )
    assert ws.snapshot("rpc-a").state is SubscriptionState.ACTIVE

    assert ws.on_notification(
        "rpc-a",
        generation=generation,
        key="pool",
        context_slot=100,
        now_monotonic_ms=NOW_MONO + 1,
    ).accepted
    gap = ws.on_notification(
        "rpc-a",
        generation=generation,
        key="pool",
        context_slot=105,
        now_monotonic_ms=NOW_MONO + 2,
    )
    assert gap.reason is DataPlaneReason.SLOT_GAP
    assert gap.requires_polling_backfill is True
    with pytest.raises(DataPlaneError):
        ws.mark_backfill_complete("rpc-a", through_slot=103)
    ws.mark_backfill_complete("rpc-a", through_slot=104)
    assert ws.snapshot("rpc-a").state is SubscriptionState.ACTIVE

    ws.on_disconnected("rpc-a")
    new_generation = ws.on_connected("rpc-a", NOW_MONO + 10)
    stale = ws.on_notification(
        "rpc-a",
        generation=generation,
        key="pool",
        context_slot=106,
        now_monotonic_ms=NOW_MONO + 11,
    )
    assert new_generation == generation + 1
    assert stale.reason is DataPlaneReason.WS_RESUBSCRIBE_REQUIRED


def test_websocket_heartbeat_readiness_and_backoff_are_bounded() -> None:
    ws = WebSocketSubscriptionSupervisor(
        DataConsistencyPolicy(websocket_heartbeat_timeout_ms=100)
    )
    ws.register(
        SubscriptionSpec(
            "logs",
            "logsSubscribe",
            canonical_payload_hash({"mentions": ["program"]}),
            CommitmentLevel.CONFIRMED,
        )
    )
    generation = ws.on_connected("rpc-a", 1_000)
    ws.bind_subscription(
        "rpc-a", generation=generation, key="logs", server_subscription_id=1
    )
    assert ws.readiness(now_monotonic_ms=1_050).state is ReadinessState.READY
    assert ws.readiness(now_monotonic_ms=1_101).state is ReadinessState.NOT_READY
    assert ws.next_backoff_ms("rpc-a", 5) == ws.next_backoff_ms("rpc-a", 5)
