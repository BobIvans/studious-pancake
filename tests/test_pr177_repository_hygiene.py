from __future__ import annotations

from dataclasses import replace

import pytest

from src.repository_hygiene import (
    ArtifactClass,
    ArtifactLifecycle,
    DomainOwnerRecord,
    DomainOwnerState,
    GeneratedArtifactManifest,
    QuarantineMetadata,
    ArtifactRecord,
    RepositorySurfaceBudget,
    RepositorySurfaceCounts,
    SupersessionMetadata,
    PR177HygieneError,
    assert_repository_hygiene,
    evaluate_repository_hygiene,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _supersession(status: ArtifactLifecycle = ArtifactLifecycle.ACTIVE) -> SupersessionMetadata:
    return SupersessionMetadata(
        canonical_id="readiness.canonical-doc",
        owner="platform",
        status=status,
        superseded_by="readiness.current-doc" if status != ArtifactLifecycle.ACTIVE else None,
        removal_release="release-1" if status == ArtifactLifecycle.SCHEDULED_FOR_REMOVAL else None,
    )


def _generated() -> GeneratedArtifactManifest:
    return GeneratedArtifactManifest(
        generator_command="python scripts/generate_inventory.py",
        generator_version="1.0.0",
        source_input_hashes=(HASH_A,),
        deterministic_hash=HASH_B,
        freshness_expires_at="2026-08-22T00:00:00Z",
        verification_test="tests/test_inventory_generation.py::test_reproducible",
    )


def _record(**overrides) -> ArtifactRecord:
    base = ArtifactRecord(
        path="src/canonical_owner.py",
        artifact_class=ArtifactClass.SOURCE,
        lifecycle=ArtifactLifecycle.ACTIVE,
        domain_id="runtime.canonical-owner",
        included_in_production_wheel=True,
    )
    return replace(base, **overrides)


def _owner(domain_id: str = "runtime.canonical-owner", path: str = "src/canonical_owner.py") -> DomainOwnerRecord:
    return DomainOwnerRecord(
        domain_id=domain_id,
        owner_path=path,
        state=DomainOwnerState.PRODUCTION_ACTIVE,
        owner_hash=HASH_A,
    )


def _counts(**overrides) -> RepositorySurfaceCounts:
    base = RepositorySurfaceCounts(
        production_python_modules=20,
        wheel_files=80,
        test_modules=50,
        docs_gate_files=12,
        duplicate_domain_count=0,
    )
    return replace(base, **overrides)


def _budget(**overrides) -> RepositorySurfaceBudget:
    base = RepositorySurfaceBudget(
        max_production_python_modules=100,
        max_wheel_files=200,
        max_test_modules=200,
        max_docs_gate_files=50,
    )
    return replace(base, **overrides)


def _evaluate(*records: ArtifactRecord, owners=None, counts=None, release_branch=False):
    return evaluate_repository_hygiene(
        artifacts=records or (_record(),),
        domain_owners=owners if owners is not None else (_owner(),),
        surface_counts=counts if counts is not None else _counts(),
        surface_budget=_budget(),
        release_branch=release_branch,
    )


def test_clean_minimal_inventory_is_hygiene_ok() -> None:
    result = _evaluate(_record())

    assert result.hygiene_ok is True
    assert result.production_wheel_clean is True
    assert result.release_branch_clean is True
    assert result.result_hash


def test_tmp_accidental_marker_is_blocker() -> None:
    result = _evaluate(
        _record(
            path="tmp_accidental_pr_marker_168",
            artifact_class=ArtifactClass.TEMPORARY,
            root_file=True,
            empty_file=True,
            included_in_production_wheel=False,
            domain_id=None,
        )
    )

    assert "TEMPORARY_OR_ACCIDENTAL_MARKER" in result.blockers
    assert "EMPTY_UNEXPLAINED_ROOT_FILE" in result.blockers
    with pytest.raises(PR177HygieneError):
        assert_repository_hygiene(result)


def test_caches_and_local_databases_are_blocked() -> None:
    result = _evaluate(
        _record(path="src/__pycache__/x.cpython-311.pyc", domain_id=None),
        _record(path="paper_trading.db", artifact_class=ArtifactClass.TEMPORARY, domain_id=None),
    )

    assert "CACHE_OR_LOCAL_STATE_ARTIFACT" in result.blockers


def test_generated_artifact_requires_reproducible_manifest() -> None:
    result = _evaluate(
        _record(
            path="src/resources/production_debt.generated.json",
            artifact_class=ArtifactClass.GENERATED,
            generated=None,
            domain_id="readiness.generated-inventory",
        )
    )

    assert "GENERATED_MANIFEST_MISSING" in result.blockers
    assert result.generated_artifacts_reproducible is False


def test_generated_artifact_accepts_valid_manifest() -> None:
    result = _evaluate(
        _record(
            path="src/resources/production_debt.generated.json",
            artifact_class=ArtifactClass.GENERATED,
            generated=_generated(),
            domain_id="readiness.generated-inventory",
        )
    )

    assert "GENERATED_MANIFEST_MISSING" not in result.blockers
    assert result.generated_artifacts_reproducible is True


def test_generated_artifact_rejects_random_non_digest() -> None:
    result = _evaluate(
        _record(
            path="src/resources/report.json",
            artifact_class=ArtifactClass.GENERATED,
            generated=replace(_generated(), deterministic_hash="not-a-sha"),
            domain_id="readiness.generated-report",
        )
    )

    assert "GENERATED_DETERMINISTIC_HASH_INVALID" in result.blockers


def test_docs_and_evidence_need_supersession_metadata() -> None:
    result = _evaluate(
        _record(
            path="docs/pr149_old_truth_plane.md",
            artifact_class=ArtifactClass.DOCUMENTATION,
            lifecycle=ArtifactLifecycle.DEPRECATED,
            included_in_production_wheel=False,
            supersession=None,
            domain_id="docs.readiness-truth",
        )
    )

    assert "SUPERSESSION_METADATA_MISSING" in result.blockers
    assert result.supersession_metadata_complete is False


def test_deprecated_doc_requires_superseded_by_target() -> None:
    result = _evaluate(
        _record(
            path="docs/pr149_old_truth_plane.md",
            artifact_class=ArtifactClass.DOCUMENTATION,
            lifecycle=ArtifactLifecycle.DEPRECATED,
            included_in_production_wheel=False,
            supersession=SupersessionMetadata(
                canonical_id="docs.readiness-truth",
                owner="platform",
                status=ArtifactLifecycle.DEPRECATED,
            ),
            domain_id="docs.readiness-truth",
        )
    )

    assert "SUPERSESSION_TARGET_MISSING" in result.blockers


def test_duplicate_production_domain_owner_is_blocker() -> None:
    result = _evaluate(
        _record(),
        owners=(
            _owner(path="src/production_debt.py"),
            _owner(path="src/production_debt_pr149.py"),
        ),
    )

    assert "DUPLICATE_PRODUCTION_DOMAIN_OWNER" in result.blockers
    assert result.duplicate_domains_blocked is False


def test_quarantined_artifact_requires_owner_and_removal_lifecycle() -> None:
    result = _evaluate(
        _record(
            path="src/legacy_tx_builder.py",
            artifact_class=ArtifactClass.SOURCE,
            lifecycle=ArtifactLifecycle.QUARANTINED,
            included_in_production_wheel=False,
            quarantine=None,
            domain_id="execution.legacy-builder",
        )
    )

    assert "QUARANTINE_METADATA_MISSING" in result.blockers
    assert result.quarantine_lifecycle_complete is False


def test_quarantined_artifact_cannot_enter_production_wheel() -> None:
    result = _evaluate(
        _record(
            path="src/legacy_tx_builder.py",
            artifact_class=ArtifactClass.SOURCE,
            lifecycle=ArtifactLifecycle.QUARANTINED,
            included_in_production_wheel=True,
            quarantine=QuarantineMetadata(
                owner="execution",
                reason="legacy unsafe tx construction",
                removal_release="release-2",
                removal_owner="execution",
            ),
            domain_id="execution.legacy-builder",
        )
    )

    assert "NON_ACTIVE_ARTIFACT_IN_PRODUCTION_WHEEL" in result.blockers


def test_temporary_artifact_cannot_enter_production_wheel() -> None:
    result = _evaluate(
        _record(
            path="scratch/report.tmp",
            artifact_class=ArtifactClass.TEMPORARY,
            included_in_production_wheel=True,
            domain_id=None,
        )
    )

    assert "TEMPORARY_IN_PRODUCTION_WHEEL" in result.blockers
    assert result.production_wheel_clean is False


def test_evidence_requires_expiry_and_non_stale_state() -> None:
    result = _evaluate(
        _record(
            path="evidence/provider_snapshot.json",
            artifact_class=ArtifactClass.EVIDENCE,
            included_in_production_wheel=False,
            supersession=_supersession(),
            evidence_expires_at=None,
            stale=True,
            domain_id="evidence.provider-snapshot",
        )
    )

    assert "EVIDENCE_EXPIRY_MISSING" in result.blockers
    assert "STALE_EVIDENCE_ARTIFACT" in result.blockers


def test_release_branch_rejects_stale_evidence_and_temp_files() -> None:
    result = _evaluate(
        _record(
            path="evidence/stale.json",
            artifact_class=ArtifactClass.EVIDENCE,
            included_in_production_wheel=False,
            supersession=_supersession(),
            evidence_expires_at="2026-07-01T00:00:00Z",
            stale=True,
            domain_id="evidence.stale",
        ),
        _record(
            path="tmp_local_note",
            artifact_class=ArtifactClass.TEMPORARY,
            included_in_production_wheel=False,
            domain_id=None,
        ),
        release_branch=True,
    )

    assert "RELEASE_BRANCH_STALE_EVIDENCE" in result.blockers
    assert "RELEASE_BRANCH_TEMPORARY_OR_FORBIDDEN" in result.blockers
    assert result.release_branch_clean is False


def test_surface_budget_exceeding_thresholds_is_blocker() -> None:
    result = evaluate_repository_hygiene(
        artifacts=(_record(),),
        domain_owners=(_owner(),),
        surface_counts=_counts(production_python_modules=101, duplicate_domain_count=1),
        surface_budget=_budget(max_production_python_modules=100, max_duplicate_domain_count=0),
    )

    assert "SURFACE_BUDGET_PRODUCTION_MODULES_EXCEEDED" in result.blockers
    assert "SURFACE_BUDGET_DUPLICATE_DOMAINS_EXCEEDED" in result.blockers
    assert result.surface_budget_ok is False


def test_domain_id_cannot_use_pr_number_identity() -> None:
    with pytest.raises(PR177HygieneError):
        _evaluate(_record(domain_id="pr-177"))


def test_result_hash_is_deterministic() -> None:
    first = _evaluate(_record())
    second = _evaluate(_record())

    assert first.result_hash == second.result_hash
