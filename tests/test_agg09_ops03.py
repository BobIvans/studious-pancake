from __future__ import annotations

from src.operations.agg09_ops03 import (
    CIPipelineEvidence,
    CIStageEvidence,
    CapitalProgressionEvidence,
    OperationalSoakEvidence,
    ProductionReadinessInput,
    ReadinessVerdict,
    ReleaseArtifactEvidence,
    evaluate_capital_progression,
    evaluate_production_readiness,
)
from src.operations.mpr2614_continuous_conformance import (
    ConformanceDecision,
    RuntimeConformanceLease,
)

GIT = "a" * 40
H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64
H6 = "6" * 64
H7 = "7" * 64
H8 = "8" * 64
H9 = "9" * 64


def _ci(*, missing: bool = False) -> CIPipelineEvidence:
    names = (
        "unit",
        "contract",
        "vm",
        "installed",
        "integration",
        "security",
        "disaster-replay",
    )
    if missing:
        names = names[:-1]
    return CIPipelineEvidence(
        source_commit=GIT,
        stages=tuple(CIStageEvidence(name, "PASS", H1) for name in names),
        network_suite_status="NOT_AUTHORIZED",
        live_suite_status="NOT_AUTHORIZED",
    )


def _release() -> ReleaseArtifactEvidence:
    return ReleaseArtifactEvidence(
        source_commit=GIT,
        tree_sha256=H1,
        wheel_sha256=H2,
        image_sha256=H3,
        lock_sha256=H4,
        sbom_sha256=H5,
        notice_sha256=H6,
        config_sha256=H7,
        policy_sha256=H8,
        installed_smoke_passed=True,
        licenses_complete=True,
        quarantined_sender_in_supported_wheel=False,
        live_enabled_by_environment=False,
    )


def _conformance(*, healthy: bool = True) -> ConformanceDecision:
    lease = RuntimeConformanceLease(
        release_generation=1,
        release_decision_hash=H1,
        release_pin_digest=H2,
        operating_envelope_hash=H3,
        process_id="agg09-test",
        boot_generation=1,
        observation_digest=H4,
        issued_monotonic_ns=10,
        expires_monotonic_ns=20,
    )
    return ConformanceDecision(
        healthy=healthy,
        reason_codes=() if healthy else ("TEST_DRIFT",),
        lease=lease if healthy else None,
        suspension_required=not healthy,
        release_generation=1,
        observation_digest=H4,
        live_enabled=False,
        signer_allowed=False,
        submission_allowed=False,
        automatic_rearm_allowed=False,
    )


def _soak(*, duration: int = 10) -> OperationalSoakEvidence:
    return OperationalSoakEvidence(
        policy_sha256=H9,
        declared_min_duration_seconds=10,
        actual_duration_seconds=duration,
        busy_window_count=1,
        quiet_window_count=1,
        restart_drill_count=1,
        failover_drill_count=1,
        incident_count=1,
        resolved_incident_count=1,
        data_gap_count=0,
        dropped_work_count=0,
        ledger_accurate_after_recovery=True,
        stable_state_restored=True,
    )


def test_nf251_ci_matrix_does_not_convert_skipped_external_suites_into_pass() -> None:
    ci = _ci()
    assert ci.passed is True
    assert ci.network_suite_status == "NOT_AUTHORIZED"
    assert ci.live_suite_status == "NOT_AUTHORIZED"

    incomplete = _ci(missing=True)
    assert incomplete.passed is False
    assert "AGG09_CI_REQUIRED_STAGE_MISSING" in incomplete.reason_codes


def test_nf252_release_artifact_is_default_off_and_installed() -> None:
    release = _release()
    assert release.passed is True
    assert release.semantic_digest


def test_nf254_soak_requires_predeclared_duration_and_recovery() -> None:
    assert _soak(duration=10).passed is True
    short = _soak(duration=9)
    assert short.passed is False
    assert "AGG09_SOAK_DURATION_SHORT" in short.reason_codes


def test_nf255_capital_progression_never_becomes_automatic() -> None:
    allowed = evaluate_capital_progression(
        CapitalProgressionEvidence(
            current_owned_atoms=1_000,
            protected_fee_reserve_atoms=100,
            minimum_fee_reserve_atoms=100,
            requested_additional_spend_atoms=50,
            measured_bottleneck="rpc-throughput",
            independent_canary_passed=True,
            explicit_user_approval=True,
        )
    )
    assert allowed.allowed is True
    assert allowed.automatic is False

    blocked = evaluate_capital_progression(
        CapitalProgressionEvidence(
            current_owned_atoms=1_000,
            protected_fee_reserve_atoms=50,
            minimum_fee_reserve_atoms=100,
            requested_additional_spend_atoms=50,
            measured_bottleneck=None,
            independent_canary_passed=False,
            explicit_user_approval=False,
        )
    )
    assert blocked.allowed is False
    assert blocked.automatic is False


def test_nf256_readiness_is_blocked_when_upstream_agg08_live03_are_missing() -> None:
    verdict = evaluate_production_readiness(
        ProductionReadinessInput(
            release_profile="production-ready-default-off",
            source_commit=GIT,
            agg04_qualified=True,
            agg05_runtime_ready=True,
            agg08_execution_evidence_ready=False,
            live03_landing_evidence_ready=False,
            ops01_ready=True,
            ops02_ready=True,
            ci=_ci(),
            release=_release(),
            conformance=_conformance(),
            soak=_soak(),
            external_rights_and_reserves_known=True,
            research_scope_traceable=True,
        )
    )
    assert verdict.verdict is ReadinessVerdict.BLOCKED
    assert verdict.operational_status == "BLOCKED"
    assert "AGG09_PREREQUISITE_AGG08_MISSING" in verdict.reason_codes
    assert "AGG09_LIVE03_EVIDENCE_MISSING" in verdict.reason_codes
    assert verdict.live_enabled is False
    assert verdict.automatic_scale_up_allowed is False


def test_nf256_qualified_result_is_scoped_default_off_only() -> None:
    verdict = evaluate_production_readiness(
        ProductionReadinessInput(
            release_profile="production-ready-default-off",
            source_commit=GIT,
            agg04_qualified=True,
            agg05_runtime_ready=True,
            agg08_execution_evidence_ready=True,
            live03_landing_evidence_ready=True,
            ops01_ready=True,
            ops02_ready=True,
            ci=_ci(),
            release=_release(),
            conformance=_conformance(),
            soak=_soak(),
            external_rights_and_reserves_known=True,
            research_scope_traceable=True,
        )
    )
    assert verdict.verdict is ReadinessVerdict.QUALIFIED_DEFAULT_OFF
    assert verdict.implementation_status == "IMPLEMENTED_OFFLINE"
    assert verdict.live_enabled is False
    assert verdict.automatic_scale_up_allowed is False
