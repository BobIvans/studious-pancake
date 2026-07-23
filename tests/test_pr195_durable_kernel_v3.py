from __future__ import annotations

from dataclasses import replace
import json

import pytest

from src.pr195_durable_kernel_v3 import (
    PR195DurableKernelClaim,
    PR195DurableKernelError,
    REQUIREMENTS,
    SCHEMA_VERSION,
    complete_offline_claim,
    evaluate_pr195_durable_kernel,
    render_report_json,
)


def test_pr195_default_claim_is_fail_closed() -> None:
    report = evaluate_pr195_durable_kernel(PR195DurableKernelClaim())

    assert report.schema_version == SCHEMA_VERSION
    assert not report.ready
    assert not report.live_enabled
    assert not report.sender_or_signer_enabled
    assert len(report.requirement_results) == len(REQUIREMENTS)
    assert all(not item.satisfied for item in report.requirement_results)
    assert "DURABLE_BEFORE_ACK_WEBHOOK_INTAKE:MISSING_PROOF" in report.reason_codes
    assert "ATOMIC_WALLET_CAPITAL_AUTHORITY:MISSING_PROOF" in report.reason_codes


def test_pr195_complete_claim_is_non_authoritative_and_deterministic() -> None:
    claim = complete_offline_claim(
        evidence_refs=("tests/pr195/kernel/webhook-capital-replay.json",)
    )

    first = evaluate_pr195_durable_kernel(claim)
    second = evaluate_pr195_durable_kernel(claim)

    assert not first.ready
    assert first.reason_codes == ("PR206_AUTHORITATIVE_STORE_EVIDENCE_REQUIRED",)
    assert first.claim_hash == second.claim_hash
    assert {item.requirement_id for item in first.requirement_results} == {
        item.requirement_id for item in REQUIREMENTS
    }


def test_pr195_live_or_sender_enablement_is_rejected_even_with_complete_claim() -> None:
    claim = complete_offline_claim(evidence_refs=("evidence/pr195/offline.json",))

    report = evaluate_pr195_durable_kernel(
        claim,
        live_enabled=True,
        sender_or_signer_enabled=True,
    )

    assert not report.ready
    assert "LIVE_ENABLEMENT_NOT_ALLOWED_IN_PR195" in report.reason_codes
    assert "SENDER_OR_SIGNER_NOT_ALLOWED_IN_PR195" in report.reason_codes


def test_pr195_webhook_ack_requires_all_intake_proofs() -> None:
    almost = complete_offline_claim(evidence_refs=("evidence/pr195/intake.json",))
    claim = replace(almost, webhook_ack_after_durable_commit=False)

    report = evaluate_pr195_durable_kernel(claim)
    intake = next(
        item
        for item in report.requirement_results
        if item.requirement_id == "DURABLE_BEFORE_ACK_WEBHOOK_INTAKE"
    )

    assert not report.ready
    assert intake.finding_ids == (
        "F-140",
        "F-141",
        "F-142",
        "F-143",
        "F-145",
        "F-146",
        "F-147",
    )
    assert intake.missing_claim_fields == ("webhook_ack_after_durable_commit",)


def test_pr195_chain_identity_must_not_include_payload_hash() -> None:
    almost = complete_offline_claim(evidence_refs=("evidence/pr195/webhook.json",))
    claim = replace(almost, chain_identity_excludes_payload_hash=False)

    report = evaluate_pr195_durable_kernel(claim)
    identity = next(
        item
        for item in report.requirement_results
        if item.requirement_id == "IMMUTABLE_CHAIN_EVENT_IDENTITY"
    )

    assert not report.ready
    assert identity.finding_ids == ("F-148",)
    assert identity.missing_claim_fields == ("chain_identity_excludes_payload_hash",)


def test_pr195_capital_authority_requires_serializable_wallet_fencing() -> None:
    almost = complete_offline_claim(evidence_refs=("evidence/pr195/capital.json",))
    claim = replace(
        almost,
        capital_reservation_serializable=False,
        negative_headroom_latches=False,
    )

    report = evaluate_pr195_durable_kernel(claim)
    capital = next(
        item
        for item in report.requirement_results
        if item.requirement_id == "ATOMIC_WALLET_CAPITAL_AUTHORITY"
    )

    assert not report.ready
    assert capital.finding_ids == ("F-149", "F-150", "F-151", "F-152")
    assert capital.missing_claim_fields == (
        "capital_reservation_serializable",
        "negative_headroom_latches",
    )


def test_pr195_mapping_input_is_strict() -> None:
    with pytest.raises(PR195DurableKernelError, match="unknown"):
        PR195DurableKernelClaim.from_mapping({"surprise": True})

    with pytest.raises(PR195DurableKernelError, match="must be boolean"):
        PR195DurableKernelClaim.from_mapping({"one_database_authority": "true"})

    with pytest.raises(PR195DurableKernelError, match="string list"):
        PR195DurableKernelClaim.from_mapping({"evidence_refs": "one-file"})


def test_pr195_render_report_json_is_stable_json() -> None:
    rendered = render_report_json(
        {
            "one_database_authority": True,
            "webhook_ack_after_durable_commit": True,
            "webhook_schema_validated_before_ack": True,
            "webhook_shutdown_drains_or_requeues": True,
            "chain_identity_excludes_payload_hash": True,
            "capital_reservation_serializable": True,
            "wallet_revision_fencing": True,
            "negative_headroom_latches": True,
            "lifecycle_writes_serialized": True,
            "submission_intent_checks_rowcount": True,
            "monotonic_lease_renewal": True,
            "outbox_has_retry_ceiling_and_dlq": True,
            "restore_uses_validate_then_atomic_rename": True,
            "integrity_replays_event_projection": True,
            "submission_receipts_unique_per_attempt": True,
            "restore_requires_authenticated_manifest": True,
            "evidence_refs": ["evidence/pr195/v3.json"],
        }
    )
    payload = json.loads(rendered)

    assert payload["ready"] is False
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["reason_codes"] == ["PR206_AUTHORITATIVE_STORE_EVIDENCE_REQUIRED"]
    assert len(payload["claim_hash"]) == 64
