from __future__ import annotations

from src.data_plane import (
    CommitmentLevel,
    RootedRpcQuorumGate,
    RootedRpcQuorumPolicy,
    RootedRpcQuorumReason,
    RootedRpcSample,
    RpcEndpointIdentity,
    RpcSample,
    canonical_payload_hash,
    canonical_request_hash,
)

GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
NOW_WALL = 10_000_000
NOW_MONO = 5_000_000
REQUEST = canonical_request_hash("getMultipleAccounts", ["vault-a", "vault-b"])
PAYLOAD = canonical_payload_hash({"context": {"slot": 120}, "value": ["ok"]})


def identity(
    endpoint_id: str,
    *,
    provider: str,
    operator: str,
    correlation_group: str,
    feature_set: int = 123,
    max_supported_transaction_version: int = 0,
    genesis_hash: str = GENESIS,
) -> RpcEndpointIdentity:
    return RpcEndpointIdentity(
        endpoint_id=endpoint_id,
        provider=provider,
        operator=operator,
        correlation_group=correlation_group,
        region="eu",
        endpoint_account=f"{provider}-paid",
        genesis_hash=genesis_hash,
        node_version="solana-core/3.0.0",
        feature_set=feature_set,
        max_supported_transaction_version=max_supported_transaction_version,
        observed_wall_ms=NOW_WALL - 20,
        observed_monotonic_ms=NOW_MONO - 20,
        evidence_expires_at_monotonic_ms=NOW_MONO + 10_000,
    )


def rpc_sample(
    endpoint_id: str,
    *,
    payload_hash: str = PAYLOAD,
    context_slot: int = 120,
    commitment: CommitmentLevel = CommitmentLevel.FINALIZED,
    genesis_hash: str = GENESIS,
    latency_ms: int = 20,
) -> RpcSample:
    return RpcSample(
        endpoint_id=endpoint_id,
        genesis_hash=genesis_hash,
        method="getMultipleAccounts",
        request_hash=REQUEST,
        context_slot=context_slot,
        commitment=commitment,
        payload_hash=payload_hash,
        observed_wall_ms=NOW_WALL - 10,
        observed_monotonic_ms=NOW_MONO - 10,
        latency_ms=latency_ms,
    )


def rooted(
    endpoint_id: str,
    *,
    provider: str,
    operator: str,
    correlation_group: str,
    context_slot: int = 120,
    root_slot: int = 122,
    finalized_slot: int = 123,
    current_slot: int = 124,
    feature_set: int = 123,
    max_supported_transaction_version: int = 0,
    payload_hash: str = PAYLOAD,
    genesis_hash: str = GENESIS,
    latency_ms: int = 20,
) -> RootedRpcSample:
    return RootedRpcSample(
        sample=rpc_sample(
            endpoint_id,
            payload_hash=payload_hash,
            context_slot=context_slot,
            genesis_hash=genesis_hash,
            latency_ms=latency_ms,
        ),
        identity=identity(
            endpoint_id,
            provider=provider,
            operator=operator,
            correlation_group=correlation_group,
            feature_set=feature_set,
            max_supported_transaction_version=max_supported_transaction_version,
            genesis_hash=genesis_hash,
        ),
        current_slot=current_slot,
        finalized_slot=finalized_slot,
        root_slot=root_slot,
        block_hash="rooted-blockhash",
    )


def evaluate(samples: list[RootedRpcSample]):
    return RootedRpcQuorumGate(RootedRpcQuorumPolicy()).evaluate(
        samples,
        expected_genesis_hash=GENESIS,
        expected_method="getMultipleAccounts",
        expected_request_hash=REQUEST,
        min_context_slot=118,
        now_wall_ms=NOW_WALL,
        now_monotonic_ms=NOW_MONO,
    )


def test_pr136_two_correlated_urls_cannot_satisfy_two_source_quorum() -> None:
    decision = evaluate(
        [
            rooted(
                "helius-a",
                provider="helius",
                operator="helius",
                correlation_group="helius-mainnet",
            ),
            rooted(
                "helius-b",
                provider="helius",
                operator="helius",
                correlation_group="helius-mainnet",
            ),
        ]
    )

    assert decision.accepted is False
    assert decision.reason is RootedRpcQuorumReason.CORRELATED_RPC_SOURCES
    assert decision.independent_correlation_groups == ("helius-mainnet",)


