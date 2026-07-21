import pytest

from src.runtime_truth import (
    ConformanceState,
    ConformanceTruth,
    CredentialState,
    CredentialTruth,
    ProductMode,
    ProviderRole,
    ProviderTruth,
    RuntimeState,
    RuntimeTruth,
    RuntimeTruthError,
    RuntimeTruthInputs,
    StageState,
    StageTruth,
    build_runtime_truth,
)


PAPER_STAGES = (
    "capital_sizing",
    "planner",
    "compiler",
    "final_simulation",
    "reconciliation",
)


def credential(provider="jupiter", state=CredentialState.AVAILABLE):
    return CredentialTruth(provider=provider, required=True, state=state)


def conformance(
    provider="jupiter",
    *,
    credentialed_api=ConformanceState.VERIFIED,
    execution_composition=ConformanceState.VERIFIED,
    promotion_evidence=ConformanceState.VERIFIED,
    human_reviewed=True,
):
    return ConformanceTruth(
        provider=provider,
        credentialed_api=credentialed_api,
        execution_composition=execution_composition,
        promotion_evidence=promotion_evidence,
        human_reviewed=human_reviewed,
    )


def provider(
    *,
    name="jupiter",
    contract_execution_allowed=True,
    requested_role=ProviderRole.EXECUTABLE,
    credential_state=CredentialState.AVAILABLE,
    conformance_state=ConformanceState.VERIFIED,
    human_reviewed=True,
    startup_ready=True,
    request_ready=True,
):
    return ProviderTruth(
        name=name,
        contract_execution_allowed=contract_execution_allowed,
        requested_role=requested_role,
        credential=credential(name, credential_state),
        conformance=conformance(
            name,
            credentialed_api=conformance_state,
            execution_composition=conformance_state,
            promotion_evidence=conformance_state,
            human_reviewed=human_reviewed,
        ),
        startup_ready=startup_ready,
        request_ready=request_ready,
        external_pin="jupiter-v2-test-pin",
    )


def stages(state=StageState.PRESENT):
    return tuple(StageTruth(name=name, state=state) for name in PAPER_STAGES)


def truth_with(*, providers, stage_state=StageState.PRESENT):
    return build_runtime_truth(
        RuntimeTruthInputs(
            product_mode=ProductMode.PAPER,
            providers=providers,
            active_detector="runtime-discovery-detector",
            stages=stages(stage_state),
            external_pins={"jupiter": "jupiter-v2-test-pin"},
            trace_id="test-pr103",
        )
    )


def test_execution_allowed_false_cannot_request_executable():
    with pytest.raises(RuntimeTruthError, match="execution_allowed=false"):
        provider(contract_execution_allowed=False)


def test_unverified_conformance_derives_disabled_not_executable():
    candidate = provider(
        conformance_state=ConformanceState.INCOMPLETE,
        human_reviewed=False,
    )

    truth = truth_with(providers=(candidate,))

    assert truth.admitted_roles["jupiter"] == ProviderRole.DISABLED
    assert truth.state is RuntimeState.BLOCKED
    assert "jupiter:execution-conformance-unverified" in truth.readiness_reasons
    assert truth.ready_payload()["ready"] is False
    assert truth.status_payload()["status"] == "blocked"


def test_missing_key_cannot_report_startup_ready():
    with pytest.raises(RuntimeTruthError, match="missing/invalid credential"):
        provider(credential_state=CredentialState.MISSING, startup_ready=True)


def test_missing_key_disables_provider_when_startup_not_ready():
    candidate = provider(
        requested_role=ProviderRole.QUOTE_ONLY,
        credential_state=CredentialState.MISSING,
        startup_ready=False,
        request_ready=False,
    )

    truth = truth_with(providers=(candidate,))

    assert truth.admitted_roles["jupiter"] == ProviderRole.DISABLED
    assert "jupiter:credential-missing" in truth.readiness_reasons
    assert truth.ready_payload()["ready"] is False


def test_stage_absent_blocks_paper_readiness():
    truth = truth_with(providers=(provider(),), stage_state=StageState.ABSENT)

    assert truth.paper_ready is False
    assert truth.state is RuntimeState.BLOCKED
    assert "paper-stages-incomplete" in truth.readiness_reasons
    assert truth.ready_payload()["ready"] is False


def test_ready_truth_has_consistent_health_ready_status_metrics_and_trace():
    truth = truth_with(providers=(provider(),))

    assert truth.state is RuntimeState.READY
    assert truth.paper_ready is True
    assert truth.live_allowed is False
    assert truth.health_payload()["ok"] is True
    assert truth.ready_payload()["ready"] is True
    assert truth.status_payload()["status"] == "ready"
    assert truth.metrics()["runtime_truth_live_allowed"] == 0
    assert truth.to_dict()["trace_id"] == "test-pr103"
    assert truth.to_dict()["providers"]["jupiter"]["request_ready"] is True
    assert truth.to_dict()["providers"]["jupiter"]["startup_ready"] is True


def test_runtime_truth_is_immutable_mapping():
    truth = truth_with(providers=(provider(),))

    with pytest.raises(TypeError):
        truth.providers["other"] = provider(name="other")  # type: ignore[index]

    with pytest.raises(Exception):
        RuntimeTruth(
            product_mode=ProductMode.PAPER,
            providers={"jupiter": provider()},
            active_detector="runtime-discovery-detector",
            stages={
                name: StageTruth(name=name, state=StageState.PRESENT)
                for name in PAPER_STAGES
            },
            live_allowed=True,
        )
