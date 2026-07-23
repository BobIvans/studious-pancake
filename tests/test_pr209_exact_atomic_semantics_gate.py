from src.execution.pr209_exact_atomic_semantics_gate import (
    AtomicInstruction,
    BlockhashFreshness,
    DecodedSemanticEffect,
    FeeAccounting,
    IntegerEconomics,
    PR209GateState,
    PR209AtomicEvidence,
    SimulationBinding,
    TimelineEvidence,
    evaluate_pr209_atomic_evidence,
)


def h(seed: str) -> str:
    return (seed * 64)[:64]


def complete_evidence(**overrides) -> PR209AtomicEvidence:
    instructions = (
        AtomicInstruction("marginfi.borrow", "MarginFi111111111111111111111111111111", h("1")),
        AtomicInstruction("jupiter.leg_a", "Jupiter1111111111111111111111111111111", h("2")),
        AtomicInstruction("jupiter.leg_b", "Jupiter1111111111111111111111111111111", h("3")),
        AtomicInstruction("marginfi.repay", "MarginFi111111111111111111111111111111", h("4")),
    )
    effects = (
        DecodedSemanticEffect("marginfi.borrow", h("1"), h("5"), principal_lamports=1_000_000),
        DecodedSemanticEffect("jupiter.leg_a", h("2"), h("6"), input_lamports=1_000_000, output_lamports=1_020_000),
        DecodedSemanticEffect("jupiter.leg_b", h("3"), h("7"), input_lamports=1_020_000, output_lamports=1_050_000),
        DecodedSemanticEffect(
            "marginfi.repay",
            h("4"),
            h("8"),
            flash_fee_lamports=3_000,
            repayment_lamports=1_003_000,
        ),
    )
    values = {
        "release_artifact_hash": h("a"),
        "rooted_provider_generation_hash": h("b"),
        "protocol_registry_hash": h("c"),
        "instructions": instructions,
        "semantic_effects": effects,
        "blockhash": BlockhashFreshness(
            current_block_height=100,
            last_valid_block_height=200,
            safety_margin_blocks=10,
            min_context_slot=50,
            observed_context_slot=55,
        ),
        "simulation": SimulationBinding(
            success=True,
            error_code=None,
            sig_verify_enabled=True,
            exact_message_hash=h("d"),
            exact_signed_payload_hash=h("e"),
            raw_account_state_hash=h("9"),
            account_delta_hash=h("a"),
            logs_hash=h("b"),
            units_consumed=120_000,
            total_transaction_fee_lamports=5_000,
        ),
        "timeline": TimelineEvidence(
            provider_snapshot_unix_ns=1_000,
            quote_unix_ns=2_000,
            blockhash_unix_ns=3_000,
            compile_unix_ns=4_000,
            simulation_unix_ns=5_000,
            max_total_age_ns=10_000,
        ),
        "economics": IntegerEconomics(
            principal_lamports=1_000_000,
            flash_fee_lamports=3_000,
            repayment_lamports=1_003_000,
            expected_output_lamports=1_050_000,
            total_transaction_fee_lamports=5_000,
            rent_lamports=2_000,
            tip_lamports=1_000,
            transfer_fee_lamports=500,
            contingency_lamports=1_000,
            minimum_profit_lamports=10_000,
        ),
        "fee_accounting": FeeAccounting(projected_total_transaction_fee_lamports=5_000),
    }
    values.update(overrides)
    return PR209AtomicEvidence(**values)


def codes(report):
    return {blocker.code for blocker in report.blockers}


def test_accepts_complete_sender_free_atomic_evidence():
    report = evaluate_pr209_atomic_evidence(complete_evidence())

    assert report.state == PR209GateState.READY_FOR_SENDER_FREE_ATOMIC_PROOF
    assert report.blockers == ()
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False


def test_rejects_expired_or_near_expired_blockhash():
    evidence = complete_evidence(
        blockhash=BlockhashFreshness(
            current_block_height=199,
            last_valid_block_height=200,
            safety_margin_blocks=2,
            min_context_slot=50,
            observed_context_slot=55,
        )
    )

    report = evaluate_pr209_atomic_evidence(evidence)

    assert report.state == PR209GateState.BLOCKED
    assert "PR209_BLOCKHASH_EXPIRED_OR_TOO_CLOSE" in codes(report)


