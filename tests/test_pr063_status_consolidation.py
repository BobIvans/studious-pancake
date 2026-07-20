from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import pytest

from src.execution.models import ExecutionState
from src.submission import (
    CanonicalFollowupAction,
    CanonicalStatusReport,
    CanonicalSubmissionStack,
    SubmissionAck,
    SubmissionError,
    SubmissionErrorCode,
    SubmissionObservation,
    SubmissionState,
    TransportKind,
    consolidate_canonical_observations,
    poll_canonical_status_once,
)


def observation(
    state: SubmissionState,
    source: str,
    observed_at_ns: int,
    *,
    reason: str | None = None,
) -> SubmissionObservation:
    return SubmissionObservation(
        state=state,
        source=source,
        observed_at_ns=observed_at_ns,
        reason=reason,
    )


def test_jito_landed_without_solana_proof_remains_ambiguous() -> None:
    report = consolidate_canonical_observations(
        TransportKind.JITO_BUNDLE,
        (
            observation(
                SubmissionState.UNKNOWN,
                "solana.getSignatureStatuses",
                1,
                reason="signature missing",
            ),
            observation(
                SubmissionState.LANDED,
                "jito.getInflightBundleStatuses",
                2,
            ),
            observation(
                SubmissionState.LANDED,
                "jito.getBundleStatuses",
                3,
            ),
        ),
    )

    assert report.state is SubmissionState.UNKNOWN
    assert report.ambiguous is True
    assert report.authoritative_source == "solana.getSignatureStatuses"
    assert report.followup.action is CanonicalFollowupAction.RECONCILE_WITHOUT_RESEND
    assert report.followup.durable_state is ExecutionState.RECONCILING
    assert report.automatic_resubmit_allowed is False
    assert report.resend_same_payload_allowed is False


def test_solana_landing_remains_authoritative_over_stale_jito_failure() -> None:
    report = consolidate_canonical_observations(
        TransportKind.JITO_SINGLE,
        (
            observation(
                SubmissionState.LANDED,
                "solana.getSignatureStatuses",
                5,
            ),
            observation(
                SubmissionState.FAILED,
                "jito.getInflightBundleStatuses",
                4,
            ),
        ),
    )

    assert report.state is SubmissionState.LANDED
    assert report.ambiguous is False
    assert report.followup.action is CanonicalFollowupAction.RECORD_LANDING
    assert report.followup.durable_state is ExecutionState.LANDED
    assert report.followup.resend_same_payload_allowed is False


def test_expiry_with_unresolved_jito_delivery_becomes_unknown() -> None:
    report = consolidate_canonical_observations(
        TransportKind.JITO_BUNDLE,
        (
            observation(
                SubmissionState.EXPIRED,
                "solana.getSignatureStatuses",
                10,
            ),
            observation(
                SubmissionState.UNKNOWN,
                "jito.getBundleStatuses",
                11,
            ),
        ),
    )

    assert report.state is SubmissionState.UNKNOWN
    assert report.ambiguous is True
    assert report.followup.action is CanonicalFollowupAction.RECONCILE_WITHOUT_RESEND
    assert report.followup.requires_new_permit is False


def test_proven_failure_requires_reviewed_rebuild_and_new_permit() -> None:
    report = consolidate_canonical_observations(
        TransportKind.RPC,
        (
            observation(
                SubmissionState.FAILED,
                "solana.getSignatureStatuses",
                20,
            ),
        ),
    )

    assert report.state is SubmissionState.FAILED
    assert report.ambiguous is False
    assert report.followup.action is CanonicalFollowupAction.REVIEWED_REBUILD_NEW_PERMIT
    assert report.followup.requires_new_permit is True
    assert report.followup.resend_same_payload_allowed is False
    assert report.automatic_resubmit_allowed is False


