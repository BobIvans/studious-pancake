from __future__ import annotations

from pathlib import Path

import pytest

from src.release_gate.agg01_foundation import (
    AGG01_REQUIRED_NF,
    AdapterContract,
    Agg01ContractError,
    BoundaryADR,
    BoundaryMode,
    CommandResult,
    ConformanceVector,
    CoverageRow,
    DifferentialCase,
    EvidenceLevel,
    ImplementationStatus,
    IntegrationDecision,
    LicenseDecision,
    SupplyChainReview,
    UpstreamPin,
    VectorSet,
    build_hermetic_environment,
    build_reuse_admission,
    classify_evidence,
    close_baseline_map,
    freeze_snapshot,
    map_entrypoints,
    monitor_upstream_drift,
    open_campaign,
    record_campaign_baseline,
    reconcile_scope,
    run_differential_tests,
)

COMMIT = "0c4f216a62d62b20f6fb4ec4bbd0548cea58df65"
SHA_A = "a" * 64
SHA_B = "b" * 64


def _pin(
    blob: str = "9755520565f83dd2ee9f02bcc2651e193e669dcc",
) -> UpstreamPin:
    return UpstreamPin(
        repository="igneous-labs/slumlord",
        commit="5c5565cb106f5316a66df8ba616034a7810fa850",
        path="slumlord_interface/src/instructions.rs",
        symbol="borrow_ix",
        blob_sha=blob,
        artifact_sha256=None,
    )


def _passing_differential():
    return run_differential_tests((DifferentialCase("v1", SHA_A, SHA_A, SHA_A),))


def test_campaign_keeps_slumlord_required_and_marginfi_paused() -> None:
    campaign, index = open_campaign(
        repo_full_name="BobIvans/studious-pancake",
        repo_commit=COMMIT,
        spec_version="2026-09-20",
        requested_scope=AGG01_REQUIRED_NF,
        effect_policy="LOCAL_BUILD_TEST",
        campaign_id="agg01-test",
    )
    assert campaign.slumlord_required is True
    assert campaign.marginfi_paused is True
    assert index.records == ()


def test_snapshot_and_installed_entrypoint(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python=">=3.13,<3.14"\n'
        '[project.scripts]\nflashloan-bot="src.cli_pr189:main"\n',
        encoding="utf-8",
    )
    runtime = tmp_path / "src/runtime"
    runtime.mkdir(parents=True)
    (runtime / "runtime_entrypoint.py").write_text(
        "build_core_v1_composition()", encoding="utf-8"
    )
    first = freeze_snapshot(tmp_path, repo_commit=COMMIT, base_commit=COMMIT)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    second = freeze_snapshot(tmp_path, repo_commit=COMMIT, base_commit=COMMIT)
    assert first.digest != second.digest
    assert map_entrypoints(tmp_path).installed_reachable is True


def test_environment_contract_matches_python_313(
    repo_root: Path = Path("."),
) -> None:
    manifest = build_hermetic_environment(repo_root)
    assert manifest.supported is True
    assert manifest.lock_hashes


def test_unknown_evidence_does_not_auto_promote() -> None:
    record = classify_evidence("e1", EvidenceLevel.UNKNOWN, SHA_A, "test", 1)
    assert record.level is EvidenceLevel.UNKNOWN


def test_all_28_nf_rows_are_visible() -> None:
    rows = tuple(
        CoverageRow(
            nf,
            "AGG-01",
            IntegrationDecision.INTEGRATE,
            ImplementationStatus.IMPLEMENTED_OFFLINE,
        )
        for nf in AGG01_REQUIRED_NF
    )
    assert len(AGG01_REQUIRED_NF) == 28
    assert reconcile_scope(rows).missing == ()
    assert close_baseline_map(rows).items


def test_missing_nf_remains_a_blocker() -> None:
    queue = close_baseline_map(())
    assert {item.nf_id for item in queue.items} == set(AGG01_REQUIRED_NF)
    assert {item.blocker for item in queue.items} == {"MISSING_COVERAGE_ROW"}