def test_pr136_independent_rooted_sources_accept_same_payload() -> None:
    decision = evaluate(
        [
            rooted(
                "helius-a",
                provider="helius",
                operator="helius",
                correlation_group="helius-mainnet",
                latency_ms=30,
            ),
            rooted(
                "triton-a",
                provider="triton",
                operator="triton",
                correlation_group="triton-mainnet",
                latency_ms=15,
            ),
        ]
    )

    assert decision.accepted is True
    assert decision.reason is RootedRpcQuorumReason.OK
    assert decision.canonical_endpoint_id == "triton-a"
    assert decision.independent_correlation_groups == (
        "helius-mainnet",
        "triton-mainnet",
    )


def test_pr136_same_slot_payload_conflict_fails_closed() -> None:
    conflict = canonical_payload_hash({"context": {"slot": 120}, "value": "fork"})
    decision = evaluate(
        [
            rooted(
                "helius-a",
                provider="helius",
                operator="helius",
                correlation_group="helius-mainnet",
            ),
            rooted(
                "triton-a",
                provider="triton",
                operator="triton",
                correlation_group="triton-mainnet",
                payload_hash=conflict,
            ),
        ]
    )

    assert decision.accepted is False
    assert decision.reason is RootedRpcQuorumReason.SAME_SLOT_CONFLICT


def test_pr136_unrooted_or_lagging_endpoint_cannot_join_quorum() -> None:
    unrooted = rooted(
        "helius-a",
        provider="helius",
        operator="helius",
        correlation_group="helius-mainnet",
        root_slot=119,
    )
    good = rooted(
        "triton-a",
        provider="triton",
        operator="triton",
        correlation_group="triton-mainnet",
    )
    decision = evaluate([unrooted, good])

    assert decision.accepted is False
    assert decision.reason is RootedRpcQuorumReason.INSUFFICIENT_INDEPENDENT_EVIDENCE
    assert (
        "helius-a",
        RootedRpcQuorumReason.NOT_ROOTED.value,
    ) in decision.rejected_endpoints


def test_pr136_genesis_and_transaction_version_support_are_required() -> None:
    wrong_genesis = rooted(
        "foreign",
        provider="foreign",
        operator="foreign",
        correlation_group="foreign",
        genesis_hash="foreign-genesis",
    )
    old_node = rooted(
        "old-node",
        provider="old",
        operator="old",
        correlation_group="old",
        max_supported_transaction_version=0,
    )
    policy = RootedRpcQuorumPolicy(min_supported_transaction_version=1)
    decision = RootedRpcQuorumGate(policy).evaluate(
        [wrong_genesis, old_node],
        expected_genesis_hash=GENESIS,
        expected_method="getMultipleAccounts",
        expected_request_hash=REQUEST,
        min_context_slot=118,
        now_wall_ms=NOW_WALL,
        now_monotonic_ms=NOW_MONO,
    )

    assert decision.accepted is False
    assert decision.reason is RootedRpcQuorumReason.GENESIS_MISMATCH
    assert (
        "foreign",
        RootedRpcQuorumReason.GENESIS_MISMATCH.value,
    ) in decision.rejected_endpoints
    assert (
        "old-node",
        RootedRpcQuorumReason.UNSUPPORTED_TX_VERSION.value,
    ) in decision.rejected_endpoints


def test_pr136_feature_set_mismatch_is_not_comparable_by_default() -> None:
    decision = evaluate(
        [
            rooted(
                "helius-a",
                provider="helius",
                operator="helius",
                correlation_group="helius-mainnet",
                feature_set=123,
            ),
            rooted(
                "triton-a",
                provider="triton",
                operator="triton",
                correlation_group="triton-mainnet",
                feature_set=456,
            ),
        ]
    )

    assert decision.accepted is False
    assert decision.reason is RootedRpcQuorumReason.FEATURE_SET_MISMATCH
