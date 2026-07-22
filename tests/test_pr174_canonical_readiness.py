from __future__ import annotations

from dataclasses import replace

import pytest

from src.canonical_readiness import (
    ArchitectureBindingProof,
    BlockingMode,
    EvidenceState,
    ImplementationState,
    LegacyTruthReport,
    PackageBindingProof,
    PR174ReadinessError,
    RequirementRecord,
    assert_single_authoritative_readiness,
    evaluate_canonical_readiness,
    owner_map_as_requirements,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def _architecture(**overrides):
    values = dict(
        cli_entrypoint="flashloan-bot readiness evaluate",
        composition_root="src.cli",
        owner_module="src.canonical.policy",
        owner_symbol="evaluate",
        cli_imports_composition=True,
        composition_imports_owner=True,
        runtime_uses_owner=True,
        isolated_gate_only=False,
        proof_hash=HASH_C,
    )
    values.update(overrides)
    return ArchitectureBindingProof(**values)


def _package(**overrides):
    values = dict(
        distribution_name="flashloan-bot",
        distribution_version="0.0.0",
        owner_module="src.canonical.policy",
        source_digest=HASH_A,
        wheel_digest=HASH_B,
        active_import_owner="src.canonical.policy",
        source_wheel_parity=True,
    )
    values.update(overrides)
    return PackageBindingProof(**values)


def _requirement(**overrides):
    values = dict(
        domain_id="policy.admission",
        title="Canonical policy admission owner",
        owner_module="src.canonical.policy",
        blocking_mode=BlockingMode.P0_BLOCKS_PAPER_AND_LIVE,
        implementation_state=ImplementationState.REVIEW_READY,
        evidence_state=EvidenceState.VERIFIED_CURRENT,
        evidence_producer="scripts.produce_policy_evidence",
        evidence_verifier="scripts.verify_policy_evidence",
        architecture=_architecture(),
        package=_package(),
    )
    values.update(overrides)
    return RequirementRecord(**values)


def test_ready_state_requires_single_authoritative_owner() -> None:
    state = evaluate_canonical_readiness(
        [_requirement()],
        legacy_reports=[
            LegacyTruthReport(
                system_id="canonical",
                paper_ready=True,
                live_ready=True,
                production_ready=True,
                report_hash=HASH_D,
            )
        ],
        evaluated_release="release-1",
    )

    assert state.paper_ready is True
    assert state.live_ready is True
    assert state.production_ready is True
    assert state.global_blockers == ()
    assert state.requirement_blockers == {}
    assert state.state_hash == evaluate_canonical_readiness(
        [_requirement()],
        legacy_reports=[
            LegacyTruthReport(
                system_id="canonical",
                paper_ready=True,
                live_ready=True,
                production_ready=True,
                report_hash=HASH_D,
            )
        ],
        evaluated_release="release-1",
    ).state_hash


def test_pr_number_domain_id_is_rejected() -> None:
    with pytest.raises(PR174ReadinessError, match="PR number"):
        evaluate_canonical_readiness(
            [_requirement(domain_id="pr174.policy")],
            evaluated_release="release-1",
        )


def test_duplicate_active_requirement_fails_global_readiness() -> None:
    duplicate = _requirement(
        owner_module="src.other_policy",
        architecture=_architecture(owner_module="src.other_policy"),
        package=_package(owner_module="src.other_policy", active_import_owner="src.other_policy"),
    )

    state = evaluate_canonical_readiness(
        [_requirement(), duplicate],
        evaluated_release="release-1",
    )

    assert state.paper_ready is False
    assert "DUPLICATE_ACTIVE_REQUIREMENT:policy.admission" in state.global_blockers
    assert "DUPLICATE_ACTIVE_OWNER:policy.admission" in state.global_blockers


def test_legacy_truth_planes_cannot_coexist() -> None:
    reports = [
        LegacyTruthReport(
            system_id="production_debt.py",
            paper_ready=False,
            live_ready=False,
            production_ready=False,
            report_hash=HASH_A,
        ),
        LegacyTruthReport(
            system_id="production_debt_pr149.py",
            paper_ready=True,
            live_ready=False,
            production_ready=False,
            report_hash=HASH_B,
        ),
    ]

    state = evaluate_canonical_readiness(
        [_requirement()],
        legacy_reports=reports,
        evaluated_release="release-1",
    )

    assert "MULTIPLE_LEGACY_TRUTH_PLANES_PRESENT" in state.global_blockers
    assert "LEGACY_READINESS_REPORTS_DIVERGE" in state.global_blockers


def test_isolated_gate_cannot_close_integration_requirement() -> None:
    req = _requirement(
        implementation_state=ImplementationState.IMPLEMENTED_ISOLATED,
        architecture=_architecture(isolated_gate_only=True),
    )

    state = evaluate_canonical_readiness([req], evaluated_release="release-1")

    assert state.paper_ready is False
    assert "ISOLATED_GATE_ONLY_CANNOT_CLOSE_INTEGRATION" in state.requirement_blockers[
        "policy.admission"
    ]


def test_missing_runtime_binding_blocks_implemented_requirement() -> None:
    req = _requirement(
        architecture=_architecture(
            cli_imports_composition=False,
            composition_imports_owner=False,
            runtime_uses_owner=False,
        )
    )

    state = evaluate_canonical_readiness([req], evaluated_release="release-1")

    blockers = state.requirement_blockers["policy.admission"]
    assert "CLI_DOES_NOT_IMPORT_COMPOSITION_ROOT" in blockers
    assert "COMPOSITION_DOES_NOT_IMPORT_OWNER" in blockers
    assert "RUNTIME_DOES_NOT_USE_OWNER" in blockers


def test_source_wheel_parity_is_required() -> None:
    req = _requirement(package=_package(source_wheel_parity=False))

    state = evaluate_canonical_readiness([req], evaluated_release="release-1")

    assert state.paper_ready is False
    assert "SOURCE_WHEEL_PARITY_NOT_PROVEN" in state.requirement_blockers[
        "policy.admission"
    ]


def test_descriptor_only_evidence_cannot_close_blocking_requirement() -> None:
    req = _requirement(evidence_state=EvidenceState.DESCRIPTOR_ONLY)

    state = evaluate_canonical_readiness([req], evaluated_release="release-1")

    assert "DESCRIPTOR_ONLY_CANNOT_CLOSE_READINESS" in state.requirement_blockers[
        "policy.admission"
    ]


def test_superseded_requirement_needs_removal_criteria() -> None:
    req = _requirement(
        implementation_state=ImplementationState.SUPERSEDED,
        superseded_by="policy.admission.v2",
    )

    state = evaluate_canonical_readiness([req], evaluated_release="release-1")

    assert "SUPERSEDED_REQUIREMENT_NEEDS_REMOVAL_CRITERIA" in state.requirement_blockers[
        "policy.admission"
    ]
    assert "SUPERSEDING_REQUIREMENT_MISSING:policy.admission" in state.global_blockers


def test_assert_single_authoritative_readiness_raises_for_open_blockers() -> None:
    state = evaluate_canonical_readiness(
        [_requirement(evidence_state=EvidenceState.MISSING)],
        evaluated_release="release-1",
    )

    with pytest.raises(PR174ReadinessError, match="open blockers"):
        assert_single_authoritative_readiness(state)


def test_owner_map_defaults_to_fail_closed_until_active_binding() -> None:
    requirements = owner_map_as_requirements(
        source_digest=HASH_A,
        wheel_digest=HASH_B,
        proof_hash=HASH_C,
    )

    state = evaluate_canonical_readiness(requirements, evaluated_release="release-1")

    assert len(requirements) >= 5
    assert state.paper_ready is False
    assert state.live_ready is False
    assert all(requirement.domain_id for requirement in requirements)
    assert "production.debt" in state.requirement_blockers


def test_producer_and_verifier_must_be_distinct() -> None:
    with pytest.raises(PR174ReadinessError, match="producer and verifier"):
        evaluate_canonical_readiness(
            [_requirement(evidence_verifier="scripts.produce_policy_evidence")],
            evaluated_release="release-1",
        )


def test_live_approval_requires_verified_current_evidence() -> None:
    req = _requirement(
        implementation_state=ImplementationState.LIVE_APPROVED,
        evidence_state=EvidenceState.PRODUCED_UNVERIFIED,
    )

    state = evaluate_canonical_readiness([req], evaluated_release="release-1")

    blockers = state.requirement_blockers["policy.admission"]
    assert "LIVE_APPROVAL_REQUIRES_CURRENT_VERIFIED_EVIDENCE" in blockers
    assert "LIVE_APPROVAL_HAS_OPEN_BLOCKERS" in blockers
