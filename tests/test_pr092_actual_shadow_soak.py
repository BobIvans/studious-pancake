from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from src.shadow_soak.evidence import (
    ReplayEvidence,
    ShadowSoakError,
    ShadowSoakEvidence,
    ShadowSoakMetrics,
    SoakArtifactKind,
    SoakArtifactReference,
    SoakEnvironment,
)
from src.shadow_soak.pr092_actual_soak import (
    REQUIRED_PR092_ARTIFACTS,
    REQUIRED_PR092_PREREQUISITES,
    PR092ActualSoakArtifactKind,
    PR092ActualSoakManifest,
    PR092ActualSoakState,
    PR092PrerequisiteEvidence,
    PR092SoakArtifactPin,
    evaluate_pr092_actual_shadow_soak,
)

START = datetime(2026, 7, 1, tzinfo=timezone.utc)
END = START + timedelta(hours=73)
REVIEWED = END + timedelta(hours=1)
ASSEMBLED = REVIEWED + timedelta(minutes=5)
COMMIT = "abcdef1234567890abcdef1234567890abcdef12"


def _digest(seed: str) -> str:
    return sha256(seed.encode("utf-8")).hexdigest()


def _write_pin(
    root: Path,
    kind: PR092ActualSoakArtifactKind,
    seed: str,
    *,
    event_count: int | None = None,
) -> PR092SoakArtifactPin:
    path = f"artifacts/shadow-soak/pr092/run-20260701/{kind.value}.json"
    payload = (
        f"{{\"kind\":\"{kind.value}\",\"seed\":\"{seed}\","
        f"\"run\":\"pr092-actual-soak\"}}\n"
    ).encode("utf-8")
    full_path = root / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(payload)
    return PR092SoakArtifactPin(
        kind=kind,
        path=path,
        sha256=sha256(payload).hexdigest(),
        size_bytes=len(payload),
        produced_at=END,
        producer="pr092-shadow-runner",
        event_count=event_count,
    )


def _metrics() -> ShadowSoakMetrics:
    return ShadowSoakMetrics(
        candidates_seen=24,
        candidates_simulated=18,
        candidates_rejected=6,
        paper_outcomes_written=10,
        outcomes_reconciled=10,
        reconciliation_mismatches=0,
        message_hash_mismatches=0,
        repayment_mismatches=0,
        ambiguous_outcomes=0,
        quota_exhaustions=0,
        provider_5xx_errors=0,
        rpc_errors=0,
        stale_data_rejections=3,
        stale_data_accepted=0,
        p50_latency_ms=80,
        p95_latency_ms=130,
        max_latency_ms=210,
        net_pnl_lamports=42,
    )


def _soak(pins: tuple[PR092SoakArtifactPin, ...], environment: SoakEnvironment):
    by_kind = {pin.kind: pin for pin in pins}
    artifacts = (
        SoakArtifactReference(
            path=by_kind[PR092ActualSoakArtifactKind.RAW_EVENTS].path,
            sha256=by_kind[PR092ActualSoakArtifactKind.RAW_EVENTS].sha256,
            kind=SoakArtifactKind.RAW_EVENTS,
            event_count=24,
        ),
        SoakArtifactReference(
            path=by_kind[PR092ActualSoakArtifactKind.REPLAY_CORPUS].path,
            sha256=by_kind[PR092ActualSoakArtifactKind.REPLAY_CORPUS].sha256,
            kind=SoakArtifactKind.REPLAY_CORPUS,
            event_count=24,
        ),
        SoakArtifactReference(
            path=by_kind[PR092ActualSoakArtifactKind.METRICS_REPORT].path,
            sha256=by_kind[PR092ActualSoakArtifactKind.METRICS_REPORT].sha256,
            kind=SoakArtifactKind.METRICS_REPORT,
            event_count=1,
        ),
        SoakArtifactReference(
            path=by_kind[PR092ActualSoakArtifactKind.OPERATOR_REVIEW].path,
            sha256=by_kind[PR092ActualSoakArtifactKind.OPERATOR_REVIEW].sha256,
            kind=SoakArtifactKind.OPERATOR_REVIEW,
            event_count=1,
        ),
    )
    return ShadowSoakEvidence(
        run_id="pr092-actual-soak",
        code_commit=COMMIT,
        started_at=START,
        ended_at=END,
        environment=environment,
        vertical_stages=(
            "discovery",
            "capital",
            "planner",
            "compiler",
            "simulation",
            "reconciliation",
            "lifecycle",
        ),
        metrics=_metrics(),
        replay=ReplayEvidence(
            corpus_events=24,
            replayed_events=24,
            deterministic_passed_events=24,
            deterministic_failed_events=0,
            corpus_sha256=by_kind[PR092ActualSoakArtifactKind.REPLAY_CORPUS].sha256,
        ),
        artifacts=artifacts,
        operator="operator",
        human_reviewed=True,
        reviewer="reviewer",
        reviewed_at=REVIEWED,
        signed_by="release-key",
        signature_reference=by_kind[PR092ActualSoakArtifactKind.BUNDLE_SIGNATURE].path,
    )


