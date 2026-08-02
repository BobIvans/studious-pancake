from __future__ import annotations

from dataclasses import replace

import pytest

from src.execution_truth import (
    CompiledMessageRef,
    DurableAttemptRef,
    ExecutionStage,
    ExecutionTruthBundle,
    ExecutionTruthError,
    PlanRef,
    ReconciliationRef,
    RootedCandidateRef,
    SimulationRef,
    TerminalState,
    evaluate_bundle,
    terminalize_ambiguous,
    validate_transition,
)


def _digest(character: str) -> str:
    return character * 64


def _bundle() -> ExecutionTruthBundle:
    rooted = RootedCandidateRef(
        candidate_id="candidate-1",
        candidate_truth_hash=_digest("a"),
        cluster_genesis_hash=_digest("b"),
        admission_hash=_digest("c"),
        root_slot=100,
    )
    plan = PlanRef(
        plan_hash=_digest("d"),
        candidate_truth_hash=rooted.candidate_truth_hash,
        principal_lamports=1_000,
        expires_block_height=500,
    )
    compiled = CompiledMessageRef(
        message_hash=_digest("e"),
        plan_hash=plan.plan_hash,
        blockhash="blockhash-1",
        last_valid_block_height=450,
        alt_hashes=(_digest("f"),),
    )
    simulation = SimulationRef(
        simulation_hash=_digest("1"),
        message_hash=compiled.message_hash,
        context_slot=110,
        fee_lamports=5,
        units_consumed=123_456,
        logs_hash=_digest("2"),
        successful=True,
    )
    reconciliation = ReconciliationRef(
        reconciliation_hash=_digest("3"),
        simulation_hash=simulation.simulation_hash,
        message_hash=compiled.message_hash,
        principal_lamports=1_000,
        gross_proceeds_lamports=1_200,
        flash_repayment_lamports=50,
        network_fee_lamports=5,
        rent_delta_lamports=10,
        tip_lamports=5,
        uncertainty_buffer_lamports=10,
        conservative_surplus_lamports=120,
    )
    durable = DurableAttemptRef(
        attempt_id="attempt-1",
        generation=1,
        lifecycle_revision=6,
        stage=ExecutionStage.TERMINAL,
        terminal_state=TerminalState.SUCCESS,
        writer_fence=7,
        event_head_hash=_digest("4"),
        idempotency_hash=_digest("5"),
        reservation_hash=_digest("6"),
        candidate_truth_hash=rooted.candidate_truth_hash,
        plan_hash=plan.plan_hash,
        message_hash=compiled.message_hash,
        simulation_hash=simulation.simulation_hash,
        reconciliation_hash=reconciliation.reconciliation_hash,
    )
    return ExecutionTruthBundle(
        rooted=rooted,
        plan=plan,
        compiled=compiled,
        simulation=simulation,
        reconciliation=reconciliation,
        durable=durable,
    )


def test_valid_execution_truth_bundle_is_sender_free_and_not_production_ready() -> None:
    report = evaluate_bundle(_bundle())

    assert report["accepted"] is True
    assert report["execution_truth_ready"] is True
    assert report["sender_free"] is True
    assert report["live_enabled"] is False
    assert report["production_ready"] is False


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("candidate", _digest("9")),
        ("plan", _digest("8")),
        ("message", _digest("7")),
        ("simulation", _digest("6")),
        ("reconciliation", _digest("5")),
    ),
)
def test_cross_stage_digest_mutation_fails_closed(
    field: str,
    replacement: str,
) -> None:
    bundle = _bundle()
    if field == "candidate":
        plan = replace(bundle.plan, candidate_truth_hash=replacement)
        with pytest.raises(
            ExecutionTruthError,
            match="PLAN_CANDIDATE_MISMATCH",
        ):
            replace(bundle, plan=plan)
    elif field == "plan":
        compiled = replace(bundle.compiled, plan_hash=replacement)
        with pytest.raises(
            ExecutionTruthError,
            match="MESSAGE_PLAN_MISMATCH",
        ):
            replace(bundle, compiled=compiled)
    elif field == "message":
        simulation = replace(bundle.simulation, message_hash=replacement)
        with pytest.raises(
            ExecutionTruthError,
            match="SIMULATION_MESSAGE_MISMATCH",
        ):
            replace(bundle, simulation=simulation)
    elif field == "simulation":
        reconciliation = replace(
            bundle.reconciliation,
            simulation_hash=replacement,
        )
        with pytest.raises(
            ExecutionTruthError,
            match="RECONCILIATION_SIMULATION_MISMATCH",
        ):
            replace(bundle, reconciliation=reconciliation)
    else:
        durable = replace(
            bundle.durable,
            reconciliation_hash=replacement,
        )
        with pytest.raises(
            ExecutionTruthError,
            match="DURABLE_RECONCILIATION_MISMATCH",
        ):
            replace(bundle, durable=durable)


