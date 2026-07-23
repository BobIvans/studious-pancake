from __future__ import annotations

from dataclasses import replace

from src.mpr28_protocol_bound_economic_execution_gate import (
    ABSORBED_FINDING_RANGE,
    REQUIRED_CHAIN_PROGRAMS,
    REQUIRED_NEGATIVE_VECTORS,
    CapitalArbitrationEvidence,
    ChainProgramEvidence,
    DecoderAccountingEvidence,
    ExactMessageEvidence,
    MPR28Evidence,
    MPR28GateState,
    RawSimulationEvidence,
    evaluate_mpr28_evidence,
)

HASH = "a" * 64
HASH_B = "b" * 64


def _program(name: str) -> ChainProgramEvidence:
    return ChainProgramEvidence(name, HASH, HASH, HASH, HASH, True, True)


def valid_evidence() -> MPR28Evidence:
    message = ExactMessageEvidence(
        HASH, HASH, HASH, HASH, HASH, HASH, HASH, HASH,
        900, 1232, False, True, True, True, True, True, True, True, True,
    )
    sim = RawSimulationEvidence(
        HASH, HASH, HASH, HASH, HASH, 100_000, HASH, HASH, HASH,
        True, True, True, True, True,
    )
    acct = DecoderAccountingEvidence(
        HASH, HASH, HASH, HASH,
        1_000_000, 1_002_500, 2_500, 5_000, 2_039_280, 1_000, 500, 0, 0, 3_000,
        3_100_000, 48_720,
        False, True, True, True, True, True, True,
    )
    cap = CapitalArbitrationEvidence(
        HASH, HASH, HASH, HASH, HASH, 2, 1,
        True, True, True, True,
    )
    return MPR28Evidence(
        True, True, True,
        ABSORBED_FINDING_RANGE,
        tuple(_program(name) for name in REQUIRED_CHAIN_PROGRAMS),
        message,
        sim,
        acct,
        cap,
        REQUIRED_NEGATIVE_VECTORS,
        True, True, True, True, True, True,
    )


def _codes(evidence: MPR28Evidence) -> set[str]:
    return {violation.code for violation in evaluate_mpr28_evidence(evidence).violations}


def test_valid_evidence_qualifies_sender_free_only() -> None:
    report = evaluate_mpr28_evidence(valid_evidence())
    assert report.state is MPR28GateState.QUALIFIED
    assert report.paper_candidate_allowed is True
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
    assert report.private_key_material_allowed is False


def test_missing_dependencies_block_qualification() -> None:
    codes = _codes(replace(valid_evidence(), mpr25_artifact_truth_accepted=False, mpr26_durable_authority_accepted=False))
    assert "MPR28_DEPENDS_ON_MPR25" in codes
    assert "MPR28_DEPENDS_ON_MPR26" in codes


def test_digest_only_message_and_wire_size_over_cap_block() -> None:
    message = replace(valid_evidence().exact_message, caller_supplied_digest_only=True, wire_size_bytes=1233)
    codes = _codes(replace(valid_evidence(), exact_message=message))
    assert "MPR28_DIGEST_ONLY_MESSAGE" in codes
    assert "MPR28_WIRE_SIZE_OVER_CAP" in codes


def test_simulation_must_bind_to_exact_message_bytes() -> None:
    simulation = replace(valid_evidence().raw_simulation, message_bytes_hash=HASH_B)
    assert "MPR28_SIM_MESSAGE_MISMATCH" in _codes(replace(valid_evidence(), raw_simulation=simulation))


def test_accounting_must_be_decoder_owned_and_formula_checked() -> None:
    acct = replace(valid_evidence().decoder_accounting, caller_manual_observations_allowed=True, conservative_net_pnl_lamports=1)
    codes = _codes(replace(valid_evidence(), decoder_accounting=acct))
    assert "MPR28_CALLER_MONEY_ALLOWED" in codes
    assert "MPR28_ACCOUNTING_FORMULA_MISMATCH" in codes


def test_repayment_must_equal_principal_plus_protocol_fee() -> None:
    acct = replace(valid_evidence().decoder_accounting, repayment_lamports=999)
    assert "MPR28_REPAYMENT_MISMATCH" in _codes(replace(valid_evidence(), decoder_accounting=acct))


def test_float_or_bool_money_values_block() -> None:
    acct = replace(valid_evidence().decoder_accounting, tx_fee_lamports=1.5)  # type: ignore[arg-type]
    assert "MPR28_MONEY_NOT_INTEGER" in _codes(replace(valid_evidence(), decoder_accounting=acct))
    acct_bool = replace(valid_evidence().decoder_accounting, tx_fee_lamports=True)  # type: ignore[arg-type]
    assert "MPR28_MONEY_NOT_INTEGER" in _codes(replace(valid_evidence(), decoder_accounting=acct_bool))


def test_capital_double_acceptance_and_bad_counts_block() -> None:
    cap = replace(valid_evidence().capital_arbitration, competing_candidates_evaluated=1, accepted_candidates=2, no_capital_double_acceptance=False)
    codes = _codes(replace(valid_evidence(), capital_arbitration=cap))
    assert "MPR28_CAPITAL_COUNT_ORDERING" in codes
    assert "MPR28_CAPITAL_PROOF_MISSING" in codes


def test_missing_program_registry_and_negative_vectors_block() -> None:
    evidence = replace(
        valid_evidence(),
        chain_programs=tuple(_program(name) for name in REQUIRED_CHAIN_PROGRAMS[:-1]),
        negative_vectors_passed=REQUIRED_NEGATIVE_VECTORS[:-2],
    )
    codes = _codes(evidence)
    assert "MPR28_PROGRAM_REGISTRY_MISSING" in codes
    assert "MPR28_NEGATIVE_VECTORS_INCOMPLETE" in codes


def test_cutover_flags_and_live_surface_block() -> None:
    evidence = replace(
        valid_evidence(),
        recorded_paper_only_replay_not_qualification=False,
        runtime_public_profit_constructors_removed=False,
        signer_or_sender_reachable=True,
        live_execution_enabled=True,
        private_key_material_accessible=True,
    )
    codes = _codes(evidence)
    assert "MPR28_CUTOVER_INCOMPLETE" in codes
    assert "MPR28_SIGNER_SENDER_REACHABLE" in codes
    assert "MPR28_LIVE_ENABLED" in codes
    assert "MPR28_PRIVATE_KEY_ACCESS" in codes
