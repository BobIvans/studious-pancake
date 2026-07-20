from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from src.release_gate import (
    DEFAULT_REQUIRED_FAILURE_AREAS,
    FailureInjectionScenario,
    OperationalDrillSuite,
    OperationalFailureArea,
    OperationalReadinessGate,
    SecurityOperationalEvidence,
)
from src.security import Severity, VulnerabilityRecord

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
IMAGE_DIGEST = "sha256:" + "c" * 64


def _security(**changes: object) -> SecurityOperationalEvidence:
    payload: dict[str, object] = {
        "generated_at": NOW,
        "records": (),
        "sbom_sha256": SHA_A,
        "image_digest": IMAGE_DIGEST,
        "isolated_signer_reference": "keychain:flashloan-canary",
        "secret_scan_passed": True,
        "plaintext_key_findings": (),
        "signer_policy_enforced": True,
        "release_manifest_sha256": SHA_B,
    }
    payload.update(changes)
    return SecurityOperationalEvidence.from_vulnerability_records(**payload)


def _scenario(
    area: OperationalFailureArea,
    **changes: object,
) -> FailureInjectionScenario:
    payload: dict[str, object] = {
        "area": area,
        "scenario_id": f"scenario-{area.value}",
        "injected_failure": f"inject {area.value}",
        "expected_safe_state": "blocked_manual_review",
        "passed": True,
        "safe_state_proven": True,
        "evidence_sha256": SHA_A,
        "max_retry_attempts": 3,
        "observed_retry_attempts": 1,
        "max_queue_depth": 10,
        "observed_queue_depth": 2,
        "max_rto_seconds": 60,
        "observed_rto_seconds": 30,
        "automatic_resubmission_attempted": False,
        "residual_task_count": 0,
    }
    payload.update(changes)
    return FailureInjectionScenario(**payload)


def _suite(**changes: object) -> OperationalDrillSuite:
    payload: dict[str, object] = {
        "suite_id": "pr062-drill-suite-2026-07-21",
        "run_started_at": NOW,
        "run_finished_at": NOW,
        "operator": "operator@example.com",
        "environment": "paper-shadow-ci",
        "security": _security(),
        "scenarios": tuple(_scenario(area) for area in OperationalFailureArea),
        "manual_rollback_rehearsed": True,
        "kill_switch_rehearsed": True,
        "no_live_submission": True,
    }
    payload.update(changes)
    return OperationalDrillSuite(**payload)


def test_complete_pr062_suite_is_ready_and_deterministic() -> None:
    first = _suite()
    second = _suite()

    result = OperationalReadinessGate(evaluated_at=NOW).evaluate(first)

    assert first.suite_hash == second.suite_hash
    assert result.ready_for_limited_live is True
    assert result.state == "ready-for-limited-live"
    assert not result.blockers
    assert result.suite_hash == first.suite_hash


def test_all_required_failure_areas_must_be_rehearsed() -> None:
    missing_area = OperationalFailureArea.JITO_AMBIGUOUS_SUBMISSION
    scenarios = tuple(
        scenario for scenario in _suite().scenarios if scenario.area is not missing_area
    )

    result = OperationalReadinessGate(evaluated_at=NOW).evaluate(
        _suite(scenarios=scenarios)
    )

    assert DEFAULT_REQUIRED_FAILURE_AREAS == frozenset(OperationalFailureArea)
    assert "REQUIRED_FAILURE_SCENARIOS_MISSING" in result.blockers
    assert "SCENARIO_MISSING:jito-ambiguous-submission" in result.blockers


def test_security_evidence_blocks_plaintext_and_dependency_findings() -> None:
    security = _security(
        secret_scan_passed=False,
        plaintext_key_findings=("WALLET_PRIVATE_KEY",),
        records=(
            VulnerabilityRecord(
                package="dangerous-lib",
                vulnerability_id="CVE-2099-0001",
                severity=Severity.CRITICAL,
                source="unit-test",
            ),
        ),
    )

    result = OperationalReadinessGate(evaluated_at=NOW).evaluate(
        _suite(security=security)
    )

    assert "SECRET_SCAN_NOT_PASSED" in result.blockers
    assert "PLAINTEXT_KEY_FINDINGS_PRESENT" in result.blockers
    assert "DEPENDENCY_AUDIT_BLOCKED" in result.blockers
    assert any(item.startswith("DEPENDENCY_AUDIT_BLOCKER:") for item in result.warnings)


def test_failure_injection_bounds_and_unsafe_states_block() -> None:
    scenarios = list(_suite().scenarios)
    index = next(
        idx
        for idx, scenario in enumerate(scenarios)
        if scenario.area is OperationalFailureArea.PROVIDER_RATE_LIMIT
    )
    scenarios[index] = replace(
        scenarios[index],
        expected_safe_state="landed",
        observed_retry_attempts=4,
        observed_queue_depth=11,
        observed_rto_seconds=61,
        automatic_resubmission_attempted=True,
        residual_task_count=1,
    )

    result = OperationalReadinessGate(evaluated_at=NOW).evaluate(
        _suite(scenarios=tuple(scenarios))
    )

    prefix = OperationalFailureArea.PROVIDER_RATE_LIMIT.value
    assert f"RETRY_BOUND_EXCEEDED:{prefix}" in result.blockers
    assert f"QUEUE_BOUND_EXCEEDED:{prefix}" in result.blockers
    assert f"RTO_BOUND_EXCEEDED:{prefix}" in result.blockers
    assert f"AUTOMATIC_RESUBMISSION_ATTEMPTED:{prefix}" in result.blockers
    assert f"RESIDUAL_TASKS_AFTER_DRILL:{prefix}" in result.blockers
    assert f"UNSAFE_EXPECTED_STATE:{prefix}" in result.blockers


def test_signer_reference_hashes_and_live_submission_are_fail_closed() -> None:
    security = _security(
        isolated_signer_reference="plaintext-private-key",
        sbom_sha256="0" * 64,
        image_digest="sha256:" + "0" * 64,
        release_manifest_sha256="not-a-hash",
        signer_policy_enforced=False,
    )
    result = OperationalReadinessGate(evaluated_at=NOW).evaluate(
        _suite(security=security, no_live_submission=False)
    )

    assert "ISOLATED_SIGNER_REFERENCE_NOT_STRUCTURAL" in result.blockers
    assert "SIGNER_POLICY_NOT_ENFORCED" in result.blockers
    assert "SBOM_DIGEST_INVALID" in result.blockers
    assert "IMAGE_DIGEST_INVALID" in result.blockers
    assert "RELEASE_MANIFEST_DIGEST_INVALID" in result.blockers
    assert "LIVE_SUBMISSION_OCCURRED_DURING_DRILL" in result.blockers
