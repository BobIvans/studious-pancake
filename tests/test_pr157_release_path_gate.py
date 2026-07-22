from __future__ import annotations

from dataclasses import replace

import pytest

from src.release_path_pr157 import (
    CanaryMode,
    FinalizedSettlementEvidence,
    HermeticReleaseEvidence,
    JitoSafetyEvidence,
    ProductionSandboxEvidence,
    ReleaseDecision,
    ReleaseFailureReason,
    ReleasePathEvidence,
    ReviewedCanaryEvidence,
    SignerBackendKind,
    SignerBoundaryEvidence,
    SubmissionLifecycleEvidence,
    SubmissionState,
    AuthorizationEvidence,
    evaluate_release_gate,
    scan_forbidden_live_surface,
)


NOW = 2_000_000


def _hash(label: str) -> str:
    return (label.encode("utf-8").hex() * 8)[:64]


def _bindings() -> dict[str, str]:
    return {
        "attempt_generation": "42",
        "exact_message_hash": _hash("message"),
        "policy_bundle_hash": _hash("policy"),
        "program_attestation_hash": _hash("program"),
        "asset_mint_attestation_hash": _hash("asset"),
        "marginfi_evidence_hash": _hash("marginfi"),
        "jupiter_evidence_hash": _hash("jupiter"),
        "simulation_cpi_proof_hash": _hash("simulation"),
        "fee_blockhash_alt_fork_hash": _hash("fork"),
        "signer_pubkey": "signer-pubkey",
        "expiry": str(NOW + 1_000),
        "nonce": _hash("nonce"),
    }


def _good_evidence() -> ReleasePathEvidence:
    return ReleasePathEvidence(
        signer=SignerBoundaryEvidence(
            network_runtime_imports_keypair=False,
            network_runtime_has_private_key_bytes=False,
            signer_backend=SignerBackendKind.KMS,
            signer_parses_exact_v0_message=True,
            signer_derives_payer_signers_programs_accounts=True,
            signer_verifies_policy_and_proof_hashes=True,
            signer_checks_full_wire_limit=True,
            signer_returns_signature_only=True,
            signer_has_general_network_access=False,
            signer_identity_hash=_hash("signer"),
            backend_public_key_hash=_hash("pubkey"),
        ),
        authorization=AuthorizationEvidence(
            durable=True,
            authenticated=True,
            caller_constructable_plain_dataclass=False,
            one_time_nonce_persisted=True,
            expiry_unix_ms=NOW + 1_000,
            bindings=_bindings(),
            authorization_hash=_hash("authorization"),
        ),
        submission=SubmissionLifecycleEvidence(
            current_state=SubmissionState.FINALIZED,
            durable_signing_intent=True,
            signed_payload_verified=True,
            durable_submission_intent=True,
            auto_resend_on_ambiguity=False,
            ambiguity_latch_enabled=True,
            indeterminate_outcome=False,
        ),
        jito=JitoSafetyEvidence(
            enabled=True,
            one_atomic_transaction=True,
            tip_inside_same_transaction=True,
            exactly_one_tip=True,
            current_tip_account_evidence_hash=_hash("tip-account"),
            bundle_only_reviewed=True,
            standalone_tip_forbidden=True,
            uncle_unbundling_drill_hash=_hash("uncle-drill"),
        ),
        settlement=FinalizedSettlementEvidence(
            finalized=True,
            get_transaction_max_supported_v0=True,
            exact_transaction_identity_hash=_hash("txid"),
            meta_err_is_none=True,
            actual_fee_lamports=5_000,
            native_token_balance_evidence_hash=_hash("balances"),
            loaded_addresses_hash=_hash("loaded"),
            inner_instructions_cpi_hash=_hash("cpi"),
            compute_units_hash=_hash("compute"),
            marginfi_repayment_hash=_hash("repayment"),
            rent_tip_transfer_fee_hash=_hash("fees"),
            simulated_vs_actual_reconciliation_hash=_hash("reconcile"),
            conservative_net_lamports=1,
        ),
        release=HermeticReleaseEvidence(
            github_actions_pinned_to_full_sha=True,
            docker_image_pinned_by_digest=True,
            hashed_wheelhouse=True,
            offline_reproducible_build=True,
            sbom_hash=_hash("sbom"),
            vulnerability_scan_hash=_hash("vuln"),
            license_inventory_hash=_hash("license"),
            secret_scan_hash=_hash("secret-scan"),
            signed_artifact_provenance_hash=_hash("provenance"),
        ),
        sandbox=ProductionSandboxEvidence(
            read_only_root_fs=True,
            capability_drop=True,
            no_new_privileges=True,
            seccomp_or_apparmor=True,
            cpu_memory_pid_fd_limits=True,
            egress_allowlist=True,
            signer_network_separation=True,
        ),
        canary=ReviewedCanaryEvidence(
            mode=CanaryMode.REVIEWED_TINY_CANARY,
            default_package_live_disabled=True,
            default_config_live_disabled=True,
            single_env_live_enable_forbidden=True,
            actual_soak_seconds=72 * 60 * 60,
            tiny_allowlisted_exposure_lamports=10_000,
            max_tiny_exposure_lamports=10_000,
            protected_sol_reserve_lamports=1_000_000,
            one_outstanding_submission=True,
            loss_stale_ambiguity_latches=True,
            manual_kill_switch=True,
            dual_human_approval_hash=_hash("approval"),
            rollback_to_shadow_hash=_hash("rollback"),
        ),
    )


