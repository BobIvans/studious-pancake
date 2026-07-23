from __future__ import annotations

from dataclasses import replace

import pytest

from src.mpr_close_05_isolated_signer_jito_canary import (
    MPRClose05State,
    NonceReplayCache,
    authorize_exact_message,
    evaluate_mpr_close_05_evidence,
    sample_ready_evidence,
)


MESSAGE = b"mpr-close-05-message"
MESSAGE_HASH = "93947fcc54b9793dad50ff5f15f020077373def81b44fe43421d6f23bcfc0f7b"


def _codes(report):
    return {blocker.code for blocker in report.blockers}


def test_ready_foundation_keeps_live_and_sender_disabled() -> None:
    report = evaluate_mpr_close_05_evidence(sample_ready_evidence())

    assert report.schema_version == "mpr-close-05.isolated-signer-jito-canary.v1"
    assert report.state is MPRClose05State.READY_FOR_BOUNDED_CANARY_REVIEW
    assert report.blockers == ()
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.unrestricted_live_available is False
    assert report.bounded_canary_default_off is True
    assert report.bounded_canary_review_ready is True


def test_runtime_private_key_access_is_forbidden() -> None:
    evidence = sample_ready_evidence()
    report = evaluate_mpr_close_05_evidence(
        replace(
            evidence,
            signer=replace(evidence.signer, runtime_private_key_access=True),
        )
    )

    assert report.state is MPRClose05State.BLOCKED
    assert "SIGNER_RUNTIME_KEY_ACCESS" in _codes(report)


def test_signer_authorizes_only_exact_message_and_consumes_nonce() -> None:
    evidence = sample_ready_evidence()
    signer = replace(evidence.signer, message_bytes_hash=MESSAGE_HASH)
    cache = NonceReplayCache()

    authorization_hash = authorize_exact_message(
        signer,
        message_bytes=MESSAGE,
        replay_cache=cache,
        now_ns=200,
    )

    assert len(authorization_hash) == 64
    with pytest.raises(ValueError, match="SIGNER_NONCE_REPLAY"):
        authorize_exact_message(signer, message_bytes=MESSAGE, replay_cache=cache, now_ns=200)


def test_signer_rejects_message_mutation_and_expiry() -> None:
    evidence = sample_ready_evidence()
    signer = replace(evidence.signer, message_bytes_hash=MESSAGE_HASH)

    with pytest.raises(ValueError, match="SIGNER_MESSAGE_BYTES_CHANGED"):
        authorize_exact_message(
            signer,
            message_bytes=b"changed",
            replay_cache=NonceReplayCache(),
            now_ns=200,
        )
    with pytest.raises(ValueError, match="SIGNER_AUTHORIZATION_EXPIRED"):
        authorize_exact_message(
            signer,
            message_bytes=MESSAGE,
            replay_cache=NonceReplayCache(),
            now_ns=1_000,
        )


def test_submission_outbox_ack_and_bundle_id_are_not_terminal() -> None:
    evidence = sample_ready_evidence()
    report = evaluate_mpr_close_05_evidence(
        replace(
            evidence,
            outbox=replace(
                evidence.outbox,
                ack_recorded_as_terminal=True,
                bundle_id_recorded_as_terminal=True,
                durable_before_transport=False,
            ),
        )
    )

    codes = _codes(report)
    assert report.state is MPRClose05State.BLOCKED
    assert "OUTBOX_ACK_TERMINAL" in codes
    assert "OUTBOX_BUNDLE_ID_TERMINAL" in codes
    assert "OUTBOX_NOT_DURABLE" in codes


def test_jito_requires_exact_simulation_polling_tip_policy_and_finalized_reconciliation() -> None:
    evidence = sample_ready_evidence()
    report = evaluate_mpr_close_05_evidence(
        replace(
            evidence,
            jito=replace(
                evidence.jito,
                simulation_before_send=False,
                bundle_status_polled=False,
                minimum_tip_policy_enforced=False,
                finalized_onchain_reconciliation=False,
            ),
        )
    )

    assert report.state is MPRClose05State.BLOCKED
    assert "JITO_SEMANTICS_INCOMPLETE" in _codes(report)


def test_canary_requires_upstream_evidence_latches_and_second_human_approval() -> None:
    evidence = sample_ready_evidence()
    latch_state = dict(evidence.canary.latch_state)
    latch_state["fresh_provider_drift_report"] = False
    report = evaluate_mpr_close_05_evidence(
        replace(
            evidence,
            canary=replace(
                evidence.canary,
                upstream_evidence={"MPR-CLOSE-01": "a" * 64},
                latch_state=latch_state,
                independent_approval_hashes=("b" * 64,),
            ),
        )
    )

    codes = _codes(report)
    assert report.state is MPRClose05State.BLOCKED
    assert "CANARY_UPSTREAM_EVIDENCE_MISSING" in codes
    assert "CANARY_LATCH_OPEN" in codes
    assert "CANARY_SECOND_APPROVAL_MISSING" in codes


def test_unrestricted_live_and_default_on_canary_are_forbidden() -> None:
    evidence = sample_ready_evidence()
    report = evaluate_mpr_close_05_evidence(
        replace(
            evidence,
            canary=replace(
                evidence.canary,
                unrestricted_live_available=True,
                live_canary_available_by_default=True,
            ),
        )
    )

    codes = _codes(report)
    assert report.state is MPRClose05State.BLOCKED
    assert "CANARY_UNRESTRICTED_LIVE_FORBIDDEN" in codes
    assert "CANARY_DEFAULT_ON_FORBIDDEN" in codes
    assert report.unrestricted_live_available is False
