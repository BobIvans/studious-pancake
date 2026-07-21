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
from src.venues.pump import PumpContractManifest, PumpFamily
from src.venues.pump.pr096_shadow_promotion import (
    REQUIRED_PUMP_PR096_ARTIFACTS,
    PumpPR096ArtifactKind,
    PumpPR096ArtifactPin,
    PumpPR096FamilyEvidence,
    PumpPR096PromotionPackage,
    PumpPR096State,
    evaluate_pump_pr096_shadow_promotion,
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
    kind: PumpPR096ArtifactKind,
    seed: str,
    *,
    family: PumpFamily | None = None,
) -> PumpPR096ArtifactPin:
    family_part = f"{family.value}/" if family is not None else ""
    path = f"artifacts/pump/pr096/run-20260701/{family_part}{kind.value}.json"
    payload = (
        f"{{\"kind\":\"{kind.value}\",\"seed\":\"{seed}\","
        f"\"family\":\"{family.value if family else 'global'}\"}}\n"
    ).encode("utf-8")
    full_path = root / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(payload)
    return PumpPR096ArtifactPin(
        kind=kind,
        path=path,
        sha256=sha256(payload).hexdigest(),
        size_bytes=len(payload),
        produced_at=END,
        producer="pump-pr096-shadow-runner",
        family=family,
    )


def _metrics() -> ShadowSoakMetrics:
    return ShadowSoakMetrics(
        candidates_seen=16,
        candidates_simulated=12,
        candidates_rejected=4,
        paper_outcomes_written=8,
        outcomes_reconciled=8,
        reconciliation_mismatches=0,
        message_hash_mismatches=0,
        repayment_mismatches=0,
        ambiguous_outcomes=0,
        quota_exhaustions=0,
        provider_5xx_errors=0,
        rpc_errors=0,
        stale_data_rejections=2,
        stale_data_accepted=0,
        p50_latency_ms=90,
        p95_latency_ms=150,
        max_latency_ms=240,
        net_pnl_lamports=0,
    )


def _soak(pins: tuple[PumpPR096ArtifactPin, ...], environment: SoakEnvironment):
    by_kind = {pin.kind: pin for pin in pins if pin.family is None}
    artifacts = (
        SoakArtifactReference(
            path=by_kind[PumpPR096ArtifactKind.SEPARATE_SOAK_BUNDLE].path,
            sha256=by_kind[PumpPR096ArtifactKind.SEPARATE_SOAK_BUNDLE].sha256,
            kind=SoakArtifactKind.RAW_EVENTS,
            event_count=16,
        ),
        SoakArtifactReference(
            path=by_kind[PumpPR096ArtifactKind.RECONCILIATION].path,
            sha256=by_kind[PumpPR096ArtifactKind.RECONCILIATION].sha256,
            kind=SoakArtifactKind.REPLAY_CORPUS,
            event_count=16,
        ),
        SoakArtifactReference(
            path=by_kind[PumpPR096ArtifactKind.EXACT_SIMULATION].path,
            sha256=by_kind[PumpPR096ArtifactKind.EXACT_SIMULATION].sha256,
            kind=SoakArtifactKind.METRICS_REPORT,
            event_count=1,
        ),
        SoakArtifactReference(
            path=by_kind[PumpPR096ArtifactKind.OPERATOR_REVIEW].path,
            sha256=by_kind[PumpPR096ArtifactKind.OPERATOR_REVIEW].sha256,
            kind=SoakArtifactKind.OPERATOR_REVIEW,
            event_count=1,
        ),
    )
    return ShadowSoakEvidence(
        run_id="pump-pr096-shadow-promotion",
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
            corpus_events=16,
            replayed_events=16,
            deterministic_passed_events=16,
            deterministic_failed_events=0,
            corpus_sha256=by_kind[PumpPR096ArtifactKind.RECONCILIATION].sha256,
        ),
        artifacts=artifacts,
        operator="operator",
        human_reviewed=True,
        reviewer="reviewer",
        reviewed_at=REVIEWED,
        signed_by="release-key",
        signature_reference=by_kind[PumpPR096ArtifactKind.OPERATOR_REVIEW].path,
    )


def _family(family: PumpFamily) -> PumpPR096FamilyEvidence:
    return PumpPR096FamilyEvidence(
        family=family,
        official_source_url=(
            "https://github.com/pump-fun/pump-public-docs/tree/"
            "abcdef1234567890abcdef1234567890abcdef12"
        ),
        official_source_commit=COMMIT,
        idl_sha256=_digest(f"{family.value}:idl"),
        layout_vector_sha256=_digest(f"{family.value}:layout"),
        discriminator_vector_sha256=_digest(f"{family.value}:discriminators"),
        rpc_fixture_sha256=_digest(f"{family.value}:rpc"),
        exact_simulation_sha256=_digest(f"{family.value}:simulation"),
        reconciliation_sha256=_digest(f"{family.value}:reconciliation"),
        token_program_verified=True,
        token_2022_policy_verified=True,
        human_reviewed=True,
        reviewer="reviewer",
    )