def test_verified_reuse_requires_license_vectors_and_safe_boundary() -> None:
    vectors = VectorSet((ConformanceVector("v1", SHA_A, SHA_A),))
    admission = build_reuse_admission(
        upstream=_pin(),
        license=LicenseDecision(True, "MIT OR Apache-2.0", True, None),
        vectors=vectors,
        differential=_passing_differential(),
        supply_chain=SupplyChainReview(True, False, False, False),
        boundary=BoundaryADR(BoundaryMode.PORT_DIFF, True, False, False),
        adapter=AdapterContract(
            "slumlord", ("state",), ("unsigned_ix",), True, False, 1
        ),
    )
    assert len(admission.admission_digest) == 64


def test_unknown_license_or_hidden_effects_reject_reuse() -> None:
    vectors = VectorSet((ConformanceVector("v1", SHA_A, SHA_A),))
    common = dict(
        upstream=_pin(),
        vectors=vectors,
        differential=_passing_differential(),
        boundary=BoundaryADR(BoundaryMode.WRAP, True, False, False),
        adapter=AdapterContract("adapter", ("state",), ("out",), True, False, 1),
    )
    with pytest.raises(Agg01ContractError, match="permitted license"):
        build_reuse_admission(
            license=LicenseDecision(False, None, False, None),
            supply_chain=SupplyChainReview(True, False, False, False),
            **common,
        )
    with pytest.raises(Agg01ContractError, match="safe supply chain"):
        build_reuse_admission(
            license=LicenseDecision(True, "MIT", False, None),
            supply_chain=SupplyChainReview(True, True, False, False),
            **common,
        )


def test_differential_mismatch_is_not_hidden() -> None:
    with pytest.raises(Agg01ContractError, match="differential"):
        run_differential_tests((DifferentialCase("v1", SHA_A, SHA_A, SHA_B),))


def test_reuse_admission_binds_the_exact_vector_set() -> None:
    vectors = VectorSet((ConformanceVector("v2", SHA_A, SHA_A),))
    with pytest.raises(Agg01ContractError, match="does not bind vector set"):
        build_reuse_admission(
            upstream=_pin(),
            license=LicenseDecision(True, "MIT OR Apache-2.0", True, None),
            vectors=vectors,
            differential=_passing_differential(),
            supply_chain=SupplyChainReview(True, False, False, False),
            boundary=BoundaryADR(BoundaryMode.PORT_DIFF, True, False, False),
            adapter=AdapterContract(
                "slumlord", ("state",), ("unsigned_ix",), True, False, 1
            ),
        )


def test_reuse_admission_binds_vector_input_digest() -> None:
    vectors = VectorSet((ConformanceVector("v1", SHA_B, SHA_A),))
    with pytest.raises(Agg01ContractError, match="does not bind vector set"):
        build_reuse_admission(
            upstream=_pin(),
            license=LicenseDecision(True, "MIT OR Apache-2.0", True, None),
            vectors=vectors,
            differential=_passing_differential(),
            supply_chain=SupplyChainReview(True, False, False, False),
            boundary=BoundaryADR(BoundaryMode.PORT_DIFF, True, False, False),
            adapter=AdapterContract(
                "slumlord", ("state",), ("unsigned_ix",), True, False, 1
            ),
        )


def test_upstream_drift_and_unreachable_source_require_requalification() -> None:
    assert monitor_upstream_drift(_pin(SHA_A), _pin(SHA_B)).requalification_required
    missing = monitor_upstream_drift(_pin(), None)
    assert missing.source_reachable is False
    assert missing.requalification_required is True


def test_external_blocker_is_separate_from_offline_pass(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    snapshot = freeze_snapshot(tmp_path, repo_commit=COMMIT, base_commit=COMMIT)
    baseline = record_campaign_baseline(
        "agg01-test",
        snapshot,
        (CommandResult("flashloan-bot status", 0),),
        (CommandResult("pytest focused", 0, passed=3, failed=0),),
        "CORE_V1_BLOCKED_EXTERNAL",
    )
    assert baseline.first_blocking_stage == "CORE_V1_BLOCKED_EXTERNAL"
    assert baseline.offline_checks[0].exit_code == 0
