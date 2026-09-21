from __future__ import annotations

from hashlib import sha256

import pytest

from src.mega8_04 import (
    CoverageRow,
    DependencyRecord,
    Disposition,
    NF_SYMBOLS,
    SignedEvidenceRecord,
    SimulationEngineResult,
    SuiObjectState,
    VerifiedPrimitive,
    append_signed_evidence_record,
    assemble_sui_object_state_frame,
    attest_reproducible_build,
    audit_post150_coverage,
    build_evm_swap_calldata,
    build_merkle_evidence_root,
    classify_simulator_disagreement,
    compile_dsl_to_primitive_graph,
    define_property_financial_invariants,
    define_verified_strategy_dsl,
    differential_test_evm_math,
    enroll_hsm_signer,
    execute_key_ceremony,
    export_incident_forensic_bundle,
    fuzz_account_meta_permissions,
    gate_on_simulation_quorum,
    generate_sbom,
    generate_stateful_test_sequences,
    publish_post150_release_verdict,
    reconcile_crosschain_settlement,
    recover_multi_region_signer,
    register_crosschain_asset_rights,
    register_evm_dex_math_adapter,
    run_post150_integrated_campaign,
    sandbox_strategy_plugin,
    schedule_next_evidence_cycle,
    shrink_failing_economic_case,
    simulate_ptb_exactly,
)

pytestmark = pytest.mark.unit

A = "a" * 64
B = "b" * 64
C = "c" * 64
ADDRESS = "0x" + "1" * 40


def test_nf_registry_is_exact_and_default_off() -> None:
    assert set(NF_SYMBOLS) == {f"NF-{number:03d}" for number in range(585, 641)}
    assert len(NF_SYMBOLS) == 56
    assert "unknown_outcome_holds_reservation" in define_property_financial_invariants()


def test_property_sequence_is_replayable_and_shrinks() -> None:
    first = generate_stateful_test_sequences(
        seed="case-a",
        operations=("reserve", "permit", "dispatch"),
        steps=6,
    )
    second = generate_stateful_test_sequences(
        seed="case-a",
        operations=("reserve", "permit", "dispatch"),
        steps=6,
    )
    assert first == second

    shrunk = shrink_failing_economic_case(
        ("reserve", "permit", "dispatch"),
        still_fails=lambda row: "dispatch" in row,
    )
    assert shrunk == ("dispatch",)


def test_permission_escalation_and_simulator_disagreement_fail_closed() -> None:
    permissions = fuzz_account_meta_permissions(
        {"payer": (True, True), "pool": (False, False)},
        {"payer": (True, True), "pool": (False, True)},
    )
    assert permissions.disposition is Disposition.BLOCKED
    assert "WRITABLE_ESCALATION:pool" in permissions.blockers

    one = SimulationEngineResult("litesvm", True, A, 10, B)
    two = SimulationEngineResult("mollusk", True, C, 10, B)
    disagreement = classify_simulator_disagreement((one, two))
    assert disagreement.disposition is Disposition.BLOCKED
    assert gate_on_simulation_quorum((one, two)).disposition is Disposition.BLOCKED


def test_supply_chain_sbom_and_reproducibility_are_deterministic() -> None:
    record = DependencyRecord(
        "example",
        "1.2.3",
        "MIT",
        "commit:" + "1" * 40,
        A,
    )
    first = generate_sbom((record,))
    second = generate_sbom((record,))
    assert first == second
    assert first["bomFormat"] == "CycloneDX"
    assert (
        attest_reproducible_build(
            first_artifact_sha256=A,
            second_artifact_sha256=A,
        ).disposition
        is Disposition.PASS
    )
    assert (
        attest_reproducible_build(
            first_artifact_sha256=A,
            second_artifact_sha256=B,
        ).disposition
        is Disposition.BLOCKED
    )


def test_signed_evidence_chain_and_merkle_bundle() -> None:
    first = SignedEvidenceRecord(1, A, None, "offline-attestor", B)
    rows = append_signed_evidence_record((), first)
    second = SignedEvidenceRecord(2, B, first.record_sha256, "offline-attestor", C)
    rows = append_signed_evidence_record(rows, second)
    root = build_merkle_evidence_root(item.record_sha256 for item in rows)
    bundle = export_incident_forensic_bundle(rows, incident_id="incident-1")
    assert bundle["merkle_root"] == root
    assert len(bundle["bundle_sha256"]) == 64


