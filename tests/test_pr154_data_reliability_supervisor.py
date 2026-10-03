from __future__ import annotations

import asyncio
from pathlib import Path

from src.data_plane.common import CommitmentLevel
from src.data_plane.pr154_reliability_supervisor import (
    DataIngressStatus,
    DataReliabilitySupervisor,
    DurableDataPlaneJournal,
    ProviderIngressRequest,
    WebhookIngressRequest,
)
from src.data_plane.rpc import (
    RootedRpcQuorumGate,
    RootedRpcQuorumPolicy,
    RootedRpcSample,
    RpcEndpointIdentity,
    RpcSample,
)
from src.providers.jupiter.quota import JupiterQuotaManager, JupiterQuotaPurpose
from src.webhook_ingest_pr135 import (
    DurableWebhookIdentity,
    WebhookEnvelope,
    WebhookPayloadKind,
    WebhookProvider,
)

REQUEST_HASH = "1" * 64
PAYLOAD_HASH = "2" * 64
GENESIS = "mainnet-genesis"


def _rooted_sample(endpoint: str, group: str) -> RootedRpcSample:
    sample = RpcSample(
        endpoint_id=endpoint,
        genesis_hash=GENESIS,
        method="getAccountInfo",
        request_hash=REQUEST_HASH,
        context_slot=100,
        commitment=CommitmentLevel.FINALIZED,
        payload_hash=PAYLOAD_HASH,
        observed_wall_ms=900,
        observed_monotonic_ms=900,
        latency_ms=10,
    )
    identity = RpcEndpointIdentity(
        endpoint_id=endpoint,
        provider=endpoint,
        operator=f"operator-{endpoint}",
        correlation_group=group,
        region="eu",
        endpoint_account=f"account-{endpoint}",
        genesis_hash=GENESIS,
        node_version="2.0.0",
        feature_set=1,
        max_supported_transaction_version=0,
        observed_wall_ms=900,
        observed_monotonic_ms=900,
        evidence_expires_at_monotonic_ms=2_000,
    )
    return RootedRpcSample(
        sample=sample,
        identity=identity,
        current_slot=100,
        finalized_slot=100,
        root_slot=100,
        block_hash="block-100",
    )


def _supervisor(tmp_path: Path, *, now_ms: int = 1_000):
    quota = JupiterQuotaManager(
        limit=10,
        window_seconds=60.0,
        finalization_reserve=2,
        clock=lambda: 1.0,
    )
    journal = DurableDataPlaneJournal(tmp_path / "data-plane.db")
    supervisor = DataReliabilitySupervisor(
        quota=quota,
        rpc_quorum=RootedRpcQuorumGate(RootedRpcQuorumPolicy()),
        journal=journal,
        clock_monotonic_ms=lambda: now_ms,
    )
    return supervisor, quota, journal


def _provider_request(
    *,
    event_key: str = "provider-event-1",
    deadline_ms: int = 2_000,
    groups: tuple[str, str] = ("group-a", "group-b"),
    queue_depth: int = 0,
    queue_capacity: int = 10,
) -> ProviderIngressRequest:
    return ProviderIngressRequest(
        event_key=event_key,
        candidate_id="candidate-1",
        quota_purpose=JupiterQuotaPurpose.FINALIZATION,
        request_fingerprint="jupiter-build-candidate-1",
        deadline_monotonic_ms=deadline_ms,
        queue_depth=queue_depth,
        queue_capacity=queue_capacity,
        rooted_samples=(
            _rooted_sample("rpc-a", groups[0]),
            _rooted_sample("rpc-b", groups[1]),
        ),
        expected_genesis_hash=GENESIS,
        expected_method="getAccountInfo",
        expected_request_hash=REQUEST_HASH,
        min_context_slot=100,
        now_wall_ms=1_000,
        now_monotonic_ms=1_000,
    )


def _webhook(signature: str, slot: int) -> WebhookEnvelope:
    return WebhookEnvelope(
        identity=DurableWebhookIdentity(
            provider=WebhookProvider.HELIUS,
            signature=signature,
            slot=slot,
            event_index=0,
            payload_hash=PAYLOAD_HASH,
        ),
        payload_kind=WebhookPayloadKind.RAW_TRANSACTION,
        payload_schema="helius_raw_transaction",
        received_unix_ms=1_000,
        failed_transaction=False,
        redacted_auth_hash="auth-hash",
        payload={"signature": signature, "slot": slot},
    )


