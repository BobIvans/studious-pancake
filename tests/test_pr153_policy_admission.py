from __future__ import annotations

from dataclasses import replace

import pytest

from src.pr153_policy_admission import (
    DISABLED_ROLE,
    EXECUTABLE_ROLE,
    PR153PolicyAdmissionError,
    PR153ReadinessState,
    ImmutablePolicyBundle,
    ProgramAttestation,
    ProviderAdmissionEvidence,
    assert_no_false_provider_promotion,
    evaluate_pr153_policy_admission,
)

pytestmark = pytest.mark.unit

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
GIT_SHA = "1" * 40


def _attestation(**overrides: object) -> ProgramAttestation:
    values: dict[str, object] = {
        "program_id": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        "cluster_genesis_hash": SHA_A,
        "executable_hash": SHA_B,
        "loader": "bpf-upgradeable-loader",
        "deployment_slot": 123,
        "executable": True,
        "upgrade_authority_revoked": True,
        "evidence_sha256": SHA_C,
        "stale": False,
    }
    values.update(overrides)
    return ProgramAttestation(**values)  # type: ignore[arg-type]


def _provider(**overrides: object) -> ProviderAdmissionEvidence:
    values: dict[str, object] = {
        "provider": "jupiter",
        "requested_role": EXECUTABLE_ROLE,
        "local_contract_active": True,
        "contract_execution_allowed": True,
        "drift_free": True,
        "credentials_present": True,
        "credentialed_api_conformance": True,
        "execution_composition_conformance": True,
        "promotion_evidence": True,
        "operator_approved": True,
        "program_attestations": (_attestation(),),
        "required_credentials": ("JUPITER_API_KEY",),
        "missing_credentials": (),
        "diagnostics": (),
    }
    values.update(overrides)
    return ProviderAdmissionEvidence(**values)  # type: ignore[arg-type]


def _bundle(**overrides: object) -> ImmutablePolicyBundle:
    values: dict[str, object] = {
        "policy_version": "policy-2026-07-22",
        "build_commit": GIT_SHA,
        "cluster_genesis_hash": SHA_A,
        "providers": (_provider(),),
        "operator_approval_id": "approval-153",
        "runtime_truth_sha256": SHA_D,
    }
    values.update(overrides)
    return ImmutablePolicyBundle(**values)  # type: ignore[arg-type]


def test_verified_provider_reaches_review_ready_but_never_live() -> None:
    result = evaluate_pr153_policy_admission(_bundle())

    assert result.state is PR153ReadinessState.READY_FOR_POLICY_REVIEW
    assert result.ready_for_policy_review is True
    assert result.runtime_live_enabled is False
    assert result.supported_command_can_submit is False
    assert result.provider_decisions[0].admitted_role == EXECUTABLE_ROLE
    assert result.provider_decisions[0].executable is True
    assert_no_false_provider_promotion(result)


def test_execution_allowed_false_never_promotes_executable() -> None:
    provider = _provider(contract_execution_allowed=False)
    result = evaluate_pr153_policy_admission(_bundle(providers=(provider,)))

    assert result.state is PR153ReadinessState.BLOCKED
    assert result.provider_decisions[0].admitted_role == DISABLED_ROLE
    assert result.provider_decisions[0].executable is False
    assert "jupiter:contract_execution_allowed" in result.blockers
    assert_no_false_provider_promotion(result)


def test_missing_credentials_block_execution_role() -> None:
    provider = _provider(
        credentials_present=False,
        missing_credentials=("JUPITER_API_KEY",),
    )
    result = evaluate_pr153_policy_admission(_bundle(providers=(provider,)))

    assert result.provider_decisions[0].admitted_role == DISABLED_ROLE
    assert "jupiter:credentials_present" in result.blockers
    assert "jupiter:missing-credential:JUPITER_API_KEY" in result.blockers


def test_stale_program_attestation_blocks_execution() -> None:
    provider = _provider(program_attestations=(_attestation(stale=True),))
    result = evaluate_pr153_policy_admission(_bundle(providers=(provider,)))

    assert result.provider_decisions[0].admitted_role == DISABLED_ROLE
    assert "jupiter:program_attestations_verified" in result.blockers
    assert any("program-attestation-stale" in item for item in result.blockers)


def test_quote_only_provider_does_not_block_review_when_not_executable() -> None:
    provider = _provider(
        requested_role="quote-only",
        contract_execution_allowed=False,
        credentials_present=False,
        missing_credentials=("OPTIONAL_KEY",),
    )
    result = evaluate_pr153_policy_admission(
        _bundle(providers=(provider, _provider(provider="okx")))
    )

    assert result.state is PR153ReadinessState.READY_FOR_POLICY_REVIEW
    assert result.provider_decisions[0].admitted_role == "quote-only"
    assert "jupiter:contract_execution_allowed" in result.warnings
    assert not result.blockers


def test_bundle_rejects_cross_cluster_attestation() -> None:
    provider = _provider(
        program_attestations=(_attestation(cluster_genesis_hash="e" * 64),)
    )

    with pytest.raises(PR153PolicyAdmissionError, match="cluster"):
        _bundle(providers=(provider,))


def test_bundle_cannot_enable_live() -> None:
    with pytest.raises(PR153PolicyAdmissionError, match="cannot enable live"):
        _bundle(live_enabled=True)


def test_placeholder_hashes_are_rejected() -> None:
    with pytest.raises(PR153PolicyAdmissionError, match="non-placeholder sha256"):
        _attestation(executable_hash="0" * 64)


def test_duplicate_provider_names_are_rejected() -> None:
    provider = _provider()

    with pytest.raises(PR153PolicyAdmissionError, match="unique"):
        _bundle(providers=(provider, replace(provider)))
