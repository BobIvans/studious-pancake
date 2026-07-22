from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.pr151_isolated_release_path import (
    PR150_SOAK_EVIDENCE_NAME,
    PR151ReleasePathError,
    PR151ReleasePathPackage,
    PR151ReleasePathState,
    DurableAuthorizationPolicy,
    FinalizedSettlementPolicy,
    HermeticReleaseAndSandboxPolicy,
    IsolatedSignerBoundary,
    JitoCanarySafetyPolicy,
    PR151EvidenceRef,
    evaluate_pr151_release_path,
)

pytestmark = pytest.mark.unit

SHA256_A = "a" * 64
SHA256_B = "b" * 64
SHA256_C = "c" * 64
SHA256_D = "d" * 64
GIT_SHA = "1" * 40
ASSEMBLED_AT = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def _package(**overrides: object) -> PR151ReleasePathPackage:
    values: dict[str, object] = {
        "code_commit": GIT_SHA,
        "pr150_soak_evidence": PR151EvidenceRef(
            name=PR150_SOAK_EVIDENCE_NAME,
            sha256=SHA256_A,
            source_commit=GIT_SHA,
            passed=True,
            human_reviewed=True,
            reviewer="release-reviewer",
        ),
        "isolated_signer": IsolatedSignerBoundary(
            backend_kind="keychain",
            network_runtime_imports_keypair=False,
            signer_has_general_network_access=False,
            parses_message_independently=True,
            derives_payer_signers_programs_accounts=True,
            verifies_policy_and_proof_hashes=True,
            verifies_full_wire_transaction_limit=True,
            returns_signature_only=True,
        ),
        "authorization": DurableAuthorizationPolicy(
            policy_bundle_sha256=SHA256_A,
            transaction_proof_sha256=SHA256_B,
            signer_readiness_sha256=SHA256_C,
            nonce="nonce-1",
            expires_at=ASSEMBLED_AT + timedelta(minutes=5),
            durable_store_bound=True,
            anti_replay_is_durable=True,
            caller_constructable_plain_permit=False,
        ),
        "settlement": FinalizedSettlementPolicy(
            get_transaction_finalized_required=True,
            max_supported_transaction_version_zero=True,
            meta_err_must_be_none=True,
            actual_fee_required=True,
            balance_delta_reconciliation_required=True,
            inner_instruction_cpi_required=True,
            simulated_vs_actual_comparison_required=True,
            indeterminate_outcome_freezes_submissions=True,
        ),
        "jito": JitoCanarySafetyPolicy(
            one_atomic_transaction=True,
            exactly_one_tip=True,
            tip_in_same_transaction=True,
            tip_account_evidence_sha256=SHA256_D,
            bundle_only_reviewed=True,
            standalone_tip_forbidden=True,
            uncle_unbundling_drill_reviewed=True,
        ),
        "release_and_sandbox": HermeticReleaseAndSandboxPolicy(
            github_actions_pinned_to_full_sha=True,
            docker_image_pinned_by_digest=True,
            hashed_wheelhouse=True,
            sbom_present=True,
            signed_artifact_provenance=True,
            read_only_root_filesystem=True,
            capabilities_dropped=True,
            no_new_privileges=True,
            seccomp_or_apparmor=True,
            egress_allowlist_enforced=True,
            signer_network_separation=True,
        ),
        "operator_approvals": {
            "release-owner-signoff": ASSEMBLED_AT - timedelta(minutes=4),
            "security-owner-signoff": ASSEMBLED_AT - timedelta(minutes=3),
            "risk-owner-signoff": ASSEMBLED_AT - timedelta(minutes=2),
            "operator-final-arm-signoff": ASSEMBLED_AT - timedelta(minutes=1),
        },
        "default_live_enabled": False,
        "env_can_enable_live": False,
        "runtime_command_can_submit": False,
        "max_outstanding_submissions": 1,
        "outstanding_submissions": 0,
        "ambiguity_latch_armed": True,
        "rollback_to_shadow_available": True,
        "manual_kill_switch_armed": True,
        "assembled_at": ASSEMBLED_AT,
        "assembled_by": "release-owner",
    }
    values.update(overrides)
    return PR151ReleasePathPackage(**values)


def test_ready_package_remains_manual_review_only_and_live_disabled() -> None:
    readiness = evaluate_pr151_release_path(_package())

    assert readiness.state == PR151ReleasePathState.READY_FOR_MANUAL_RELEASE_REVIEW
    assert readiness.ready_for_manual_release_review is True
    assert readiness.default_live_enabled is False
    assert readiness.runtime_live_enabled is False
    assert readiness.supported_command_can_submit is False
    assert readiness.blockers == ()
    assert "REVIEW_ONLY_GATE_DOES_NOT_ENABLE_LIVE" in readiness.warnings


def test_default_live_enabled_is_blocked() -> None:
    readiness = evaluate_pr151_release_path(_package(default_live_enabled=True))

    assert readiness.state == PR151ReleasePathState.BLOCKED
    assert "DEFAULT_LIVE_ENABLED" in readiness.blockers
    assert readiness.runtime_live_enabled is False


def test_network_runtime_keypair_import_blocks_release_path() -> None:
    package = _package(
        isolated_signer=replace(
            _package().isolated_signer,
            network_runtime_imports_keypair=True,
        )
    )

    readiness = evaluate_pr151_release_path(package)

    assert "NETWORK_RUNTIME_IMPORTS_KEYPAIR" in readiness.blockers
    assert readiness.supported_command_can_submit is False


def test_finalized_settlement_evidence_is_mandatory() -> None:
    package = _package(
        settlement=replace(
            _package().settlement,
            indeterminate_outcome_freezes_submissions=False,
        )
    )

    readiness = evaluate_pr151_release_path(package)

    assert "INDETERMINATE_DOES_NOT_FREEZE" in readiness.blockers


def test_jito_standalone_tip_must_be_forbidden() -> None:
    package = _package(
        jito=replace(
            _package().jito,
            standalone_tip_forbidden=False,
        )
    )

    readiness = evaluate_pr151_release_path(package)

    assert "JITO_STANDALONE_TIP_ALLOWED" in readiness.blockers


def test_missing_operator_approval_blocks() -> None:
    approvals = dict(_package().operator_approvals)
    approvals.pop("risk-owner-signoff")

    readiness = evaluate_pr151_release_path(_package(operator_approvals=approvals))

    assert "SIGNOFF_MISSING:risk-owner-signoff" in readiness.blockers


def test_placeholder_hashes_are_rejected() -> None:
    with pytest.raises(PR151ReleasePathError, match="non-placeholder sha256"):
        PR151EvidenceRef(
            name=PR150_SOAK_EVIDENCE_NAME,
            sha256="0" * 64,
            source_commit=GIT_SHA,
            passed=True,
            human_reviewed=True,
            reviewer="reviewer",
        )