def test_rejects_unknown_instruction_role():
    instructions = complete_evidence().instructions + (
        AtomicInstruction("system.transfer.unmodeled", "11111111111111111111111111111111", h("6")),
    )

    report = evaluate_pr209_atomic_evidence(complete_evidence(instructions=instructions))

    assert "PR209_INSTRUCTION_SEQUENCE_NOT_EXACT" in codes(report)
    assert "PR209_UNKNOWN_INSTRUCTION_ROLE" in codes(report)


def test_rejects_duplicate_required_instruction_role():
    base = complete_evidence()
    instructions = (
        base.instructions[0],
        base.instructions[1],
        base.instructions[1],
        base.instructions[2],
        base.instructions[3],
    )

    report = evaluate_pr209_atomic_evidence(complete_evidence(instructions=instructions))

    assert "PR209_DUPLICATE_INSTRUCTION_ROLE" in codes(report)
    assert "PR209_INSTRUCTION_SEQUENCE_NOT_EXACT" in codes(report)


def test_rejects_instruction_without_decoded_effect():
    base = complete_evidence()
    effects = base.semantic_effects[:-1]

    report = evaluate_pr209_atomic_evidence(complete_evidence(semantic_effects=effects))

    assert "PR209_EFFECT_COUNT_MISMATCH" in codes(report)
    assert "PR209_EFFECT_MISSING_FOR_INSTRUCTION" in codes(report)


def test_rejects_decoded_repayment_amount_mismatch():
    base = complete_evidence()
    effects = base.semantic_effects[:-1] + (
        DecodedSemanticEffect(
            "marginfi.repay",
            h("4"),
            h("8"),
            flash_fee_lamports=3_000,
            repayment_lamports=1_000_000,
        ),
    )

    report = evaluate_pr209_atomic_evidence(complete_evidence(semantic_effects=effects))

    assert "PR209_REPAYMENT_EFFECT_MISMATCH" in codes(report)


def test_rejects_flash_loan_repayment_formula_mismatch():
    report = evaluate_pr209_atomic_evidence(
        complete_evidence(
            economics=IntegerEconomics(
                principal_lamports=1_000_000,
                flash_fee_lamports=3_000,
                repayment_lamports=1_000_000,
                expected_output_lamports=1_050_000,
                total_transaction_fee_lamports=5_000,
                rent_lamports=2_000,
                tip_lamports=1_000,
                transfer_fee_lamports=500,
                contingency_lamports=1_000,
                minimum_profit_lamports=10_000,
            )
        )
    )

    assert "PR209_REPAYMENT_FORMULA_MISMATCH" in codes(report)


def test_rejects_simulation_success_with_error_code():
    evidence = complete_evidence(
        simulation=SimulationBinding(
            success=True,
            error_code="InstructionError",
            sig_verify_enabled=True,
            exact_message_hash=h("d"),
            exact_signed_payload_hash=h("e"),
            raw_account_state_hash=h("9"),
            account_delta_hash=h("a"),
            logs_hash=h("b"),
            units_consumed=120_000,
            total_transaction_fee_lamports=5_000,
        )
    )

    report = evaluate_pr209_atomic_evidence(evidence)

    assert "PR209_SIMULATION_SUCCESS_ERROR_CONFLICT" in codes(report)


def test_requires_sigverify_or_local_signature_verification_binding():
    base = complete_evidence().simulation
    evidence = complete_evidence(
        simulation=SimulationBinding(
            success=base.success,
            error_code=base.error_code,
            sig_verify_enabled=False,
            exact_message_hash=base.exact_message_hash,
            exact_signed_payload_hash=base.exact_signed_payload_hash,
            raw_account_state_hash=base.raw_account_state_hash,
            account_delta_hash=base.account_delta_hash,
            logs_hash=base.logs_hash,
            units_consumed=base.units_consumed,
            total_transaction_fee_lamports=base.total_transaction_fee_lamports,
        )
    )

    report = evaluate_pr209_atomic_evidence(evidence)

    assert "PR209_SIMULATION_SIGVERIFY_REQUIRED" in codes(report)


def test_rejects_fee_that_is_not_exact_total_transaction_fee():
    evidence = complete_evidence(
        fee_accounting=FeeAccounting(projected_total_transaction_fee_lamports=1)
    )

    report = evaluate_pr209_atomic_evidence(evidence)

    assert "PR209_PROJECTED_FEE_NOT_SIMULATION_FEE" in codes(report)
    assert report.state == PR209GateState.BLOCKED