def _reasons(report) -> set[ReleaseFailureReason]:
    return {failure.reason for failure in report.failures}


def test_pr157_good_evidence_approves_reviewed_tiny_canary() -> None:
    report = evaluate_release_gate(_good_evidence(), now_unix_ms=NOW)

    assert report.decision is ReleaseDecision.APPROVED
    assert report.live_allowed is True
    assert report.failures == ()
    assert len(report.evidence_hash) == 64


def test_pr157_default_live_enabled_blocks_release() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        canary=replace(good.canary, default_config_live_disabled=False),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    assert report.live_allowed is False
    assert ReleaseFailureReason.LIVE_DEFAULT_ENABLED in _reasons(report)


def test_pr157_single_env_live_toggle_blocks_release() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        canary=replace(good.canary, single_env_live_enable_forbidden=False),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    assert ReleaseFailureReason.SINGLE_ENV_ENABLES_LIVE in _reasons(report)


def test_pr157_keypair_in_network_runtime_blocks_release() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        signer=replace(good.signer, network_runtime_imports_keypair=True),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    assert ReleaseFailureReason.PRIVATE_KEY_IN_NETWORK in _reasons(report)


def test_pr157_development_memory_signer_blocks_release() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        signer=replace(good.signer, signer_backend=SignerBackendKind.DEVELOPMENT_MEMORY),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    assert ReleaseFailureReason.UNSUPPORTED_SIGNER_BACKEND in _reasons(report)


def test_pr157_signer_must_parse_message_and_verify_proofs() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        signer=replace(
            good.signer,
            signer_parses_exact_v0_message=False,
            signer_verifies_policy_and_proof_hashes=False,
        ),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    assert ReleaseFailureReason.SIGNER_NOT_ISOLATED in _reasons(report)


