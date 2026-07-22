from __future__ import annotations

import pytest

from src.transaction_proof_pr149 import (
    CpiContract,
    InstructionContract,
    InstructionFamily,
    PR149ProofError,
    ReconciliationContract,
    SimulationContract,
    TransactionContract,
    TransactionProofEvidence,
    assert_transaction_proof_review_ready,
    evaluate_transaction_proof,
)

H1 = "a" * 64
H2 = "b" * 64
H3 = "c" * 64
PAYER = "11111111111111111111111111111111"
SIGNER = "So11111111111111111111111111111111111111112"
ATA = "ATokenGPvoter111111111111111111111111111111"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
MARGINFI = "MRGNfi111111111111111111111111111111111111"
ROUTE = "RoutE1111111111111111111111111111111111111"


def tx(**kw):
    data = dict(
        count=1,
        version="v0",
        full_wire_bytes=1100,
        expected_payer=PAYER,
        observed_payer=PAYER,
        expected_signers=(SIGNER,),
        observed_signers=(SIGNER,),
        expected_privileges_hash=H1,
        observed_privileges_hash=H1,
        expected_alt_hash=H2,
        observed_alt_hash=H2,
        alt_active=True,
        blockhash_valid=True,
        blockhash_context_slot=20,
        min_context_slot=10,
        last_valid_block_height=100,
        compute_budget_instruction_count=1,
        compute_unit_limit=250_000,
        compute_unit_price_micro_lamports=1000,
        get_fee_for_message_lamports=5000,
        landing_cost_cap_lamports=20_000,
        estimated_landing_cost_lamports=15_000,
    )
    data.update(kw)
    return TransactionContract(**data)


def ix(family, program, **kw):
    data = dict(
        family=family.value if isinstance(family, InstructionFamily) else family,
        program_id=program,
        amount_atoms=10,
        expected_amount_atoms=10,
        authority=SIGNER,
        expected_authority=SIGNER,
    )
    data.update(kw)
    return InstructionContract(**data)


def ixs():
    return (
        ix(InstructionFamily.SYSTEM, PAYER),
        ix(InstructionFamily.ATA, ATA),
        ix(InstructionFamily.SPL_TOKEN, TOKEN),
        ix(InstructionFamily.TOKEN_2022, TOKEN_2022),
        ix(InstructionFamily.JUPITER, JUPITER),
        ix(InstructionFamily.MARGINFI, MARGINFI),
        ix(InstructionFamily.ROUTE, ROUTE),
    )


def sim(**kw):
    data = dict(
        accounts_hash=H1,
        owners_hash=H2,
        data_hash=H3,
        balances_hash=H1,
        token_balances_hash=H2,
        loaded_addresses_hash=H3,
        inner_instructions_hash=H1,
        logs_hash=H2,
        return_data_hash=H3,
        raw_evidence_bytes=4096,
        truncated=False,
        simulation_err=None,
        provisional_compute_units=220_000,
        final_compute_units=230_000,
    )
    data.update(kw)
    return SimulationContract(**data)


def cpi(**kw):
    data = dict(
        planned_programs=(PAYER, ATA, TOKEN, TOKEN_2022, JUPITER, MARGINFI, ROUTE),
        top_level_programs=(PAYER, ATA, TOKEN, TOKEN_2022, JUPITER, MARGINFI, ROUTE),
        observed_cpi_programs=(TOKEN, TOKEN_2022, MARGINFI),
        allowed_cpi_programs=(TOKEN, TOKEN_2022, MARGINFI),
        call_graph_hash=H1,
    )
    data.update(kw)
    return CpiContract(**data)


def recon(**kw):
    data = dict(
        principal_atoms=1000,
        required_repayment_atoms=1001,
        actual_repayment_atoms=1001,
        fees_lamports=5000,
        token_deltas_hash=H2,
        native_deltas_hash=H3,
        unauthorized_account_mutation=False,
        conservative_net_lamports=50,
    )
    data.update(kw)
    return ReconciliationContract(**data)


def evidence(**kw):
    proof = kw.pop("proof_hash", None)
    data = dict(
        transaction=tx(),
        instructions=ixs(),
        simulation=sim(),
        cpi=cpi(),
        reconciliation=recon(),
        expected_route_programs=(ROUTE,),
    )
    data.update(kw)
    ev = TransactionProofEvidence(**data)
    return TransactionProofEvidence(**data, proof_hash=proof or ev.canonical_hash())


def blockers(ev):
    return set(evaluate_transaction_proof(ev).blockers)


