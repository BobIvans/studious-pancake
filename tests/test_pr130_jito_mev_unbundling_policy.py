from __future__ import annotations

import pytest

from src.submission.canonical_sender import CanonicalSenderSettings
from src.submission.jito_mev_policy import (
    JitoMevProtectionState,
    PR130_JITO_MEV_POLICY_SCHEMA_VERSION,
    evaluate_pr130_jito_mev_policy,
)
from src.submission.permit_bound import (
    ErrorDisposition,
    SubmissionError,
    SubmissionErrorCode,
    TransportKind,
)


def test_pr130_first_production_jito_single_shape_is_ready() -> None:
    result = evaluate_pr130_jito_mev_policy(
        transport=TransportKind.JITO_SINGLE,
        transaction_count=1,
        tip_transaction_index=0,
        bundle_only=True,
        tip_account_static=True,
        bundle_ack_treated_as_settlement=False,
    )

    assert result.ready is True
    assert result.state is JitoMevProtectionState.READY
    assert result.blockers == ()
    assert result.to_dict()["schema_version"] == PR130_JITO_MEV_POLICY_SCHEMA_VERSION


def test_pr130_standalone_tip_transaction_is_blocked() -> None:
    result = evaluate_pr130_jito_mev_policy(
        transport=TransportKind.JITO_BUNDLE,
        transaction_count=2,
        tip_transaction_index=1,
        bundle_only=False,
        tip_account_static=True,
        bundle_ack_treated_as_settlement=False,
    )

    assert result.ready is False
    assert result.state is JitoMevProtectionState.BLOCKED
    assert "MULTI_TRANSACTION_JITO_BUNDLE_DISABLED_FOR_PR130" in result.blockers
    assert "JITO_PAYLOAD_MUST_CONTAIN_EXACTLY_ONE_TRANSACTION" in result.blockers
    assert "STANDALONE_TIP_TRANSACTION_FORBIDDEN" in result.blockers


def test_pr130_bundle_ack_or_status_is_not_settlement_proof() -> None:
    result = evaluate_pr130_jito_mev_policy(
        transport=TransportKind.JITO_SINGLE,
        transaction_count=1,
        tip_transaction_index=0,
        bundle_only=True,
        tip_account_static=True,
        bundle_ack_treated_as_settlement=True,
    )

    assert result.ready is False
    assert "JITO_BUNDLE_STATUS_NOT_SETTLEMENT_PROOF" in result.blockers


def test_pr130_alt_tip_account_is_blocked() -> None:
    result = evaluate_pr130_jito_mev_policy(
        transport=TransportKind.JITO_SINGLE,
        transaction_count=1,
        tip_transaction_index=0,
        bundle_only=True,
        tip_account_static=False,
        bundle_ack_treated_as_settlement=False,
    )

    assert result.ready is False
    assert "JITO_TIP_ACCOUNT_MUST_BE_STATIC_NO_ALT" in result.blockers


def test_pr130_live_canonical_jito_bundle_is_hard_blocked() -> None:
    with pytest.raises(SubmissionError) as raised:
        CanonicalSenderSettings(
            transport=TransportKind.JITO_BUNDLE,
            rpc_endpoint="https://api.mainnet-beta.solana.com",
            compile_time_enabled=True,
            config_enabled=True,
        )

    assert raised.value.code is SubmissionErrorCode.LIVE_GATE_CLOSED
    assert raised.value.disposition is ErrorDisposition.FATAL
    assert "PR-130" in str(raised.value)


def test_pr130_canonical_manifest_exposes_jito_policy() -> None:
    settings = CanonicalSenderSettings(
        transport=TransportKind.JITO_SINGLE,
        rpc_endpoint="https://api.mainnet-beta.solana.com",
        jito_bundle_only=True,
    )

    protection = settings.redacted_manifest()["jito_mev_protection"]

    assert isinstance(protection, dict)
    assert protection["schema_version"] == PR130_JITO_MEV_POLICY_SCHEMA_VERSION
    assert protection["state"] == "ready"
    assert protection["transaction_count"] == 1
    assert protection["tip_transaction_index"] == 0
    assert protection["bundle_ack_treated_as_settlement"] is False
