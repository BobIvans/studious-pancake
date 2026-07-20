from __future__ import annotations

from src.live_canary import CanaryMode, CanaryReport, LatchCode
from src.release_gate.canary_release_readiness import (
    CanaryReleaseReadinessGate,
    ReadinessBlocker,
    UpstreamDependency,
    UpstreamEvidenceRecord,
)
from src.release_gate.gate import ReleaseGateResult

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64
F = "f" * 64


def upstream_evidence(
    *, human_reviewed: bool = True, passed: bool = True
) -> tuple[UpstreamEvidenceRecord, ...]:
    hashes = {
        UpstreamDependency.PR060_SHADOW_SOAK: A,
        UpstreamDependency.PR061_DATA_LIFECYCLE_OBSERVABILITY: B,
        UpstreamDependency.PR062_SECURITY_CHAOS_OPS: C,
        UpstreamDependency.PR063_SENDER_CONSOLIDATION: D,
    }
    return tuple(
        UpstreamEvidenceRecord(
            dependency=dependency,
            evidence_hash=digest,
            source_ref=f"https://github.com/BobIvans/studious-pancake/pull/{60 + index}",
            passed=passed,
            human_reviewed=human_reviewed,
            reviewer="human-release-reviewer",
        )
        for index, (dependency, digest) in enumerate(hashes.items())
    )


def canary_report(**overrides: object) -> CanaryReport:
    values: dict[str, object] = {
        "schema_version": "pr046.canary-report.v1",
        "policy_hash": A,
        "evidence_hash": B,
        "mode": CanaryMode.LIMITED_LIVE,
        "armed": True,
        "armed_until_ms": 123_000,
        "outstanding_attempt_id": None,
        "active_latches": (),
        "daily_realized_pnl_lamports": 0,
        "consecutive_failures": 0,
        "event_count": 3,
        "event_digest": C,
        "ai_authority": False,
    }
    values.update(overrides)
    return CanaryReport(**values)


def release_result(**overrides: object) -> ReleaseGateResult:
    values: dict[str, object] = {
        "schema_version": "pr047.release-gate-result.v1",
        "release_id": "release-2026-07-21-canary-1",
        "production_ready": True,
        "state": "production-ready",
        "manifest_sha256": E,
        "blockers": (),
        "warnings": (),
        "checks_evaluated": 42,
    }
    values.update(overrides)
    return ReleaseGateResult(**values)


def evaluate(
    *,
    report: CanaryReport | None = None,
    release: ReleaseGateResult | None = None,
    upstream: tuple[UpstreamEvidenceRecord, ...] | None = None,
):
    return CanaryReleaseReadinessGate().evaluate(
        canary_report=report or canary_report(),
        release_result=release or release_result(),
        upstream_evidence=upstream if upstream is not None else upstream_evidence(),
    )


def test_complete_pr064_evidence_is_ready_without_mutating_live() -> None:
    result = evaluate()

    assert result.ready is True
    assert result.state == "ready-for-human-controlled-canary-release"
    assert result.blockers == ()
    assert len(result.upstream_evidence_hash) == 64
    assert result.canary_report_hash == canary_report().report_hash
    assert result.release_manifest_hash == E
    assert result.ai_authority is False
    assert result.live_mode_mutated is False


def test_missing_upstream_dependency_blocks_pr064() -> None:
    incomplete = tuple(
        item
        for item in upstream_evidence()
        if item.dependency is not UpstreamDependency.PR063_SENDER_CONSOLIDATION
    )

    result = evaluate(upstream=incomplete)

    assert result.ready is False
    assert ReadinessBlocker.UPSTREAM_EVIDENCE_MISSING.value in result.blockers


def test_upstream_dependency_must_pass_and_be_human_reviewed() -> None:
    failed = evaluate(upstream=upstream_evidence(passed=False))
    unreviewed = evaluate(upstream=upstream_evidence(human_reviewed=False))

    assert ReadinessBlocker.UPSTREAM_EVIDENCE_NOT_PASSED.value in failed.blockers
    assert (
        ReadinessBlocker.UPSTREAM_EVIDENCE_NOT_HUMAN_REVIEWED.value
        in unreviewed.blockers
    )


def test_canary_report_must_be_armed_idle_and_human_authorized() -> None:
    result = evaluate(
        report=canary_report(
            ai_authority=True,
            armed=False,
            active_latches=(LatchCode.MANUAL_KILL_SWITCH,),
            outstanding_attempt_id="attempt-1",
        )
    )

    assert ReadinessBlocker.CANARY_AI_AUTHORITY_PRESENT.value in result.blockers
    assert ReadinessBlocker.CANARY_NOT_ARMED.value in result.blockers
    assert ReadinessBlocker.CANARY_ACTIVE_LATCH.value in result.blockers
    assert ReadinessBlocker.CANARY_OUTSTANDING_SUBMISSION.value in result.blockers


def test_shadow_or_unreviewed_canary_state_blocks_release_readiness() -> None:
    result = evaluate(
        report=canary_report(
            mode=CanaryMode.SHADOW,
            evidence_hash=None,
        )
    )

    assert ReadinessBlocker.CANARY_NOT_LIMITED_LIVE.value in result.blockers
    assert ReadinessBlocker.CANARY_EVIDENCE_HASH_MISSING.value in result.blockers


def test_release_gate_blockers_are_carried_forward() -> None:
    result = evaluate(
        release=release_result(
            production_ready=False,
            state="blocked",
            blockers=("REQUIRED_SIGNOFFS_MISSING",),
            manifest_sha256=F,
        )
    )

    assert ReadinessBlocker.RELEASE_GATE_NOT_READY.value in result.blockers
    assert ReadinessBlocker.RELEASE_GATE_HAS_BLOCKERS.value in result.blockers
    assert result.release_manifest_hash == F


def test_placeholder_manifest_hash_blocks_even_if_release_flag_is_true() -> None:
    result = evaluate(release=release_result(manifest_sha256="0" * 64))

    assert ReadinessBlocker.RELEASE_MANIFEST_HASH_INVALID.value in result.blockers