def test_valid_sender_free_proof_is_review_ready():
    decision = evaluate_transaction_proof(evidence())
    assert decision.review_ready
    assert decision.sender_free_transaction_proof_ready
    assert not decision.sender_submission_allowed
    assert not decision.live_claim_allowed


def test_one_canonical_v0_wire_limit_required():
    b = blockers(
        evidence(
            transaction=tx(count=2, version="legacy", legacy=True, full_wire_bytes=1233)
        )
    )
    assert {"NOT_ONE_TRANSACTION", "NOT_CANONICAL_V0", "FULL_WIRE_LIMIT"} <= b


def test_payer_signer_and_privileges_must_match():
    b = blockers(
        evidence(
            transaction=tx(
                observed_payer=SIGNER,
                observed_signers=(PAYER,),
                observed_privileges_hash=H2,
            )
        )
    )
    assert {"PAYER_MISMATCH", "SIGNER_SET_MISMATCH", "ACCOUNT_PRIVILEGES_MISMATCH"} <= b


def test_alt_blockhash_compute_fee_and_cost_are_final():
    b = blockers(
        evidence(
            transaction=tx(
                observed_alt_hash=H3,
                alt_active=False,
                blockhash_valid=False,
                compute_budget_instruction_count=2,
                get_fee_for_message_lamports=None,
                estimated_landing_cost_lamports=25_000,
            )
        )
    )
    assert {
        "ALT_PROOF_INVALID",
        "BLOCKHASH_PROOF_INVALID",
        "COMPUTE_FINALIZATION_INVALID",
        "FINAL_FEE_MISSING",
        "LANDING_COST_CAP_EXCEEDED",
    } <= b


def test_no_sender_private_key_or_caller_adjustable_ceiling():
    b = blockers(
        evidence(
            transaction=tx(
                caller_adjustable_ceiling=True,
                sender_import_present=True,
                private_key_material_present=True,
            )
        )
    )
    assert {"CALLER_ADJUSTABLE_CEILING", "SENDER_IMPORT_PRESENT", "PRIVATE_KEY_MATERIAL_PRESENT"} <= b


def test_instruction_firewall_blocks_unknown_unsafe_and_missing_families():
    bad = ix(
        "unknown",
        "bad",
        decoded=False,
        allowed=False,
        amount_atoms=9,
        authority="other",
        authority_change=True,
        arbitrary_transfer=True,
    )
    b = blockers(evidence(instructions=(bad,)))
    assert "IX_0_UNKNOWN_FAMILY" in b
    assert "MISSING_REQUIRED_FAMILY:system" in b


def test_route_program_requires_attestation():
    b = blockers(evidence(expected_route_programs=()))
    assert "IX_6_UNATTESTED_ROUTE_PROGRAM" in b


def test_simulation_must_own_raw_complete_evidence():
    b = blockers(
        evidence(
            simulation=sim(
                accounts_hash="bad",
                raw_evidence_bytes=0,
                truncated=True,
                simulation_err="err",
                final_compute_units=0,
            )
        )
    )
    assert {
        "MALFORMED_SHA256:accounts_hash",
        "SIM_RAW_EVIDENCE_MISSING",
        "SIM_EVIDENCE_TRUNCATED",
        "SIMULATION_ERR",
        "SIM_COMPUTE_MISSING",
    } <= b


def test_cpi_graph_must_match_and_be_allowlisted():
    bad = "Bad111111111111111111111111111111111111111"
    b = blockers(
        evidence(
            cpi=cpi(
                top_level_programs=(PAYER,),
                observed_cpi_programs=(TOKEN, bad),
                allowed_cpi_programs=(TOKEN,),
                call_graph_hash="bad",
            )
        )
    )
    assert {"CPI_MISSING_TOP_LEVEL", "CPI_UNEXPECTED_PROGRAM", "MALFORMED_SHA256:call_graph_hash"} <= b


def test_reconciliation_blocks_underpayment_and_mutation():
    b = blockers(
        evidence(
            reconciliation=recon(
                actual_repayment_atoms=999,
                unauthorized_account_mutation=True,
            )
        )
    )
    assert {"REPAYMENT_BELOW_REQUIRED", "UNAUTHORIZED_ACCOUNT_MUTATION"} <= b


def test_one_byte_change_or_bad_hash_invalidates_proof():
    base = evidence()
    changed = evidence(
        reconciliation=recon(conservative_net_lamports=51),
        proof_hash=base.canonical_hash(),
    )
    assert base.canonical_hash() != changed.canonical_hash()
    assert "PROOF_HASH_MISMATCH" in blockers(changed)
    with pytest.raises(PR149ProofError):
        assert_transaction_proof_review_ready(evidence(transaction=tx(blockhash_valid=False)))
