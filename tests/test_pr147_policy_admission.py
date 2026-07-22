from __future__ import annotations

import pytest

from src.policy_admission_pr147 import (
    ADMISSION_DECISION_DOMAIN,
    POLICY_BUNDLE_DOMAIN,
    AdmittedProviderRole,
    HashReference,
    ImmutablePolicyBundle,
    MintAttestation,
    PolicyAdmissionError,
    PolicyRuntimeTruth,
    ProgramAttestation,
    ProviderAdmissionDecision,
    ProviderPolicyEvidence,
    RequestedProviderRole,
    domain_hash,
    evaluate_provider_admission,
    require_domain,
)

JUPITER_PROGRAM = "Jupiter1111111111111111111111111111111111"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def _hash(label: str) -> str:
    return domain_hash("test/pr147", {"label": label})


def _bundle() -> ImmutablePolicyBundle:
    return ImmutablePolicyBundle(
        cluster_genesis="solana-mainnet-beta",
        runtime_config_hash=_hash("runtime"),
        secret_locator_hash=_hash("secret-locators"),
        provider_contracts_hash=_hash("provider-contracts"),
        credential_availability_hash=_hash("credentials"),
        program_attestations_hash=_hash("programs"),
        asset_mint_registry_hash=_hash("mints"),
        freshness_policy_hash=_hash("freshness"),
        build_release_hash=_hash("build"),
        operator_approval_hash=_hash("approval"),
    )


def _program(*, stale: bool = False, executable: bool = True) -> ProgramAttestation:
    return ProgramAttestation(
        program_id=JUPITER_PROGRAM,
        cluster_genesis="solana-mainnet-beta",
        executable=executable,
        deployment_slot=123,
        programdata_hash=_hash("programdata"),
        upgrade_authority=None,
        evidence_hash=_hash("program-evidence"),
        stale=stale,
    )


def _evidence(**overrides: object) -> ProviderPolicyEvidence:
    values: dict[str, object] = {
        "provider": "jupiter",
        "requested_role": RequestedProviderRole.EXECUTABLE,
        "contract_id": "jupiter.swap-v2-build",
        "local_contract_active": True,
        "contract_execution_allowed": True,
        "credentials_present": True,
        "credentialed_api_conformance": True,
        "execution_composition_conformance": True,
        "promotion_evidence": True,
        "current_policy_approval": True,
        "no_drift": True,
        "evidence_age_slots": 3,
        "max_evidence_age_slots": 10,
        "program_attestations": (_program(),),
        "requires_on_chain_attestation": True,
    }
    values.update(overrides)
    return ProviderPolicyEvidence(**values)  # type: ignore[arg-type]


def test_pr147_complete_evidence_admits_executable_provider() -> None:
    decision = evaluate_provider_admission(_bundle(), _evidence())

    assert decision.admitted_role is AdmittedProviderRole.EXECUTABLE
    assert decision.execution_allowed is True
    assert decision.request_ready is True
    assert decision.startup_ready is True
    assert decision.reasons == ()
    assert len(decision.decision_hash) == 64


def test_pr147_contract_execution_false_cannot_be_executable() -> None:
    decision = evaluate_provider_admission(
        _bundle(),
        _evidence(contract_execution_allowed=False),
    )

    assert decision.admitted_role is AdmittedProviderRole.DISCOVERY_ONLY
    assert decision.execution_allowed is False
    assert "contract-execution-denied" in decision.reasons


def test_pr147_missing_credential_cannot_report_startup_ready() -> None:
    decision = evaluate_provider_admission(
        _bundle(),
        _evidence(credentials_present=False),
    )

    assert decision.admitted_role is AdmittedProviderRole.DISABLED
    assert decision.request_ready is False
    assert decision.startup_ready is False
    assert "missing-credentials" in decision.reasons


def test_pr147_stale_program_attestation_blocks_paper_ready() -> None:
    decision = evaluate_provider_admission(
        _bundle(),
        _evidence(program_attestations=(_program(stale=True),)),
    )
    mint = MintAttestation(
        mint=TOKEN_2022,
        owner_program_id=TOKEN_2022,
        supported=True,
        evidence_hash=_hash("mint"),
        tradable=True,
    )
    truth = PolicyRuntimeTruth(
        policy_bundle=_bundle(),
        provider_decisions={"jupiter": decision},
        mint_attestations={TOKEN_2022: mint},
    )

    assert decision.admitted_role is AdmittedProviderRole.DISCOVERY_ONLY
    assert truth.paper_ready is False
    assert any("stale-or-not-executable" in reason for reason in truth.blocking_reasons)


def test_pr147_unsupported_mint_cannot_be_tradable() -> None:
    with pytest.raises(PolicyAdmissionError, match="unsupported mint"):
        MintAttestation(
            mint=TOKEN_2022,
            owner_program_id=TOKEN_2022,
            supported=False,
            evidence_hash=_hash("mint"),
            tradable=True,
        )


def test_pr147_cross_domain_hash_substitution_is_rejected() -> None:
    ref = HashReference(domain=ADMISSION_DECISION_DOMAIN, digest=_hash("decision"))

    with pytest.raises(PolicyAdmissionError, match="hash domain mismatch"):
        require_domain(ref, POLICY_BUNDLE_DOMAIN)


def test_pr147_runtime_truth_rejects_impossible_provider_mapping() -> None:
    broken = ProviderAdmissionDecision(
        provider="jupiter",
        requested_role=RequestedProviderRole.EXECUTABLE,
        admitted_role=AdmittedProviderRole.EXECUTABLE,
        execution_allowed=False,
        request_ready=True,
        startup_ready=True,
        reasons=(),
        policy_bundle_hash=_bundle().bundle_hash,
        provider_evidence_hash=_hash("provider-evidence"),
    )

    with pytest.raises(PolicyAdmissionError, match="execution_allowed=false"):
        PolicyRuntimeTruth(
            policy_bundle=_bundle(),
            provider_decisions={"jupiter": broken},
            mint_attestations={},
        )


def test_pr147_policy_gate_models_current_jupiter_blocked_state() -> None:
    decision = evaluate_provider_admission(
        _bundle(),
        _evidence(
            contract_execution_allowed=False,
            credentialed_api_conformance=False,
            execution_composition_conformance=False,
            promotion_evidence=False,
        ),
    )

    assert decision.admitted_role is AdmittedProviderRole.DISCOVERY_ONLY
    assert decision.execution_allowed is False
    assert decision.startup_ready is False
    assert "contract-execution-denied" in decision.reasons
    assert "credentialed-api-conformance-missing" in decision.reasons
    assert "execution-composition-conformance-missing" in decision.reasons
    assert "promotion-evidence-missing" in decision.reasons
