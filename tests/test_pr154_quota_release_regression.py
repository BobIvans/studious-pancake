from __future__ import annotations

import asyncio
from pathlib import Path

from src.data_plane.pr154_reliability_supervisor import (
    DataIngressStatus,
    DataReliabilitySupervisor,
    DurableDataPlaneJournal,
    ProviderIngressRequest,
)
from src.providers.jupiter.quota import JupiterQuotaManager, JupiterQuotaPurpose


class RaisingQuorumGate:
    def evaluate(self, *args: object, **kwargs: object) -> object:
        raise ValueError("malformed rooted quorum input")


def test_pr154_quorum_validation_exception_releases_unissued_quota(
    tmp_path: Path,
) -> None:
    quota = JupiterQuotaManager(
        limit=10,
        window_seconds=60.0,
        finalization_reserve=2,
        clock=lambda: 1.0,
    )
    journal = DurableDataPlaneJournal(tmp_path / "data-plane.db")
    supervisor = DataReliabilitySupervisor(
        quota=quota,
        rpc_quorum=RaisingQuorumGate(),  # type: ignore[arg-type]
        journal=journal,
        clock_monotonic_ms=lambda: 1_000,
    )
    request = ProviderIngressRequest(
        event_key="provider-malformed-quorum",
        candidate_id="candidate-1",
        quota_purpose=JupiterQuotaPurpose.FINALIZATION,
        request_fingerprint="jupiter-build-candidate-1",
        deadline_monotonic_ms=2_000,
        queue_depth=0,
        queue_capacity=10,
        rooted_samples=(),
        expected_genesis_hash="mainnet-genesis",
        expected_method="getAccountInfo",
        expected_request_hash="1" * 64,
        min_context_slot=100,
        now_wall_ms=1_000,
        now_monotonic_ms=1_000,
    )

    decision = asyncio.run(supervisor.admit_provider(request))

    assert decision.status is DataIngressStatus.RPC_BLOCKED
    assert decision.reason == "PR154_RPC_VALIDATION_VALUEERROR"
    assert decision.accepted is False
    assert journal.count() == 1
    assert quota.snapshot()["released"] == 1
    assert quota.snapshot()["used"] == 0
