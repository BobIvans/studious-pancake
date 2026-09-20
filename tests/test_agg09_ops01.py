from __future__ import annotations

from src.ha_dr.mpr2616 import CoordinatorCapabilities, RestoreEvidence
from src.operations.agg09_ops01 import (
    AssetRiskCap,
    CredentialRecoveryEvidence,
    PortfolioExposure,
    RecoveryEvidence,
    SecurityBoundaryEvidence,
    evaluate_credential_recovery,
    evaluate_portfolio_budget,
    evaluate_recovery,
    evaluate_security_boundaries,
)

H = "a" * 64
H2 = "b" * 64


def _restore() -> RestoreEvidence:
    return RestoreEvidence(
        release_generation=1,
        backup_artifact_digest=H,
        object_receipt_digest=H2,
        wal_included=True,
        integrity_ok=True,
        critical_state_before_digest=H,
        critical_state_after_digest=H,
        consumed_permits_preserved=True,
        unknown_holds_preserved=True,
        risk_counters_not_decreased=True,
        suspension_preserved=True,
        fence_generation_not_decreased=True,
        committed_ns=1_000_000_000,
        restored_ns=2_000_000_000,
    )


def _coordinator(*, production: bool) -> CoordinatorCapabilities:
    return CoordinatorCapabilities(
        backend_id="test",
        cross_host=production,
        strongly_consistent=True,
        monotonic_generation=True,
        compare_and_swap=True,
        coordinator_native_expiry=True,
        survives_application_host_loss=production,
        sandbox_only=not production,
    )


def test_nf240_shared_equity_is_not_duplicated_across_strategies() -> None:
    exposures = (
        PortfolioExposure(
            owner_id="treasury",
            strategy_id="circular",
            chain_id="solana",
            asset_id="SOL",
            owned_equity_atoms=1_000,
            reserved_atoms=200,
            unresolved_atoms=0,
            worst_failure_atoms=100,
            provider_spend_atoms=10,
        ),
        PortfolioExposure(
            owner_id="treasury",
            strategy_id="stable",
            chain_id="solana",
            asset_id="SOL",
            owned_equity_atoms=1_000,
            reserved_atoms=300,
            unresolved_atoms=50,
            worst_failure_atoms=100,
            provider_spend_atoms=10,
        ),
    )
    state = evaluate_portfolio_budget(
        exposures,
        (AssetRiskCap("SOL", max_total_risk_atoms=800, protected_reserve_atoms=100),),
    )
    assert state.allowed is True
    assert state.decisions[0].owned_equity_atoms == 1_000
    assert state.decisions[0].used_risk_atoms == 770
    assert state.decisions[0].free_owned_atoms == 130
    assert state.live_enabled is False
    assert state.automatic_scale_up_allowed is False


def test_nf240_client_capital_and_lender_capacity_never_become_equity() -> None:
    state = evaluate_portfolio_budget(
        (
            PortfolioExposure(
                owner_id="treasury",
                strategy_id="circular",
                chain_id="solana",
                asset_id="SOL",
                owned_equity_atoms=100,
                reserved_atoms=50,
                unresolved_atoms=0,
                worst_failure_atoms=60,
                provider_spend_atoms=0,
                collateral_atoms=10_000,
                loan_capacity_atoms=10_000,
                client_capital_atoms=10_000,
            ),
        ),
        (AssetRiskCap("SOL", max_total_risk_atoms=1_000, protected_reserve_atoms=0),),
    )
    assert state.allowed is False
    assert "AGG09_CLIENT_CAPITAL_PRESENT_IN_OWNER_SCOPE" in state.reason_codes
    assert "AGG09_PORTFOLIO_OWNED_EQUITY_EXHAUSTED" in state.reason_codes