def test_pr154_provider_admission_joins_quota_rooted_quorum_and_journal(
    tmp_path: Path,
) -> None:
    supervisor, quota, journal = _supervisor(tmp_path)
    decision = asyncio.run(supervisor.admit_provider(_provider_request()))

    assert decision.status is DataIngressStatus.ADMITTED
    assert decision.accepted is True
    assert decision.canonical_slot == 100
    assert decision.payload_hash == PAYLOAD_HASH
    assert decision.rpc_evidence_hash is not None
    assert decision.quota_reservation_id is not None
    assert journal.count() == 1
    assert quota.snapshot()["used"] == 1


def test_pr154_duplicate_provider_event_does_not_consume_more_quota(
    tmp_path: Path,
) -> None:
    supervisor, quota, _ = _supervisor(tmp_path)
    request = _provider_request()
    first = asyncio.run(supervisor.admit_provider(request))
    second = asyncio.run(supervisor.admit_provider(request))

    assert first.status is DataIngressStatus.ADMITTED
    assert second.status is DataIngressStatus.DUPLICATE
    assert quota.snapshot()["reserved"] == 1


def test_pr154_correlated_rpc_sources_release_unissued_quota(tmp_path: Path) -> None:
    supervisor, quota, _ = _supervisor(tmp_path)
    decision = asyncio.run(
        supervisor.admit_provider(
            _provider_request(groups=("same-provider", "same-provider"))
        )
    )

    assert decision.status is DataIngressStatus.RPC_BLOCKED
    assert decision.accepted is False
    assert "CORRELATED_RPC_SOURCES" in decision.reason
    assert quota.snapshot()["released"] == 1
    assert quota.snapshot()["used"] == 0


def test_pr154_deadline_and_backpressure_block_before_quota(tmp_path: Path) -> None:
    supervisor, quota, _ = _supervisor(tmp_path, now_ms=2_001)
    expired = asyncio.run(
        supervisor.admit_provider(_provider_request(deadline_ms=2_000))
    )
    full = asyncio.run(
        supervisor.admit_provider(
            _provider_request(
                event_key="provider-event-2",
                deadline_ms=3_000,
                queue_depth=10,
                queue_capacity=10,
            )
        )
    )

    assert expired.status is DataIngressStatus.DEADLINE_EXPIRED
    assert full.status is DataIngressStatus.BACKPRESSURE
    assert quota.snapshot()["reserved"] == 0


def test_pr154_webhook_gap_requires_backfill_and_can_be_retried(
    tmp_path: Path,
) -> None:
    supervisor, _, journal = _supervisor(tmp_path)
    first = supervisor.admit_webhook(
        WebhookIngressRequest(
            envelope=_webhook("sig-100", 100),
            queue_depth=0,
            queue_capacity=10,
            max_allowed_slot_gap=2,
            now_monotonic_ms=1_000,
        )
    )
    gap_request = WebhookIngressRequest(
        envelope=_webhook("sig-110", 110),
        queue_depth=0,
        queue_capacity=10,
        max_allowed_slot_gap=2,
        now_monotonic_ms=1_001,
    )
    gap = supervisor.admit_webhook(gap_request)

    for slot in range(101, 110):
        backfill = supervisor.admit_webhook(
            WebhookIngressRequest(
                envelope=_webhook(f"sig-{slot}", slot),
                queue_depth=0,
                queue_capacity=10,
                max_allowed_slot_gap=2,
                now_monotonic_ms=1_000 + slot,
            )
        )
        assert backfill.status is DataIngressStatus.ADMITTED

    retried = supervisor.admit_webhook(gap_request)

    assert first.status is DataIngressStatus.ADMITTED
    assert gap.status is DataIngressStatus.GAP_RECOVERY_REQUIRED
    assert gap.backfill_required is True
    assert retried.status is DataIngressStatus.ADMITTED
    assert journal.last_accepted_webhook_slot() == 110


def test_pr154_webhook_duplicate_and_queue_full_are_durable(tmp_path: Path) -> None:
    supervisor, _, journal = _supervisor(tmp_path)
    envelope = _webhook("sig-200", 200)
    request = WebhookIngressRequest(
        envelope=envelope,
        queue_depth=0,
        queue_capacity=1,
        max_allowed_slot_gap=2,
        now_monotonic_ms=1_000,
    )
    admitted = supervisor.admit_webhook(request)
    duplicate = supervisor.admit_webhook(request)
    full = supervisor.admit_webhook(
        WebhookIngressRequest(
            envelope=_webhook("sig-201", 201),
            queue_depth=1,
            queue_capacity=1,
            max_allowed_slot_gap=2,
            now_monotonic_ms=1_001,
        )
    )

    assert admitted.status is DataIngressStatus.ADMITTED
    assert duplicate.status is DataIngressStatus.DUPLICATE
    assert full.status is DataIngressStatus.BACKPRESSURE
    assert journal.count() == 2
