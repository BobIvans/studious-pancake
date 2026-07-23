from __future__ import annotations

import math

import pytest

from src.live_boundary.mega_pr03_live_canary_convergence import (
    CANONICAL_OWNER_BY_ROLE,
    CHECKPOINT,
    REQUIRED_CANARY_BINDINGS,
    REQUIRED_COMPATIBILITY_ALIASES,
    REQUIRED_REVIEW_ONLY_SURFACES,
    REQUIRED_SUBMISSION_CRASH_DRILLS,
    SCHEMA_VERSION,
    evaluate_mega_pr03_checkpoint,
)

pytestmark = pytest.mark.unit

HASH = "a" * 64


def _good_evidence() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "checkpoint": CHECKPOINT,
        "mega_pr02": {
            "accepted": True,
            "paper_ready": True,
            "release_bound": True,
            "independently_reviewed": True,
            "live_physically_disabled": True,
            "non_synthetic_qualification": True,
            "source_sha256": HASH,
            "wheel_sha256": HASH,
            "image_sha256": HASH,
            "config_sha256": HASH,
            "policy_sha256": HASH,
            "qualification_sha256": HASH,
        },
        "authority": {
            "owners": dict(CANONICAL_OWNER_BY_ROLE),
            "review_only_surfaces": REQUIRED_REVIEW_ONLY_SURFACES,
            "compatibility_aliases": dict(REQUIRED_COMPATIBILITY_ALIASES),
            "runtime_private_key_loader_present": False,
            "runtime_sender_present": False,
            "one_owner_per_role_enforced": True,
        },
        "signer_boundary": {
            "separate_process": True,
            "separate_image": True,
            "narrow_authenticated_ipc": True,
            "client_identity_bound": True,
            "exact_message_hash_only": True,
            "semantic_bounds_enforced": True,
            "replay_nonce_persisted": True,
            "request_size_bounded": True,
            "request_deadline_bounded": True,
            "compile_time_live_disabled": True,
            "runtime_image_contains_key_loader": False,
            "signer_image_contains_strategy_logic": False,
            "signer_accepts_provider_inputs": False,
            "raw_env_private_key_allowed": False,
            "arbitrary_message_signing_allowed": False,
            "key_authority": "secret_manager",
            "signer_image_sha256": HASH,
            "ipc_policy_sha256": HASH,
        },
        "submission": {
            "durable_intent_before_network": True,
            "one_selected_transport": True,
            "ack_not_economic_success": True,
            "processed_confirmed_not_success": True,
            "no_blind_retry": True,
            "blockheight_rechecked_before_send": True,
            "rate_limits_enforced": True,
            "unbundling_leakage_policy": True,
            "receipt_durable_and_signed": True,
            "unknown_state_persisted": True,
            "crash_drills": REQUIRED_SUBMISSION_CRASH_DRILLS,
            "retry_policy": "status_search_then_operator_review",
        },
        "settlement": {
            "get_transaction_materialized": True,
            "v0_supported": True,
            "intent_message_hash_bound": True,
            "payer_lamport_delta_bound": True,
            "token_deltas_bound": True,
            "inner_instructions_bound": True,
            "fee_tip_rent_accounted": True,
            "borrow_repayment_verified": True,
            "unknown_holds_capital": True,
            "fork_reorg_rpc_disagreement_blocks": True,
            "external_wallet_activity_blocks": True,
            "realized_pnl_only": True,
            "bounded_recovery": True,
            "restart_idempotent": True,
            "commitment": "finalized",
            "terminal_states": (
                "finalized_success",
                "finalized_failure",
                "expired",
                "unknown_locked",
            ),
        },
        "canary": {
            "permit_signed": True,
            "permit_one_time": True,
            "permit_expiring": True,
            "latch_persistent_across_restart": True,
            "unknown_closes_latch": True,
            "provider_drift_closes_latch": True,
            "reconciliation_lag_closes_latch": True,
            "post_run_evidence_signed": True,
            "manual_go_no_go_required": True,
            "permit_bindings": REQUIRED_CANARY_BINDINGS,
            "reviewer_ids": ("risk-reviewer", "security-reviewer"),
            "proposer_id": "operator-proposer",
            "max_capital_lamports": 1_000_000,
            "wallet_capital_lamports": 2_000_000,
            "max_daily_loss_lamports": 100_000,
            "max_fee_tip_lamports": 50_000,
            "max_transactions": 1,
            "max_in_flight": 1,
            "max_slippage_bps": 50,
            "automatic_scale_up": False,
            "unrestricted_live": False,
        },
        "capabilities": {
            "live_execution_enabled": False,
            "unrestricted_live_enabled": False,
            "automatic_scale_up_enabled": False,
            "runtime_private_key_access": False,
            "runtime_sender_access": False,
        },
    }