def test_pr157_authorization_requires_all_bindings() -> None:
    good = _good_evidence()
    bindings = _bindings()
    del bindings["simulation_cpi_proof_hash"]
    evidence = replace(
        good,
        authorization=replace(good.authorization, bindings=bindings),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    assert ReleaseFailureReason.AUTHORIZATION_INCOMPLETE in _reasons(report)
    assert "simulation_cpi_proof_hash" in report.failures[0].detail


def test_pr157_plain_or_expired_authorization_blocks_release() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        authorization=replace(
            good.authorization,
            caller_constructable_plain_dataclass=True,
            expiry_unix_ms=NOW - 1,
        ),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    assert ReleaseFailureReason.PLAIN_CALLER_PERMIT in _reasons(report)
    assert ReleaseFailureReason.AUTHORIZATION_REPLAYABLE in _reasons(report)


def test_pr157_unknown_submission_state_and_auto_resend_blocks_release() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        submission=SubmissionLifecycleEvidence(
            current_state=SubmissionState.UNKNOWN,
            durable_signing_intent=True,
            signed_payload_verified=True,
            durable_submission_intent=True,
            auto_resend_on_ambiguity=True,
            ambiguity_latch_enabled=False,
            indeterminate_outcome=True,
        ),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    reasons = _reasons(report)
    assert ReleaseFailureReason.SUBMISSION_STATE_AMBIGUOUS in reasons
    assert ReleaseFailureReason.AUTO_RESEND_ON_AMBIGUITY in reasons
    assert ReleaseFailureReason.LATCH_MISSING in reasons
    assert ReleaseFailureReason.INDETERMINATE_OUTCOME in reasons


def test_pr157_jito_standalone_or_missing_tip_evidence_blocks_release() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        jito=JitoSafetyEvidence(
            enabled=True,
            one_atomic_transaction=False,
            tip_inside_same_transaction=False,
            exactly_one_tip=False,
            current_tip_account_evidence_hash=None,
            bundle_only_reviewed=False,
            standalone_tip_forbidden=False,
            uncle_unbundling_drill_hash=None,
        ),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    assert _reasons(report) == {ReleaseFailureReason.JITO_UNSAFE}
    assert len(report.failures) >= 5


def test_pr157_settlement_must_be_finalized_and_reconciled() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        settlement=replace(
            good.settlement,
            finalized=False,
            get_transaction_max_supported_v0=False,
            meta_err_is_none=False,
            conservative_net_lamports=-1,
        ),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    assert ReleaseFailureReason.SETTLEMENT_NOT_FINALIZED in _reasons(report)
    assert ReleaseFailureReason.SETTLEMENT_RECONCILIATION_MISSING in _reasons(report)


def test_pr157_hermetic_release_requires_pins_and_artifacts() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        release=HermeticReleaseEvidence(
            github_actions_pinned_to_full_sha=False,
            docker_image_pinned_by_digest=False,
            hashed_wheelhouse=False,
            offline_reproducible_build=False,
            sbom_hash=_hash("sbom"),
            vulnerability_scan_hash=_hash("vuln"),
            license_inventory_hash=_hash("license"),
            secret_scan_hash=_hash("secret-scan"),
            signed_artifact_provenance_hash=_hash("provenance"),
        ),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    assert len(
        [f for f in report.failures if f.reason is ReleaseFailureReason.RELEASE_NOT_HERMETIC]
    ) == 4


def test_pr157_sandbox_must_isolate_network_and_signer() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        sandbox=ProductionSandboxEvidence(
            read_only_root_fs=False,
            capability_drop=False,
            no_new_privileges=False,
            seccomp_or_apparmor=False,
            cpu_memory_pid_fd_limits=False,
            egress_allowlist=False,
            signer_network_separation=False,
        ),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    assert len(
        [f for f in report.failures if f.reason is ReleaseFailureReason.SANDBOX_INCOMPLETE]
    ) == 7


def test_pr157_canary_requires_soak_tiny_exposure_and_dual_approval() -> None:
    good = _good_evidence()
    evidence = replace(
        good,
        canary=ReviewedCanaryEvidence(
            mode=CanaryMode.REVIEWED_TINY_CANARY,
            default_package_live_disabled=True,
            default_config_live_disabled=True,
            single_env_live_enable_forbidden=True,
            actual_soak_seconds=1,
            tiny_allowlisted_exposure_lamports=20,
            max_tiny_exposure_lamports=10,
            protected_sol_reserve_lamports=1_000,
            one_outstanding_submission=False,
            loss_stale_ambiguity_latches=False,
            manual_kill_switch=False,
            dual_human_approval_hash=None,
            rollback_to_shadow_hash=None,
        ),
    )

    report = evaluate_release_gate(evidence, now_unix_ms=NOW)

    reasons = _reasons(report)
    assert ReleaseFailureReason.SOAK_INCOMPLETE in reasons
    assert ReleaseFailureReason.EXPOSURE_TOO_LARGE in reasons
    assert ReleaseFailureReason.OPERATOR_APPROVAL_MISSING in reasons
    assert ReleaseFailureReason.LATCH_MISSING in reasons


def test_pr157_placeholder_hash_rejected_on_construction() -> None:
    with pytest.raises(ValueError):
        SignerBoundaryEvidence(
            network_runtime_imports_keypair=False,
            network_runtime_has_private_key_bytes=False,
            signer_backend=SignerBackendKind.KMS,
            signer_parses_exact_v0_message=True,
            signer_derives_payer_signers_programs_accounts=True,
            signer_verifies_policy_and_proof_hashes=True,
            signer_checks_full_wire_limit=True,
            signer_returns_signature_only=True,
            signer_has_general_network_access=False,
            signer_identity_hash="0" * 64,
            backend_public_key_hash=_hash("pubkey"),
        )


def test_pr157_evidence_hash_changes_when_settlement_changes() -> None:
    good = _good_evidence()
    changed = replace(
        good,
        settlement=replace(
            good.settlement,
            actual_fee_lamports=good.settlement.actual_fee_lamports + 1,
        ),
    )

    first = evaluate_release_gate(good, now_unix_ms=NOW)
    second = evaluate_release_gate(changed, now_unix_ms=NOW)

    assert first.evidence_hash != second.evidence_hash


def test_pr157_static_scanner_detects_bypass_tokens() -> None:
    source = """
    from solders.keypair import Keypair
    rpc.sendTransaction(tx, opts={"skipPreflight": True})
    import src.execution.live_control
    """

    findings = scan_forbidden_live_surface(source)

    assert "Keypair" in findings
    assert "sendTransaction" in findings
    assert "skipPreflight" in findings
    assert "live_control" in findings


def test_pr157_static_scanner_is_quiet_for_release_gate_code() -> None:
    source = "def evaluate_release_gate(evidence): return evidence"

    assert scan_forbidden_live_surface(source) == ()