def _prerequisite(name: str) -> PR092PrerequisiteEvidence:
    return PR092PrerequisiteEvidence(
        name=name,
        evidence_path=f"artifacts/shadow-soak/pr092/prerequisites/{name}.json",
        evidence_sha256=_digest(name),
        source_commit=COMMIT,
        passed=True,
        human_reviewed=True,
        reviewer="reviewer",
    )


def _manifest(root: Path, **overrides) -> PR092ActualSoakManifest:
    pins = tuple(
        _write_pin(root, kind, f"seed-{index}", event_count=24)
        for index, kind in enumerate(REQUIRED_PR092_ARTIFACTS, start=1)
    )
    values = {
        "run_id": "pr092-actual-soak",
        "soak": _soak(pins, SoakEnvironment.MAINNET_READ_ONLY),
        "prerequisites": tuple(
            _prerequisite(name) for name in REQUIRED_PR092_PREREQUISITES
        ),
        "artifacts": pins,
        "release_candidate_commit": COMMIT,
        "runtime_truth_sha256": _digest("runtime-truth"),
        "assembled_at": ASSEMBLED,
        "assembled_by": "operator",
        "reviewed_by": "reviewer",
        "deterministic_replay_verified": True,
        "no_sender_imports_observed": True,
        "sender_endpoints_enabled": False,
        "live_submissions_observed": 0,
    }
    values.update(overrides)
    return PR092ActualSoakManifest(**values)


def test_pr092_accepts_materialized_real_soak_without_live_enablement(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)

    result = evaluate_pr092_actual_shadow_soak(manifest, artifact_root=tmp_path)

    assert result.state is PR092ActualSoakState.READY_FOR_MANUAL_RELEASE_REVIEW
    assert result.release_evidence_ready is True
    assert result.live_allowed is False
    assert result.blockers == ()
    assert result.duration_seconds >= 72 * 60 * 60
    assert result.artifact_check.passed is True
    assert len(result.artifact_check.checked_paths) == len(REQUIRED_PR092_ARTIFACTS)


def test_pr092_fails_closed_when_artifact_files_are_not_materialized(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)

    result = evaluate_pr092_actual_shadow_soak(manifest)

    assert result.state is PR092ActualSoakState.BLOCKED
    assert "MATERIALIZED_ARTIFACT_CHECK_NOT_RUN" in result.blockers
    assert result.live_allowed is False


def test_pr092_rejects_recorded_fixture_soak(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    recorded_soak = replace(manifest.soak, environment=SoakEnvironment.RECORDED)
    manifest = replace(manifest, soak=recorded_soak)

    result = evaluate_pr092_actual_shadow_soak(manifest, artifact_root=tmp_path)

    assert result.state is PR092ActualSoakState.BLOCKED
    assert "RECORDED_FIXTURE_NOT_ACTUAL_SOAK" in result.blockers
    assert result.live_allowed is False


def test_pr092_requires_pr089_to_pr091_prerequisites(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        prerequisites=tuple(
            _prerequisite(name)
            for name in REQUIRED_PR092_PREREQUISITES
            if not name.startswith("pr091.")
        ),
    )

    result = evaluate_pr092_actual_shadow_soak(manifest, artifact_root=tmp_path)

    assert result.state is PR092ActualSoakState.BLOCKED
    assert (
        "PREREQUISITE_MISSING:pr091.security-sbom-provenance-chaos-artifacts"
        in result.blockers
    )


def test_pr092_rejects_live_or_sender_observation(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        deterministic_replay_verified=False,
        no_sender_imports_observed=False,
        sender_endpoints_enabled=True,
        live_submissions_observed=1,
    )

    result = evaluate_pr092_actual_shadow_soak(manifest, artifact_root=tmp_path)

    assert "DETERMINISTIC_REPLAY_NOT_VERIFIED" in result.blockers
    assert "SENDER_IMPORT_OBSERVED_DURING_SOAK" in result.blockers
    assert "SENDER_ENDPOINT_ENABLED_DURING_SOAK" in result.blockers
    assert "LIVE_SUBMISSIONS_OBSERVED" in result.blockers
    assert result.live_allowed is False


def test_pr092_rejects_fabricated_constant_hashes(tmp_path: Path) -> None:
    with pytest.raises(ShadowSoakError, match="low-entropy fixture sha256"):
        PR092SoakArtifactPin(
            kind=PR092ActualSoakArtifactKind.RAW_EVENTS,
            path="artifacts/shadow-soak/pr092/run-20260701/raw-events.json",
            sha256="a" * 64,
            size_bytes=1,
            produced_at=END,
            producer="pr092-shadow-runner",
        )


def test_pr092_detects_materialized_hash_mismatch(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    first = manifest.artifacts[0]
    changed = replace(first, sha256=_digest("different-real-digest"))
    manifest = replace(manifest, artifacts=(changed, *manifest.artifacts[1:]))

    result = evaluate_pr092_actual_shadow_soak(manifest, artifact_root=tmp_path)

    assert result.state is PR092ActualSoakState.BLOCKED
    assert f"ARTIFACT_HASH_MISMATCH:{changed.path}" in result.blockers
    assert result.live_allowed is False