def test_happy_path_allows_only_bounded_canary_review() -> None:
    report = evaluate_mega_pr03_checkpoint(_good_evidence())

    assert report.accepted is True
    assert report.blockers == ()
    assert report.bounded_canary_review_allowed is True
    assert report.live_execution_allowed is False
    assert report.unrestricted_live_allowed is False
    assert report.automatic_scale_up_allowed is False


def test_report_hash_is_deterministic() -> None:
    first = evaluate_mega_pr03_checkpoint(_good_evidence())
    second = evaluate_mega_pr03_checkpoint(_good_evidence())

    assert first.evidence_hash == second.evidence_hash
    assert first.canonical_owner_hash == second.canonical_owner_hash


def test_requires_accepted_release_bound_mega_pr02() -> None:
    evidence = _good_evidence()
    evidence["mega_pr02"]["accepted"] = False
    evidence["mega_pr02"]["qualification_sha256"] = "invalid"

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "MEGA_PR02_NOT_ACCEPTED" in report.blockers
    assert "MEGA_PR02_QUALIFICATION_SHA256_INVALID" in report.blockers


def test_rejects_canonical_owner_drift_and_runtime_sender() -> None:
    evidence = _good_evidence()
    evidence["authority"]["owners"]["signer_boundary"] = "src.legacy.signer"
    evidence["authority"]["runtime_sender_present"] = True

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "LIVE_BOUNDARY_OWNER_INVALID:signer_boundary" in report.blockers
    assert "RUNTIME_SENDER_PRESENT" in report.blockers


def test_requires_review_gate_quarantine_and_alias_target() -> None:
    evidence = _good_evidence()
    evidence["authority"]["review_only_surfaces"] = ()
    evidence["authority"]["compatibility_aliases"] = {
        "src.submission.pr202_isolated_signer_settlement": "src.legacy.impl"
    }

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "LIVE_BOUNDARY_REVIEW_SURFACE_NOT_QUARANTINED" in report.blockers
    assert (
        "LIVE_BOUNDARY_ALIAS_INVALID:"
        "src.submission.pr202_isolated_signer_settlement"
    ) in report.blockers


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("runtime_image_contains_key_loader", "RUNTIME_IMAGE_CONTAINS_KEY_LOADER"),
        ("signer_image_contains_strategy_logic", "SIGNER_IMAGE_CONTAINS_STRATEGY"),
        ("signer_accepts_provider_inputs", "SIGNER_ACCEPTS_PROVIDER_INPUTS"),
        ("raw_env_private_key_allowed", "SIGNER_RAW_ENV_KEY_ALLOWED"),
        ("arbitrary_message_signing_allowed", "SIGNER_ARBITRARY_SIGNING_ALLOWED"),
    ),
)
def test_signer_boundary_rejects_forbidden_surface(field: str, reason: str) -> None:
    evidence = _good_evidence()
    evidence["signer_boundary"][field] = True

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert reason in report.blockers


def test_submission_ack_and_processed_cannot_be_success() -> None:
    evidence = _good_evidence()
    evidence["submission"]["ack_not_economic_success"] = False
    evidence["submission"]["processed_confirmed_not_success"] = False

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "SUBMISSION_ACK_COUNTS_AS_SUCCESS" in report.blockers
    assert "NON_FINAL_STATUS_COUNTS_AS_SUCCESS" in report.blockers


def test_submission_requires_complete_crash_matrix() -> None:
    evidence = _good_evidence()
    evidence["submission"]["crash_drills"] = ("crash_before_send",)

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "SUBMISSION_CRASH_MATRIX_INCOMPLETE" in report.blockers


