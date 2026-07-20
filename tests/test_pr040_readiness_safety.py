from __future__ import annotations

from pathlib import Path

from src.data_plane import (
    CommitmentLevel,
    DataConsistencyPolicy,
    DataPlaneReadinessAggregator,
    DataPlaneReason,
    OracleConsistencyGate,
    OraclePolicy,
    OracleSample,
    OracleStatus,
    ReadinessState,
    RpcConsistencyGate,
    RpcSample,
    SubscriptionSpec,
    WebSocketSubscriptionSupervisor,
    canonical_payload_hash,
    canonical_request_hash,
)


def test_aggregate_readiness_never_promotes_rpc_or_oracle_ambiguity() -> None:
    now_wall, now_mono = 10_000, 5_000
    request = canonical_request_hash("getAccountInfo", ["account"])
    payload = canonical_payload_hash({"context": {"slot": 10}, "value": "ok"})
    samples = [
        RpcSample(
            endpoint,
            "genesis",
            "getAccountInfo",
            request,
            10,
            CommitmentLevel.CONFIRMED,
            payload,
            now_wall,
            now_mono,
            latency,
        )
        for endpoint, latency in (("a", 1), ("b", 2))
    ]
    rpc = RpcConsistencyGate(DataConsistencyPolicy()).evaluate(
        samples,
        expected_genesis_hash="genesis",
        expected_method="getAccountInfo",
        expected_request_hash=request,
        min_context_slot=10,
        now_wall_ms=now_wall,
        now_monotonic_ms=now_mono,
    )
    ws = WebSocketSubscriptionSupervisor(DataConsistencyPolicy())
    ws.register(
        SubscriptionSpec(
            "account",
            "accountSubscribe",
            canonical_payload_hash(["account"]),
            CommitmentLevel.CONFIRMED,
        )
    )
    generation = ws.on_connected("a", now_mono)
    ws.bind_subscription(
        "a", generation=generation, key="account", server_subscription_id=1
    )
    ws_report = ws.readiness(now_monotonic_ms=now_mono)
    oracle = OracleConsistencyGate(
        DataConsistencyPolicy(), OraclePolicy(("pyth",), max_confidence_bps=10)
    ).evaluate(
        OracleSample(
            "pyth",
            "SOL/USD",
            OracleStatus.TRADING,
            100_000,
            -3,
            10,
            10,
            now_wall,
            now_mono,
            canonical_payload_hash({"oracle": 1}),
        ),
        min_context_slot=10,
        now_wall_ms=now_wall,
        now_monotonic_ms=now_mono,
    )
    aggregate = DataPlaneReadinessAggregator().evaluate(
        rpc=rpc,
        websocket=ws_report,
        oracle=oracle,
        detector_inflight=0,
        detector_limit=10,
    )
    assert aggregate.state is ReadinessState.READY

    one_rpc = RpcConsistencyGate(DataConsistencyPolicy()).evaluate(
        samples[:1],
        expected_genesis_hash="genesis",
        expected_method="getAccountInfo",
        expected_request_hash=request,
        min_context_slot=10,
        now_wall_ms=now_wall,
        now_monotonic_ms=now_mono,
    )
    blocked = DataPlaneReadinessAggregator().evaluate(
        rpc=one_rpc,
        websocket=ws_report,
        oracle=oracle,
        detector_inflight=0,
        detector_limit=10,
    )
    assert blocked.state is ReadinessState.NOT_READY
    assert DataPlaneReason.RPC_INSUFFICIENT_EVIDENCE.value in blocked.reasons


def test_package_has_no_network_sender_signer_or_secret_side_effects() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("src/data_plane").glob("*.py"))
    )
    forbidden = (
        "import aiohttp",
        "import requests",
        "sendTransaction",
        "send_bundle",
        "Keypair",
        "private_key",
        "Jito",
    )
    assert not any(token in source for token in forbidden)