def _manifest(root: Path, **overrides) -> PumpPR096PromotionPackage:
    manifest = PumpContractManifest.load()
    families = tuple(spec.family for spec in manifest.specs)
    pins = []
    for index, kind in enumerate(REQUIRED_PUMP_PR096_ARTIFACTS, start=1):
        pins.append(_write_pin(root, kind, f"global-{index}"))
    for family in families:
        for kind in (
            PumpPR096ArtifactKind.IDL,
            PumpPR096ArtifactKind.LAYOUT_VECTOR,
            PumpPR096ArtifactKind.DISCRIMINATOR_VECTOR,
            PumpPR096ArtifactKind.RPC_FIXTURE,
            PumpPR096ArtifactKind.EXACT_SIMULATION,
            PumpPR096ArtifactKind.RECONCILIATION,
        ):
            pins.append(
                _write_pin(root, kind, f"{family.value}:{kind.value}", family=family)
            )
    pin_tuple = tuple(pins)
    values = {
        "run_id": "pump-pr096-shadow-promotion",
        "release_candidate_commit": COMMIT,
        "families": tuple(_family(family) for family in families),
        "artifacts": pin_tuple,
        "soak": _soak(pin_tuple, SoakEnvironment.MAINNET_READ_ONLY),
        "assembled_at": ASSEMBLED,
        "assembled_by": "operator",
        "reviewed_by": "reviewer",
        "separate_soak_from_core_runtime": True,
        "deterministic_replay_verified": True,
        "no_sender_imports_observed": True,
        "sender_endpoints_enabled": False,
        "live_submissions_observed": 0,
    }
    values.update(overrides)
    return PumpPR096PromotionPackage(**values)


def test_pr096_accepts_materialized_pump_shadow_promotion_without_live(
    tmp_path: Path,
) -> None:
    package = _manifest(tmp_path)

    report = evaluate_pump_pr096_shadow_promotion(package, artifact_root=tmp_path)

    assert report.state is PumpPR096State.READY_FOR_MANUAL_SHADOW_REVIEW
    assert report.shadow_promotion_ready is True
    assert report.live_allowed is False
    assert report.blockers == ()
    assert report.required_families == len(package.families)
    assert report.artifact_check.passed is True


def test_pr096_fails_closed_when_artifacts_are_not_materialized(
    tmp_path: Path,
) -> None:
    package = _manifest(tmp_path)

    report = evaluate_pump_pr096_shadow_promotion(package)

    assert report.state is PumpPR096State.BLOCKED
    assert "PUMP_PR096_MATERIALIZED_ARTIFACT_CHECK_NOT_RUN" in report.blockers
    assert report.live_allowed is False


def test_pr096_rejects_recorded_fixture_soak(tmp_path: Path) -> None:
    package = _manifest(tmp_path)
    package = replace(
        package, soak=replace(package.soak, environment=SoakEnvironment.RECORDED)
    )

    report = evaluate_pump_pr096_shadow_promotion(package, artifact_root=tmp_path)

    assert report.state is PumpPR096State.BLOCKED
    assert "PUMP_PR096_RECORDED_FIXTURE_NOT_ALLOWED" in report.blockers
    assert report.live_allowed is False


def test_pr096_requires_every_manifest_family(tmp_path: Path) -> None:
    package = _manifest(tmp_path, families=(_family(PumpFamily.BONDING_CURVE),))

    report = evaluate_pump_pr096_shadow_promotion(package, artifact_root=tmp_path)

    assert report.state is PumpPR096State.BLOCKED
    assert "PUMP_FAMILY_EVIDENCE_MISSING:pumpswap" in report.blockers


def test_pr096_rejects_sender_live_and_unreviewed_token_policy(
    tmp_path: Path,
) -> None:
    family = replace(
        _family(PumpFamily.BONDING_CURVE),
        token_2022_policy_verified=False,
        human_reviewed=False,
    )
    package = _manifest(
        tmp_path,
        families=(family, _family(PumpFamily.PUMPSWAP)),
        separate_soak_from_core_runtime=False,
        deterministic_replay_verified=False,
        no_sender_imports_observed=False,
        sender_endpoints_enabled=True,
        live_submissions_observed=1,
    )

    report = evaluate_pump_pr096_shadow_promotion(package, artifact_root=tmp_path)

    assert "PUMP_TOKEN_2022_POLICY_NOT_VERIFIED:bonding_curve" in report.blockers
    assert "PUMP_FAMILY_NOT_REVIEWED:bonding_curve" in report.blockers
    assert "PUMP_PR096_SEPARATE_SOAK_REQUIRED" in report.blockers
    assert "PUMP_PR096_DETERMINISTIC_REPLAY_NOT_VERIFIED" in report.blockers
    assert "PUMP_PR096_SENDER_IMPORT_OBSERVED" in report.blockers
    assert "PUMP_PR096_SENDER_ENDPOINT_ENABLED" in report.blockers
    assert "PUMP_PR096_LIVE_SUBMISSIONS_OBSERVED" in report.blockers
    assert report.live_allowed is False


def test_pr096_rejects_low_entropy_hashes(tmp_path: Path) -> None:
    with pytest.raises(ShadowSoakError, match="low-entropy fixture sha256"):
        PumpPR096ArtifactPin(
            kind=PumpPR096ArtifactKind.IDL,
            path="artifacts/pump/pr096/run-20260701/idl.json",
            sha256="a" * 64,
            size_bytes=1,
            produced_at=END,
            producer="pump-pr096-shadow-runner",
        )


def test_pr096_detects_hash_mismatch(tmp_path: Path) -> None:
    package = _manifest(tmp_path)
    changed = replace(package.artifacts[0], sha256=_digest("different"))
    package = replace(package, artifacts=(changed, *package.artifacts[1:]))

    report = evaluate_pump_pr096_shadow_promotion(package, artifact_root=tmp_path)

    assert report.state is PumpPR096State.BLOCKED
    assert f"PUMP_PR096_ARTIFACT_HASH_MISMATCH:{changed.path}" in report.blockers
    assert report.live_allowed is False