def test_settlement_requires_finalized_truth_and_unknown_capital_lock() -> None:
    evidence = _good_evidence()
    evidence["settlement"]["commitment"] = "confirmed"
    evidence["settlement"]["unknown_holds_capital"] = False
    evidence["settlement"]["realized_pnl_only"] = False

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "FINALITY_COMMITMENT_NOT_FINALIZED" in report.blockers
    assert "UNKNOWN_OUTCOME_RELEASES_CAPITAL" in report.blockers
    assert "CANARY_METRICS_NOT_REALIZED_PNL" in report.blockers


def test_canary_requires_independent_two_person_approval() -> None:
    evidence = _good_evidence()
    evidence["canary"]["reviewer_ids"] = ("operator-proposer",)
    evidence["canary"]["proposer_id"] = "operator-proposer"

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "CANARY_TWO_PERSON_APPROVAL_MISSING" in report.blockers
    assert "CANARY_SELF_APPROVAL_FORBIDDEN" in report.blockers


def test_canary_permit_must_bind_exact_release_surface() -> None:
    evidence = _good_evidence()
    evidence["canary"]["permit_bindings"] = ("release", "config")

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "CANARY_PERMIT_BINDING_INCOMPLETE" in report.blockers


def test_canary_budget_is_bounded_and_single_in_flight() -> None:
    evidence = _good_evidence()
    evidence["canary"]["max_capital_lamports"] = 3_000_000
    evidence["canary"]["wallet_capital_lamports"] = 2_000_000
    evidence["canary"]["max_transactions"] = 11
    evidence["canary"]["max_in_flight"] = 2
    evidence["canary"]["max_slippage_bps"] = 101

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "CANARY_CAPITAL_EXCEEDS_WALLET" in report.blockers
    assert "CANARY_TRANSACTION_COUNT_UNBOUNDED" in report.blockers
    assert "CANARY_IN_FLIGHT_MUST_BE_ONE" in report.blockers
    assert "CANARY_SLIPPAGE_BOUND_UNSAFE" in report.blockers


def test_canary_cannot_enable_unrestricted_or_automatic_live() -> None:
    evidence = _good_evidence()
    evidence["canary"]["automatic_scale_up"] = True
    evidence["canary"]["unrestricted_live"] = True

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "CANARY_AUTOMATIC_SCALE_UP_FORBIDDEN" in report.blockers
    assert "CANARY_UNRESTRICTED_LIVE_FORBIDDEN" in report.blockers


def test_global_live_and_key_capabilities_remain_disabled() -> None:
    evidence = _good_evidence()
    evidence["capabilities"]["live_execution_enabled"] = True
    evidence["capabilities"]["runtime_private_key_access"] = True
    evidence["capabilities"]["runtime_sender_access"] = True

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "LIVE_EXECUTION_MUST_REMAIN_DISABLED" in report.blockers
    assert "RUNTIME_PRIVATE_KEY_ACCESS_FORBIDDEN" in report.blockers
    assert "RUNTIME_SENDER_ACCESS_FORBIDDEN" in report.blockers
    assert report.bounded_canary_review_allowed is False


def test_non_finite_or_boolean_budget_values_fail_closed() -> None:
    evidence = _good_evidence()
    evidence["canary"]["max_capital_lamports"] = math.inf
    evidence["canary"]["max_transactions"] = True

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "CANARY_CAPITAL_BOUND_INVALID" in report.blockers
    assert "CANARY_TRANSACTION_COUNT_UNBOUNDED" in report.blockers


def test_unknown_owner_role_fails_closed() -> None:
    evidence = _good_evidence()
    evidence["authority"]["owners"]["legacy_sender"] = "src.legacy.sender"

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "LIVE_BOUNDARY_UNKNOWN_OWNER_ROLE" in report.blockers


def test_missing_evidence_sections_fail_closed() -> None:
    evidence = _good_evidence()
    evidence.pop("submission")
    evidence.pop("settlement")

    report = evaluate_mega_pr03_checkpoint(evidence)

    assert "SUBMISSION_EVIDENCE_MISSING" in report.blockers
    assert "SETTLEMENT_EVIDENCE_MISSING" in report.blockers