def test_reconciliation_requires_exact_integer_arithmetic() -> None:
    bundle = _bundle()
    with pytest.raises(
        ExecutionTruthError,
        match="RECONCILIATION_ARITHMETIC_MISMATCH",
    ):
        replace(
            bundle.reconciliation,
            conservative_surplus_lamports=121,
        )


def test_success_requires_positive_conservative_surplus() -> None:
    bundle = _bundle()
    reconciliation = ReconciliationRef(
        reconciliation_hash=_digest("3"),
        simulation_hash=bundle.simulation.simulation_hash,
        message_hash=bundle.compiled.message_hash,
        principal_lamports=1_000,
        gross_proceeds_lamports=1_080,
        flash_repayment_lamports=50,
        network_fee_lamports=5,
        rent_delta_lamports=10,
        tip_lamports=5,
        uncertainty_buffer_lamports=10,
        conservative_surplus_lamports=0,
    )
    with pytest.raises(
        ExecutionTruthError,
        match="SUCCESS_REQUIRES_POSITIVE_SURPLUS",
    ):
        replace(bundle, reconciliation=reconciliation)


def test_transition_requires_contiguous_revision_and_stable_writer_fence() -> None:
    bundle = _bundle()
    rooted = DurableAttemptRef(
        attempt_id=bundle.durable.attempt_id,
        generation=1,
        lifecycle_revision=1,
        stage=ExecutionStage.ROOTED,
        terminal_state=TerminalState.NONE,
        writer_fence=7,
        event_head_hash=_digest("4"),
        idempotency_hash=_digest("5"),
        reservation_hash=_digest("6"),
        candidate_truth_hash=bundle.rooted.candidate_truth_hash,
    )
    planned = replace(
        rooted,
        lifecycle_revision=2,
        stage=ExecutionStage.PLANNED,
        plan_hash=bundle.plan.plan_hash,
    )
    validate_transition(rooted, planned)

    with pytest.raises(
        ExecutionTruthError,
        match="REVISION_NOT_CONTIGUOUS",
    ):
        validate_transition(rooted, replace(planned, lifecycle_revision=3))
    with pytest.raises(
        ExecutionTruthError,
        match="WRITER_FENCE_CHANGED",
    ):
        validate_transition(rooted, replace(planned, writer_fence=8))


def test_terminal_state_is_immutable() -> None:
    bundle = _bundle()
    with pytest.raises(
        ExecutionTruthError,
        match="TERMINAL_STATE_IS_IMMUTABLE",
    ):
        validate_transition(
            bundle.durable,
            replace(
                bundle.durable,
                lifecycle_revision=7,
                terminal_state=TerminalState.FAILURE,
            ),
        )


def test_unknown_post_simulation_effect_is_quarantined_as_ambiguous() -> None:
    bundle = _bundle()
    simulated = replace(
        bundle.durable,
        lifecycle_revision=5,
        stage=ExecutionStage.SIMULATED,
        terminal_state=TerminalState.NONE,
        reconciliation_hash=None,
    )
    ambiguous = terminalize_ambiguous(simulated)

    validate_transition(simulated, ambiguous)
    assert ambiguous.terminal_state is TerminalState.AMBIGUOUS
    assert ambiguous.ambiguity_quarantined is True


def test_post_compile_cancelled_terminal_is_rejected() -> None:
    bundle = _bundle()
    with pytest.raises(
        ExecutionTruthError,
        match="POST_COMPILE_CANCELLATION_IS_AMBIGUOUS",
    ):
        replace(
            bundle,
            durable=replace(
                bundle.durable,
                terminal_state=TerminalState.CANCELLED,
                reconciliation_hash=None,
            ),
            reconciliation=None,
        )


def test_bool_is_not_accepted_as_integer() -> None:
    with pytest.raises(ExecutionTruthError, match="non-bool integer"):
        PlanRef(
            plan_hash=_digest("d"),
            candidate_truth_hash=_digest("a"),
            principal_lamports=True,
            expires_block_height=500,
        )