def test_rpc_report_rejects_jito_evidence() -> None:
    with pytest.raises(ValueError, match="cannot contain Jito"):
        consolidate_canonical_observations(
            TransportKind.RPC,
            (
                observation(
                    SubmissionState.UNKNOWN,
                    "solana.getSignatureStatuses",
                    1,
                ),
                observation(
                    SubmissionState.UNKNOWN,
                    "jito.getBundleStatuses",
                    2,
                ),
            ),
        )


def test_exactly_one_solana_observation_is_required() -> None:
    with pytest.raises(ValueError, match="exactly one aggregate Solana"):
        consolidate_canonical_observations(
            TransportKind.JITO_BUNDLE,
            (
                observation(
                    SubmissionState.UNKNOWN,
                    "jito.getBundleStatuses",
                    1,
                ),
            ),
        )


@dataclass
class FakeStatusClient:
    calls: list[str]

    async def signature_statuses(
        self,
        _ack: SubmissionAck,
        *,
        current_block_height: int,
        last_valid_block_height: int,
    ) -> SubmissionObservation:
        assert current_block_height == 100
        assert last_valid_block_height == 120
        self.calls.append("solana")
        return observation(
            SubmissionState.UNKNOWN,
            "solana.getSignatureStatuses",
            30,
        )

    async def jito_inflight_status(
        self,
        _ack: SubmissionAck,
    ) -> SubmissionObservation:
        self.calls.append("inflight")
        return observation(
            SubmissionState.LANDED,
            "jito.getInflightBundleStatuses",
            31,
        )

    async def jito_bundle_status(
        self,
        _ack: SubmissionAck,
    ) -> SubmissionObservation:
        self.calls.append("bundle")
        return observation(
            SubmissionState.LANDED,
            "jito.getBundleStatuses",
            32,
        )


@pytest.mark.asyncio
async def test_poll_once_uses_status_routes_without_resubmission() -> None:
    client = FakeStatusClient([])
    stack = cast(
        CanonicalSubmissionStack,
        SimpleNamespace(
            status_client=client,
            transport=TransportKind.JITO_BUNDLE,
        ),
    )
    ack = SubmissionAck(
        state=SubmissionState.ACCEPTED,
        transport=TransportKind.JITO_BUNDLE,
        request_id="request-1",
        transaction_signatures=("signature-1",),
        bundle_id="a" * 64,
        accepted_at_ns=1,
    )

    report = await poll_canonical_status_once(
        stack,
        ack,
        current_block_height=100,
        last_valid_block_height=120,
    )

    assert client.calls == ["solana", "inflight", "bundle"]
    assert report.state is SubmissionState.UNKNOWN
    assert report.automatic_resubmit_allowed is False


@pytest.mark.asyncio
async def test_poll_rejects_ack_transport_mismatch_before_network() -> None:
    client = FakeStatusClient([])
    stack = cast(
        CanonicalSubmissionStack,
        SimpleNamespace(status_client=client, transport=TransportKind.RPC),
    )
    ack = SubmissionAck(
        state=SubmissionState.ACCEPTED,
        transport=TransportKind.JITO_SINGLE,
        request_id="request-2",
        transaction_signatures=("signature-2",),
        bundle_id=None,
        accepted_at_ns=2,
    )

    with pytest.raises(SubmissionError) as raised:
        await poll_canonical_status_once(
            stack,
            ack,
            current_block_height=100,
            last_valid_block_height=120,
        )

    assert raised.value.code is SubmissionErrorCode.IDENTITY_MISMATCH
    assert client.calls == []


def test_report_rejects_non_solana_authority() -> None:
    followup_report = consolidate_canonical_observations(
        TransportKind.RPC,
        (
            observation(
                SubmissionState.UNKNOWN,
                "solana.getSignatureStatuses",
                1,
            ),
        ),
    )
    with pytest.raises(ValueError, match="must be a Solana source"):
        CanonicalStatusReport(
            state=followup_report.state,
            observations=followup_report.observations,
            followup=followup_report.followup,
            authoritative_source="jito.getBundleStatuses",
            ambiguous=True,
            reason="invalid authority",
        )
