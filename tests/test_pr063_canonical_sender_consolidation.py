from __future__ import annotations

from typing import Mapping
from uuid import uuid4

import pytest

from src.execution.models import ExecutionState
from src.submission.canonical_sender import (
    DEFAULT_JITO_BLOCK_ENGINE_URL,
    JITO_BUNDLE_STATUS_PATH,
    JITO_INFLIGHT_STATUS_PATH,
    JITO_TIP_ACCOUNTS_PATH,
    SOLANA_SIGNATURE_STATUS_METHOD,
    CanonicalFollowupAction,
    CanonicalSenderSettings,
    JitoCredentialMode,
    build_canonical_submission_stack,
    canonical_followup_for_observation,
    canonical_status_routes,
)
from src.submission.permit_bound import (
    HttpResponse,
    JitoSender,
    LivePermitIssuer,
    LiveSubmissionPolicy,
    RpcSender,
    SubmissionError,
    SubmissionErrorCode,
    SubmissionObservation,
    SubmissionState,
    TransportKind,
)


class FakeHttp:
    async def post_json(
        self,
        url: str,
        body: Mapping[str, object],
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse:
        raise AssertionError("PR-063 construction tests must not submit network calls")


def test_rpc_stack_is_single_transport_default_disabled() -> None:
    settings = CanonicalSenderSettings(
        TransportKind.RPC,
        rpc_endpoint="https://rpc.example",
    )

    stack = build_canonical_submission_stack(settings, FakeHttp())

    assert isinstance(stack.sender, RpcSender)
    assert stack.transport is TransportKind.RPC
    assert stack.issuer.policy.enabled is False
    assert stack.issuer.policy.allowed_transports == (TransportKind.RPC,)
    assert stack.duplicate_submission_allowed is False
    assert stack.transport_fallback_allowed is False
    assert len(stack.endpoint_fingerprint) == 64
    assert [route.path_or_method for route in canonical_status_routes(TransportKind.RPC)] == [
        SOLANA_SIGNATURE_STATUS_METHOD
    ]


def test_jito_no_auth_is_explicit_and_keeps_exactly_one_transport() -> None:
    settings = CanonicalSenderSettings(
        TransportKind.JITO_BUNDLE,
        rpc_endpoint="https://rpc.example",
        jito_credential_mode=JitoCredentialMode.NO_AUTH,
        compile_time_enabled=True,
        config_enabled=True,
    )

    stack = build_canonical_submission_stack(settings, FakeHttp())
    routes = [route.path_or_method for route in canonical_status_routes(TransportKind.JITO_BUNDLE)]

    assert isinstance(stack.sender, JitoSender)
    assert stack.issuer.policy.enabled is True
    assert stack.issuer.policy.allowed_transports == (TransportKind.JITO_BUNDLE,)
    assert stack.issuer.policy.require_jito_uuid_auth is False
    assert settings.redacted_manifest()["jito_base_url"] == DEFAULT_JITO_BLOCK_ENGINE_URL
    assert JITO_INFLIGHT_STATUS_PATH in routes
    assert JITO_BUNDLE_STATUS_PATH in routes
    assert JITO_TIP_ACCOUNTS_PATH in routes


def test_jito_uuid_mode_requires_uuid_and_never_leaks_secret() -> None:
    with pytest.raises(SubmissionError) as missing:
        CanonicalSenderSettings(
            TransportKind.JITO_SINGLE,
            rpc_endpoint="https://rpc.example",
            jito_credential_mode=JitoCredentialMode.UUID,
        )
    assert missing.value.code is SubmissionErrorCode.AUTH_INVALID

    settings = CanonicalSenderSettings(
        TransportKind.JITO_SINGLE,
        rpc_endpoint="https://rpc.example",
        jito_credential_mode=JitoCredentialMode.UUID,
        jito_uuid=str(uuid4()),
    )
    manifest = settings.redacted_manifest()

    assert manifest["jito_credential_mode"] == "uuid"
    assert isinstance(manifest["jito_uuid_fingerprint"], str)
    assert str(settings).find(str(settings.jito_uuid)) == -1


def test_mismatched_injected_issuer_is_rejected() -> None:
    settings = CanonicalSenderSettings(
        TransportKind.JITO_SINGLE,
        rpc_endpoint="https://rpc.example",
    )
    wrong_issuer = LivePermitIssuer(
        LiveSubmissionPolicy(allowed_transports=(TransportKind.RPC,))
    )

    with pytest.raises(SubmissionError) as raised:
        build_canonical_submission_stack(settings, FakeHttp(), issuer=wrong_issuer)

    assert raised.value.code is SubmissionErrorCode.PERMIT_INVALID


def test_fallback_and_duplicate_submission_modes_are_unrepresentable() -> None:
    with pytest.raises(SubmissionError) as fallback:
        CanonicalSenderSettings(
            TransportKind.RPC,
            rpc_endpoint="https://rpc.example",
            allow_transport_fallback=True,
        )
    assert fallback.value.code is SubmissionErrorCode.LIVE_GATE_CLOSED

    with pytest.raises(SubmissionError) as duplicate:
        CanonicalSenderSettings(
            TransportKind.RPC,
            rpc_endpoint="https://rpc.example",
            allow_duplicate_submission=True,
        )
    assert duplicate.value.code is SubmissionErrorCode.RESUBMIT_FORBIDDEN


def test_ambiguous_status_goes_to_durable_reconciliation_without_resend() -> None:
    observation = SubmissionObservation(
        SubmissionState.UNKNOWN,
        "jito.getInflightBundleStatuses",
        observed_at_ns=10,
        reason="bundle status is ambiguous",
    )

    followup = canonical_followup_for_observation(observation)

    assert followup.action is CanonicalFollowupAction.RECONCILE_WITHOUT_RESEND
    assert followup.durable_state is ExecutionState.RECONCILING
    assert followup.requires_new_permit is False
    assert followup.resend_same_payload_allowed is False


def test_expired_or_failed_requires_reviewed_rebuild_with_new_permit_only() -> None:
    expired = SubmissionObservation(
        SubmissionState.EXPIRED,
        "solana.getSignatureStatuses",
        observed_at_ns=20,
        reason="blockhash expired",
    )

    followup = canonical_followup_for_observation(expired)

    assert followup.action is CanonicalFollowupAction.REVIEWED_REBUILD_NEW_PERMIT
    assert followup.requires_new_permit is True
    assert followup.resend_same_payload_allowed is False
    assert followup.durable_state is ExecutionState.RECONCILING