def test_nf243_default_off_restore_is_separate_from_production_ha() -> None:
    sandbox = evaluate_recovery(
        RecoveryEvidence(
            restore=_restore(),
            coordinator=_coordinator(production=False),
            prior_fence_generation=2,
            recovered_fence_generation=3,
            reservations_preserved=True,
            unknown_dispatches_quarantined=True,
            revoked_credentials_preserved=True,
            chain_state_reconciled=True,
            signer_recovery_proven=False,
        )
    )
    assert sandbox.restore_safe_default_off is True
    assert sandbox.production_failover_qualified is False
    assert sandbox.resend_unknown_allowed is False
    assert "AGG09_HA_COORDINATOR_NOT_PRODUCTION_QUALIFIED" in sandbox.reason_codes

    production = evaluate_recovery(
        RecoveryEvidence(
            restore=_restore(),
            coordinator=_coordinator(production=True),
            prior_fence_generation=2,
            recovered_fence_generation=3,
            reservations_preserved=True,
            unknown_dispatches_quarantined=True,
            revoked_credentials_preserved=True,
            chain_state_reconciled=True,
            signer_recovery_proven=True,
        )
    )
    assert production.production_failover_qualified is True


def test_nf243_stale_fence_or_unknown_dispatch_fails_closed() -> None:
    result = evaluate_recovery(
        RecoveryEvidence(
            restore=_restore(),
            coordinator=_coordinator(production=True),
            prior_fence_generation=3,
            recovered_fence_generation=3,
            reservations_preserved=True,
            unknown_dispatches_quarantined=False,
            revoked_credentials_preserved=True,
            chain_state_reconciled=True,
            signer_recovery_proven=True,
        )
    )
    assert result.restore_safe_default_off is False
    assert "AGG09_FENCE_DID_NOT_ADVANCE" in result.reason_codes
    assert "AGG09_UNKNOWN_DISPATCH_NOT_QUARANTINED" in result.reason_codes


def test_nf245_security_boundary_requires_every_fail_closed_control() -> None:
    safe = SecurityBoundaryEvidence(
        endpoint_allowlist_enforced=True,
        ssrf_private_targets_blocked=True,
        dns_rebinding_blocked=True,
        tls_policy_enforced=True,
        redirects_bounded=True,
        json_size_bounded=True,
        decompression_bounded=True,
        archive_traversal_blocked=True,
        filesystem_permissions_least_privilege=True,
        untrusted_metadata_non_executable=True,
        callpath_evidence_sha256=H,
    )
    assert evaluate_security_boundaries(safe).passed is True
    unsafe = SecurityBoundaryEvidence(
        **{
            **{name: getattr(safe, name) for name in safe.__dataclass_fields__},
            "dns_rebinding_blocked": False,
        }
    )
    report = evaluate_security_boundaries(unsafe)
    assert report.passed is False
    assert "AGG09_DNS_REBINDING_NOT_BLOCKED" in report.reason_codes


def test_nf246_restore_cannot_resurrect_revoked_credential() -> None:
    ok = CredentialRecoveryEvidence(
        secret_id="provider-jupiter",
        active_version="v2",
        active_rotation_epoch=4,
        active_revocation_epoch=7,
        restored_rotation_epoch=4,
        restored_revocation_epoch=7,
        stale_handle_rejected=True,
        logs_redacted=True,
        rollback_resurrected_revoked_version=False,
        evidence_sha256=H,
    )
    assert evaluate_credential_recovery(ok).accepted is True

    bad = CredentialRecoveryEvidence(
        secret_id="provider-jupiter",
        active_version="v2",
        active_rotation_epoch=4,
        active_revocation_epoch=7,
        restored_rotation_epoch=3,
        restored_revocation_epoch=6,
        stale_handle_rejected=False,
        logs_redacted=False,
        rollback_resurrected_revoked_version=True,
        evidence_sha256=H,
    )
    result = evaluate_credential_recovery(bad)
    assert result.accepted is False
    assert "AGG09_ROTATION_EPOCH_ROLLED_BACK" in result.reason_codes
    assert "AGG09_REVOCATION_EPOCH_ROLLED_BACK" in result.reason_codes
    assert "AGG09_REVOKED_CREDENTIAL_RESURRECTED" in result.reason_codes
