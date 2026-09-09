from __future__ import annotations

from dataclasses import replace

import pytest

from src.errors import FailureCategory
from src.errors.deadline import Deadline
from src.errors.retry import decide
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
    validate_transition,
)


def _digest(ch: str) -> str:
    return ch * 64


def _bundle() -> ExecutionTruthBundle:
    rooted = RootedCandidateRef(
        candidate_id="mpr2606-candidate",
        candidate_truth_hash=_digest("a"),
        cluster_genesis_hash=_digest("b"),
        admission_hash=_digest("c"),
        root_slot=100,
    )
    plan = PlanRef.create(
        candidate_truth_hash=rooted.candidate_truth_hash,
        principal_lamports=1_000,
        expires_block_height=500,
    )
    compiled = CompiledMessageRef(
        message_hash=_digest("e"),
        plan_hash=plan.plan_hash,
        blockhash="mpr2606-blockhash",
        last_valid_block_height=500,
        alt_hashes=(_digest("f"),),
    )
    simulation = SimulationRef(
        simulation_hash=_digest("1"),
        message_hash=compiled.message_hash,
        context_slot=100,
        fee_lamports=5,
        units_consumed=1,
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
        attempt_id="mpr2606-attempt",
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


def test_success_requires_successful_simulation_directly() -> None:
    bundle = _bundle()
    with pytest.raises(ExecutionTruthError, match="SUCCESS_REQUIRES_SUCCESSFUL_SIMULATION"):
        replace(bundle, simulation=replace(bundle.simulation, successful=False))


@pytest.mark.parametrize(("height", "accepted"), ((499, True), (500, True), (501, False)))
def test_message_expiry_boundary(height: int, accepted: bool) -> None:
    bundle = _bundle()
    compiled = replace(bundle.compiled, last_valid_block_height=height)
    if accepted:
        replace(bundle, compiled=compiled)
    else:
        with pytest.raises(ExecutionTruthError, match="MESSAGE_OUTLIVES_CANDIDATE"):
            replace(bundle, compiled=compiled)


@pytest.mark.parametrize(("slot", "accepted"), ((99, False), (100, True), (101, True)))
def test_simulation_root_slot_boundary(slot: int, accepted: bool) -> None:
    bundle = _bundle()
    simulation = replace(bundle.simulation, context_slot=slot)
    if accepted:
        replace(bundle, simulation=simulation)
    else:
        with pytest.raises(ExecutionTruthError, match="SIMULATION_PRECEDES_ROOTED_CANDIDATE"):
            replace(bundle, simulation=simulation)


def test_durable_candidate_identity_is_bound() -> None:
    bundle = _bundle()
    with pytest.raises(ExecutionTruthError, match="DURABLE_CANDIDATE_MISMATCH"):
        replace(bundle, durable=replace(bundle.durable, candidate_truth_hash=_digest("9")))


def _transition_pair() -> tuple[DurableAttemptRef, DurableAttemptRef]:
    bundle = _bundle()
    previous = DurableAttemptRef(
        attempt_id="mpr2606-transition",
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
    current = replace(
        previous,
        lifecycle_revision=2,
        stage=ExecutionStage.PLANNED,
        plan_hash=bundle.plan.plan_hash,
    )
    return previous, current


def test_transition_generation_is_immutable() -> None:
    previous, current = _transition_pair()
    with pytest.raises(ExecutionTruthError, match="GENERATION_CHANGED"):
        validate_transition(previous, replace(current, generation=2))


@pytest.mark.parametrize(("remaining", "allowed"), ((1.0, True), (0.0, False), (-1.0, False)))
def test_retry_remaining_time_boundary(remaining: float, allowed: bool) -> None:
    decision = decide(
        operation_class="safe_read",
        category=FailureCategory.PROVIDER_TRANSIENT,
        attempt=0,
        remaining_seconds=remaining,
    )
    assert decision.allowed is allowed


@pytest.mark.parametrize(("attempt", "allowed"), ((2, True), (3, False), (4, False)))
def test_retry_attempt_limit_boundary(attempt: int, allowed: bool) -> None:
    decision = decide(
        operation_class="safe_read",
        category=FailureCategory.PROVIDER_TRANSIENT,
        attempt=attempt,
        remaining_seconds=1.0,
    )
    assert decision.allowed is allowed


def test_deadline_expired_boundary() -> None:
    now = [10.0]
    deadline = Deadline.after(1.0, clock=lambda: now[0])
    assert deadline.expired is False
    now[0] = 11.0
    assert deadline.expired is True
    now[0] = 12.0
    assert deadline.expired is True


def test_plan_ref_rejects_bool_with_matching_hash() -> None:
    with pytest.raises(ExecutionTruthError, match="non-bool integer"):
        PlanRef.create(
            candidate_truth_hash=_digest("a"),
            principal_lamports=True,
            expires_block_height=500,
        )
