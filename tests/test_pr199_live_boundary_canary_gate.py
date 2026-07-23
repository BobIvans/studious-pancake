from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from src.pr199_live_boundary_canary_gate import (
    CanaryBudgetEvidence,
    DigestBindingEvidence,
    EvidenceRef,
    FeeAndLatchEvidence,
    IntentConsumptionEvidence,
    PR199BoundaryError,
    PR199LiveBoundaryEvidence,
    REQUIRED_CANARY_BUDGETS,
    REQUIRED_CRASH_DRILLS,
    REQUIRED_STATUS_STATES,
    SignerIsolationEvidence,
    SubmissionRecoveryEvidence,
    evaluate_pr199_live_boundary,
    pr199_live_boundary_status_payload,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def ref(label: str) -> EvidenceRef:
    return EvidenceRef(
        label=label,
        sha256=digest(f"{label}-artifact"),
        relative_path=f"artifacts/pr199/{label}.json",
    )


def good_signer() -> SignerIsolationEvidence:
    return SignerIsolationEvidence(
        separate_signer_process=True,
        runtime_has_private_key_bytes=False,
        signer_backend_importable_from_runtime=False,
        signer_has_general_internet_egress=False,
        signer_accepts_only_policy_permit=True,
        signer_rejects_unsigned_or_unbound_payload=True,
        signer_policy_hash=digest("signer-policy"),
        signer_release_hash=digest("signer-release"),
    )


def good_digest_binding() -> DigestBindingEvidence:
    return DigestBindingEvidence(
        attempt_generation_message_bound=True,
        config_wallet_provider_market_bound=True,
        reservation_nonce_expiry_bound=True,
        local_signature_verification_passed=True,
        signed_payload_hash_matches_message=True,
        replay_field_mutation_rejections=8,
        signer_request_digest=digest("signer-request"),
        signed_payload_digest=digest("signed-payload"),
    )


def good_intent() -> IntentConsumptionEvidence:
    return IntentConsumptionEvidence(
        atomic_permit_reservation_intent_consume=True,
        durable_before_first_network_byte=True,
        receipt_unique_per_message_hash=True,
        transport_receipt_ownership_conflicts=0,
        outstanding_intents=1,
        duplicate_send_recovery_proven=True,
    )


def good_recovery() -> SubmissionRecoveryEvidence:
    return SubmissionRecoveryEvidence(
        immediate_blockheight_recheck_count=1,
        no_blind_retry_policy=True,
        one_atomic_flash_transaction=True,
        required_status_states=REQUIRED_STATUS_STATES,
        crash_drills_passed=REQUIRED_CRASH_DRILLS,
        history_search_used=True,
        finalized_transaction_fetch_used=True,
        jito_ack_treated_as_success=False,
        unknown_outcome_escalation_proven=True,
    )


def good_fee_latch() -> FeeAndLatchEvidence:
    return FeeAndLatchEvidence(
        landed_failed_fee_accounted_from_finalized_meta=True,
        charged_fee_lamports=6_000,
        projected_fee_lamports=5_000,
        settled_native_delta_bound=True,
        failed_landing_profit_forced_zero=True,
        loss_latch_armed_on_fee_or_capital_violation=True,
        emergency_latch_clear_for_canary=True,
    )


def good_canary() -> CanaryBudgetEvidence:
    return CanaryBudgetEvidence(
        budget_controls_present=REQUIRED_CANARY_BUDGETS,
        wallet_allowlist_hash=digest("wallet-allowlist"),
        max_per_attempt_loss_lamports=10_000,
        max_daily_loss_lamports=25_000,
        runtime_budget_override_possible=False,
        operator_approval_hash=digest("operator-approval"),
        emergency_latch_hash=digest("emergency-latch"),
    )


def good_evidence(**overrides: object) -> PR199LiveBoundaryEvidence:
    data: dict[str, object] = {
        "release_id": "release-pr199-live-boundary",
        "pr198_evidence_hash": digest("accepted-pr198-evidence"),
        "pr198_sender_free_evidence_accepted": True,
        "signer": good_signer(),
        "digest_binding": good_digest_binding(),
        "intent": good_intent(),
        "recovery": good_recovery(),
        "fee_latch": good_fee_latch(),
        "canary": good_canary(),
        "signed_evidence_package": ref("signed-evidence"),
        "signer_policy_artifact": ref("signer-policy"),
        "reconciliation_artifact": ref("reconciliation"),
    }
    data.update(overrides)
    return PR199LiveBoundaryEvidence(**data)


def test_pr199_live_boundary_happy_path_is_still_default_off() -> None:
    report = evaluate_pr199_live_boundary(good_evidence())

    assert report.passed is True
    assert report.blockers == ()
    assert report.live_capability_allowed is False
    assert report.signer_backend_allowed is False
    assert report.sender_transport_allowed is False
    assert report.report_hash == report.report_hash
    assert all(report.requirement_results.values())


def test_pr199_requires_accepted_pr198_sender_free_evidence() -> None:
    report = evaluate_pr199_live_boundary(
        good_evidence(pr198_sender_free_evidence_accepted=False)
    )

    assert report.passed is False
    assert report.requirement_results["accepted_pr198_evidence"] is False


def test_pr199_rejects_runtime_private_key_or_signer_backend_import() -> None:
    unsafe_signer = replace(
        good_signer(),
        runtime_has_private_key_bytes=True,
        signer_backend_importable_from_runtime=True,
    )
    report = evaluate_pr199_live_boundary(
        good_evidence(signer=unsafe_signer, signer_backend_enabled=True)
    )

    assert report.passed is False
    assert report.requirement_results["isolated_signer_policy"] is False


def test_pr199_rejects_digest_mixup_or_unverified_signed_payload() -> None:
    bad_binding = replace(
        good_digest_binding(),
        config_wallet_provider_market_bound=False,
        signed_payload_hash_matches_message=False,
    )
    report = evaluate_pr199_live_boundary(good_evidence(digest_binding=bad_binding))

    assert report.passed is False
    assert report.requirement_results["digest_and_payload_binding"] is False


def test_pr199_rejects_non_atomic_intent_or_receipt_conflict() -> None:
    bad_intent = replace(
        good_intent(),
        atomic_permit_reservation_intent_consume=False,
        transport_receipt_ownership_conflicts=1,
        outstanding_intents=2,
    )
    report = evaluate_pr199_live_boundary(good_evidence(intent=bad_intent))

    assert report.passed is False
    assert report.requirement_results["atomic_intent_consumption"] is False
    assert report.requirement_results["limited_canary_budgets"] is False


def test_pr199_requires_history_search_finalized_tx_and_no_ack_success() -> None:
    bad_recovery = replace(
        good_recovery(),
        history_search_used=False,
        finalized_transaction_fetch_used=False,
        jito_ack_treated_as_success=True,
    )
    report = evaluate_pr199_live_boundary(good_evidence(recovery=bad_recovery))

    assert report.passed is False
    assert report.requirement_results["finalized_reconciliation"] is False


def test_pr199_requires_crash_drills_and_blockheight_recheck() -> None:
    bad_recovery = replace(
        good_recovery(),
        immediate_blockheight_recheck_count=0,
        crash_drills_passed=("crash_before_send",),
    )
    report = evaluate_pr199_live_boundary(good_evidence(recovery=bad_recovery))

    assert report.passed is False
    assert report.requirement_results["blockheight_recheck_and_no_blind_retry"] is False
    assert report.requirement_results["finalized_reconciliation"] is False


def test_pr199_accounts_landed_failed_fee_and_latch() -> None:
    bad_fee = replace(
        good_fee_latch(),
        charged_fee_lamports=3_000,
        projected_fee_lamports=5_000,
        loss_latch_armed_on_fee_or_capital_violation=False,
    )
    report = evaluate_pr199_live_boundary(good_evidence(fee_latch=bad_fee))

    assert report.passed is False
    assert report.requirement_results["fee_accounting_and_latches"] is False


def test_pr199_rejects_runtime_canary_budget_override() -> None:
    bad_canary = replace(
        good_canary(),
        runtime_budget_override_possible=True,
        max_per_attempt_loss_lamports=30_000,
        max_daily_loss_lamports=25_000,
    )
    report = evaluate_pr199_live_boundary(good_evidence(canary=bad_canary))

    assert report.passed is False
    assert report.requirement_results["limited_canary_budgets"] is False


def test_pr199_artifact_paths_are_normalized_relative_paths() -> None:
    with pytest.raises(PR199BoundaryError):
        EvidenceRef(label="signed", sha256=digest("signed"), relative_path="/tmp/x.json")


def test_pr199_status_payload_is_fail_closed() -> None:
    payload = pr199_live_boundary_status_payload()

    assert payload["roadmap_pr"] == "PR-199"
    assert payload["seven_pr_scope"] == "isolated_signer_exactly_once_submission_finality_canary"
    assert payload["live_capability_allowed"] is False
    assert payload["signer_backend_allowed"] is False
    assert payload["sender_transport_allowed"] is False
    assert set(REQUIRED_STATUS_STATES).issubset(payload["required_status_states"])
    assert set(REQUIRED_CRASH_DRILLS).issubset(payload["required_crash_drills"])
    assert set(REQUIRED_CANARY_BUDGETS).issubset(payload["required_canary_budgets"])
