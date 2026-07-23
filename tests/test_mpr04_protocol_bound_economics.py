from __future__ import annotations

import pytest

from src.mpr04_protocol_bound_economics import (
    ChainProgramRegistry,
    DecoderOwnedEconomics,
    ExactSimulationArtifact,
    InstructionEvidence,
    InstructionFirewallEvidence,
    MPR04ExecutionCandidate,
    MPR04ProtocolExecutionError,
    SCHEMA_VERSION,
    SerializedTransactionEvidence,
    SimulationRawAccount,
    BlockhashFreshnessEvidence,
    evaluate_mpr04_candidate,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64


def ix(index: int, role: str, *, program_id: str) -> InstructionEvidence:
    return InstructionEvidence(
        index=index,
        role=role,
        program_id=program_id,
        account_keys_hash=HASH_A,
        data_hash=HASH_B,
        writable_account_count=3,
    )


def firewall(*instructions: InstructionEvidence) -> InstructionFirewallEvidence:
    return InstructionFirewallEvidence(instructions=tuple(instructions))


def good_firewall() -> InstructionFirewallEvidence:
    return firewall(
        ix(0, "marginfi.borrow", program_id="marginfi.v2"),
        ix(1, "jupiter.leg_a", program_id="jupiter.swap"),
        ix(2, "jupiter.leg_b", program_id="jupiter.swap"),
        ix(3, "marginfi.repay", program_id="marginfi.v2"),
    )


def good_simulation(message_hash: str = HASH_C, blockhash: str = "Blockhash111") -> ExactSimulationArtifact:
    return ExactSimulationArtifact(
        message_hash=message_hash,
        blockhash=blockhash,
        slot=123,
        success=True,
        units_consumed=50_000,
        decoder_version="decoder-v1",
        returned_accounts=(
            SimulationRawAccount(
                account_key="wallet-wsol-ata",
                owner_program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                pre_hash=HASH_D,
                post_hash=HASH_E,
                pre_lamports=2_000,
                post_lamports=2_075,
            ),
        ),
    )


def good_candidate() -> MPR04ExecutionCandidate:
    blockhash = BlockhashFreshnessEvidence(
        blockhash="Blockhash111",
        fetched_at_slot=100,
        current_block_height=1_000,
        last_valid_block_height=1_200,
        safety_margin_blocks=10,
    )
    tx = SerializedTransactionEvidence(
        message_hash=HASH_C,
        versioned_message_bytes_hash=HASH_F,
        unsigned_transaction_bytes=700,
        required_signature_count=1,
    )
    simulation = good_simulation(message_hash=tx.message_hash, blockhash=blockhash.blockhash)
    simulation_hash = simulation.validate(
        expected_message_hash=tx.message_hash,
        expected_blockhash=blockhash.blockhash,
    )
    economics = DecoderOwnedEconomics(
        principal_lamports=1_000,
        flash_fee_lamports=5,
        repayment_lamports=1_005,
        gross_output_lamports=1_100,
        network_fee_lamports=10,
        priority_tip_lamports=3,
        rent_loss_lamports=2,
        transfer_fee_lamports=1,
        contingency_lamports=4,
        realized_account_delta_lamports=75,
        minimum_profit_lamports=70,
        source_simulation_hash=simulation_hash,
        decoder_version="decoder-v1",
    )
    return MPR04ExecutionCandidate(
        registry=ChainProgramRegistry(),
        firewall=good_firewall(),
        blockhash=blockhash,
        serialized_transaction=tx,
        simulation=simulation,
        economics=economics,
        attempt_generation=1,
        capital_reservation_hash=HASH_A,
    )


def replace_candidate(candidate: MPR04ExecutionCandidate, **overrides) -> MPR04ExecutionCandidate:
    values = {
        "registry": candidate.registry,
        "firewall": candidate.firewall,
        "blockhash": candidate.blockhash,
        "serialized_transaction": candidate.serialized_transaction,
        "simulation": candidate.simulation,
        "economics": candidate.economics,
        "attempt_generation": candidate.attempt_generation,
        "capital_reservation_hash": candidate.capital_reservation_hash,
    }
    values.update(overrides)
    return MPR04ExecutionCandidate(**values)


def test_mpr04_accepts_complete_sender_free_golden_vector() -> None:
    report = evaluate_mpr04_candidate(good_candidate())

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["ready_sender_free"] is True
    assert report["live_execution_allowed"] is False
    assert report["signer_or_sender_allowed"] is False
    assert report["total_required_output_lamports"] == 1_025
    assert report["conservative_profit_lamports"] == 75
    assert len(report["evidence_hash"]) == 64


def test_mpr04_rejects_duplicate_critical_instruction_roles() -> None:
    candidate = replace_candidate(
        good_candidate(),
        firewall=firewall(
            ix(0, "marginfi.borrow", program_id="marginfi.v2"),
            ix(1, "marginfi.borrow", program_id="marginfi.v2"),
            ix(2, "jupiter.leg_a", program_id="jupiter.swap"),
            ix(3, "jupiter.leg_b", program_id="jupiter.swap"),
            ix(4, "marginfi.repay", program_id="marginfi.v2"),
        ),
    )

    with pytest.raises(MPR04ProtocolExecutionError, match="MPR04_REQUIRED_ROLE_NOT_EXACTLY_ONCE"):
        evaluate_mpr04_candidate(candidate)


def test_mpr04_rejects_unknown_side_effecting_instruction_role() -> None:
    candidate = replace_candidate(
        good_candidate(),
        firewall=firewall(
            ix(0, "marginfi.borrow", program_id="marginfi.v2"),
            ix(1, "jupiter.leg_a", program_id="jupiter.swap"),
            ix(2, "jupiter.leg_b", program_id="jupiter.swap"),
            ix(3, "jupiter.hidden_leg", program_id="jupiter.swap"),
            ix(4, "marginfi.repay", program_id="marginfi.v2"),
        ),
    )

    with pytest.raises(MPR04ProtocolExecutionError, match="MPR04_UNKNOWN_SIDE_EFFECTING_ROLE"):
        evaluate_mpr04_candidate(candidate)


def test_mpr04_rejects_expired_blockhash_probe() -> None:
    candidate = replace_candidate(
        good_candidate(),
        blockhash=BlockhashFreshnessEvidence(
            blockhash="Blockhash111",
            fetched_at_slot=100,
            current_block_height=1_000,
            last_valid_block_height=1,
            safety_margin_blocks=0,
        ),
    )

    with pytest.raises(MPR04ProtocolExecutionError, match="MPR04_BLOCKHASH_EXPIRED_OR_TOO_CLOSE"):
        evaluate_mpr04_candidate(candidate)


def test_mpr04_rejects_simulation_without_raw_returned_accounts() -> None:
    tx = SerializedTransactionEvidence(
        message_hash=HASH_C,
        versioned_message_bytes_hash=HASH_F,
        unsigned_transaction_bytes=700,
        required_signature_count=1,
    )
    candidate = replace_candidate(
        good_candidate(),
        serialized_transaction=tx,
        simulation=ExactSimulationArtifact(
            message_hash=tx.message_hash,
            blockhash="Blockhash111",
            slot=123,
            success=True,
            units_consumed=50_000,
            decoder_version="decoder-v1",
            returned_accounts=(),
        ),
    )

    with pytest.raises(MPR04ProtocolExecutionError, match="MPR04_RAW_RETURNED_ACCOUNTS_REQUIRED"):
        evaluate_mpr04_candidate(candidate)


def test_mpr04_rejects_caller_economics_not_bound_to_simulation() -> None:
    candidate = replace_candidate(
        good_candidate(),
        economics=DecoderOwnedEconomics(
            principal_lamports=1_000,
            flash_fee_lamports=5,
            repayment_lamports=1_005,
            gross_output_lamports=1_100,
            network_fee_lamports=10,
            priority_tip_lamports=3,
            rent_loss_lamports=2,
            transfer_fee_lamports=1,
            contingency_lamports=4,
            realized_account_delta_lamports=75,
            minimum_profit_lamports=70,
            source_simulation_hash=HASH_B,
            decoder_version="decoder-v1",
        ),
    )

    with pytest.raises(MPR04ProtocolExecutionError, match="MPR04_ECONOMICS_NOT_BOUND_TO_SIMULATION"):
        evaluate_mpr04_candidate(candidate)


def test_mpr04_rejects_flash_repayment_formula_mismatch() -> None:
    base = good_candidate()
    economics = DecoderOwnedEconomics(
        principal_lamports=1_000,
        flash_fee_lamports=5,
        repayment_lamports=1_004,
        gross_output_lamports=1_100,
        network_fee_lamports=10,
        priority_tip_lamports=3,
        rent_loss_lamports=2,
        transfer_fee_lamports=1,
        contingency_lamports=4,
        realized_account_delta_lamports=76,
        minimum_profit_lamports=70,
        source_simulation_hash=base.economics.source_simulation_hash,
        decoder_version="decoder-v1",
    )
    candidate = replace_candidate(base, economics=economics)

    with pytest.raises(MPR04ProtocolExecutionError, match="MPR04_FLASH_REPAYMENT_FORMULA_INVALID"):
        evaluate_mpr04_candidate(candidate)


def test_mpr04_contingency_and_rent_are_required_pnl_deductions() -> None:
    base = good_candidate()
    economics = DecoderOwnedEconomics(
        principal_lamports=1_000,
        flash_fee_lamports=5,
        repayment_lamports=1_005,
        gross_output_lamports=1_100,
        network_fee_lamports=10,
        priority_tip_lamports=3,
        rent_loss_lamports=40,
        transfer_fee_lamports=1,
        contingency_lamports=40,
        realized_account_delta_lamports=75,
        minimum_profit_lamports=70,
        source_simulation_hash=base.economics.source_simulation_hash,
        decoder_version="decoder-v1",
    )
    candidate = replace_candidate(base, economics=economics)

    with pytest.raises(MPR04ProtocolExecutionError, match="MPR04_DECODER_DELTA_MISMATCH"):
        evaluate_mpr04_candidate(candidate)


def test_mpr04_rejects_signed_wire_size_exceeding_packet_limit() -> None:
    candidate = replace_candidate(
        good_candidate(),
        serialized_transaction=SerializedTransactionEvidence(
            message_hash=HASH_C,
            versioned_message_bytes_hash=HASH_F,
            unsigned_transaction_bytes=1_200,
            required_signature_count=1,
        ),
    )

    with pytest.raises(MPR04ProtocolExecutionError, match="MPR04_SIGNED_TRANSACTION_WIRE_SIZE_EXCEEDED"):
        evaluate_mpr04_candidate(candidate)


def test_mpr04_live_and_signer_surface_remain_forbidden() -> None:
    candidate = good_candidate()

    with pytest.raises(MPR04ProtocolExecutionError, match="MPR04_LIVE_EXECUTION_NOT_ALLOWED"):
        evaluate_mpr04_candidate(candidate, live_execution_allowed=True)
    with pytest.raises(MPR04ProtocolExecutionError, match="MPR04_SIGNER_OR_SENDER_NOT_ALLOWED"):
        evaluate_mpr04_candidate(candidate, signer_or_sender_allowed=True)


def test_mpr04_public_mapping_constructor_is_disabled_for_runtime_economics() -> None:
    with pytest.raises(
        MPR04ProtocolExecutionError,
        match="MPR04_PUBLIC_RUNTIME_MAPPING_CONSTRUCTOR_DISABLED",
    ):
        MPR04ExecutionCandidate.from_mapping({})