def test_hsm_contract_is_metadata_only_and_region_fenced() -> None:
    primary = enroll_hsm_signer(
        provider="mock-pkcs11",
        key_reference_sha256=A,
        region="riga-a",
        permit_semantics_sha256=B,
    )
    secondary = enroll_hsm_signer(
        provider="mock-pkcs11",
        key_reference_sha256=C,
        region="riga-b",
        permit_semantics_sha256=B,
    )
    assert primary.live_enabled is False
    assert (
        execute_key_ceremony(
            primary,
            approvals=("operator-a", "operator-b"),
            quorum=2,
        ).disposition
        is Disposition.PASS
    )
    assert (
        recover_multi_region_signer(
            primary,
            secondary,
        ).disposition
        is Disposition.PASS
    )


def test_evm_adapter_and_calldata_are_research_only() -> None:
    adapter = register_evm_dex_math_adapter(
        adapter_id="cpmm-reference",
        deployment=ADDRESS,
        math_version="integer-v1",
        source_commit="1" * 40,
        license_id="REFERENCE_ONLY",
    )
    assert adapter.research_only is True
    assert adapter.live_enabled is False
    calldata = build_evm_swap_calldata(
        selector_hex="0x12345678",
        amount_in=10,
        minimum_out=9,
        recipient=ADDRESS,
    )
    assert len(calldata) == 100
    assert (
        differential_test_evm_math(
            local_amount_out=9,
            reference_amount_out=9,
        ).disposition
        is Disposition.PASS
    )


def test_sui_exact_state_and_crosschain_reconciliation_remain_research_only() -> None:
    frame = assemble_sui_object_state_frame(
        chain_id="sui-mainnet",
        checkpoint=100,
        objects=(SuiObjectState("0x1", 7, "digest-a", True, True),),
    )
    sim = simulate_ptb_exactly(
        frame=frame,
        expected_after_sha256=A,
        observed_after_sha256=A,
    )
    assert sim.disposition is Disposition.RESEARCH_ONLY

    right = register_crosschain_asset_rights(
        canonical_asset_id="USDC",
        source_chain="solana",
        destination_chain="ethereum",
        custody_model="bridge-custody",
        bridge_identity="bridge-v1",
        finality_model="attested-finality",
    )
    assert right.research_only is True
    settlement = reconcile_crosschain_settlement(
        source_debit=100,
        destination_credit=99,
        bridge_fee=1,
        finality_proven=True,
    )
    assert settlement.disposition is Disposition.RESEARCH_ONLY


def test_dsl_cannot_gain_sign_or_send_capabilities() -> None:
    dsl = define_verified_strategy_dsl(
        version="v1",
        primitives=(VerifiedPrimitive("quote", A, "solana"),),
    )
    assert compile_dsl_to_primitive_graph(dsl, "quote") == ("quote",)
    blocked = sandbox_strategy_plugin(
        plugin_id="plugin-a",
        requested_capabilities=("READ_STATE", "SIGN"),
    )
    assert blocked.disposition is Disposition.BLOCKED
    assert blocked.signing_enabled is False


def test_post150_release_audit_is_honestly_blocked_without_full_evidence() -> None:
    rows = (
        CoverageRow(209, "COVERED_BY_EXISTING", "src.mega8_04", A),
        CoverageRow(210, "RESEARCH_ONLY", "src.mega8_04", B),
    )
    audit = audit_post150_coverage(rows)
    assert audit.covered_count == 2
    assert 151 in audit.missing_prs
    assert audit.release_claim_allowed is False
    campaign = run_post150_integrated_campaign(
        audit,
        code_generation="code-1",
        data_generation="data-1",
        model_generation="model-1",
        deployment_generation="deployment-1",
    )
    assert campaign.disposition is Disposition.BLOCKED
    verdict = publish_post150_release_verdict(
        audit,
        campaign,
        selected_capabilities=("MEGA8-04",),
        budgets={"capital": 0},
        residual_blockers=("EXTERNAL_EVIDENCE_REQUIRED",),
    )
    assert verdict["release_claim_allowed"] is False
    assert verdict["production_ready"] is False
    assert verdict["live_enabled"] is False
    cycle = schedule_next_evidence_cycle(
        current_cycle=0,
        residual_blockers=verdict["blockers"],
    )
    assert cycle["cycle"] == 1
    assert cycle["automatic_promotion"] is False


def test_merkle_leaf_identity_is_sha256() -> None:
    leaf = sha256(b"leaf").hexdigest()
    assert build_merkle_evidence_root((leaf,)) == leaf
