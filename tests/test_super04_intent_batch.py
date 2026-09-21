from __future__ import annotations

import pytest
from solders.instruction import Instruction
from solders.pubkey import Pubkey

from src.execution.models import PlannedInstruction, TransactionPlan
from src.planning.intent_batch import (
    AtomicIntentChild,
    ChildAttribution,
    ChildCostInput,
    FinalizedParentEvidence,
    IntentBatchError,
    ParentFinality,
    ResourceFootprint,
    admit_atomic_intent_batch,
    allocate_batch_costs_and_floors,
    canonical_transaction_plan_hash,
    compose_atomic_parent_plan,
    settle_atomic_parent_children,
)

H3 = "3" * 64
H4 = "4" * 64


def _plan(payer: Pubkey, marker: int) -> TransactionPlan:
    ix = Instruction(Pubkey.new_unique(), bytes([marker]), ())
    return TransactionPlan(
        opportunity_id=f"child-{marker}",
        payer=payer,
        instructions=(
            PlannedInstruction(
                ix,
                role="application",
                name=f"ix-{marker}",
            ),
        ),
        required_signers=(payer,),
        quote_slot=100,
        market_state_slot=100,
    )


def _children() -> tuple[AtomicIntentChild, AtomicIntentChild]:
    payer = Pubkey.new_unique()
    plan_a = _plan(payer, 1)
    plan_b = _plan(payer, 2)
    return (
        AtomicIntentChild(
            child_id="a",
            plan_hash=canonical_transaction_plan_hash(plan_a),
            state_identity_hash=H3,
            authority_scope_hash=H4,
            lender_composition_id="slumlord+jupiter",
            expires_at_ms=10_000,
            plan=plan_a,
            footprint=ResourceFootprint(
                sequential_state_resources=("pool:x",)
            ),
        ),
        AtomicIntentChild(
            child_id="b",
            plan_hash=canonical_transaction_plan_hash(plan_b),
            state_identity_hash=H3,
            authority_scope_hash=H4,
            lender_composition_id="slumlord+jupiter",
            expires_at_ms=10_000,
            plan=plan_b,
            footprint=ResourceFootprint(
                sequential_state_resources=("pool:x",)
            ),
        ),
    )


def test_nf333_membership_order_is_immutable_and_state_bound() -> None:
    children = _children()
    first = admit_atomic_intent_batch(children, now_ms=1)
    second = admit_atomic_intent_batch(
        tuple(reversed(children)),
        now_ms=1,
    )
    assert first.membership_hash != second.membership_hash
    assert first.live_enabled is False

    changed_plan = children[1].plan
    bad = (
        children[0],
        AtomicIntentChild(
            child_id="b",
            plan_hash=canonical_transaction_plan_hash(changed_plan),
            state_identity_hash="5" * 64,
            authority_scope_hash=H4,
            lender_composition_id="slumlord+jupiter",
            expires_at_ms=10_000,
            plan=changed_plan,
        ),
    )
    with pytest.raises(IntentBatchError, match="SHARED_STATE_CONFLICT"):
        admit_atomic_intent_batch(bad, now_ms=1)


def test_nf333_child_plan_hash_cannot_lie_about_membership() -> None:
    children = _children()
    with pytest.raises(IntentBatchError, match="CHILD_PLAN_HASH_MISMATCH"):
        AtomicIntentChild(
            child_id="tampered",
            plan_hash="9" * 64,
            state_identity_hash=H3,
            authority_scope_hash=H4,
            lender_composition_id="slumlord+jupiter",
            expires_at_ms=10_000,
            plan=children[0].plan,
        )


def test_nf333_exclusive_resource_conflict_rejected() -> None:
    children = _children()
    conflict = tuple(
        AtomicIntentChild(
            child_id=child.child_id,
            plan_hash=child.plan_hash,
            state_identity_hash=child.state_identity_hash,
            authority_scope_hash=child.authority_scope_hash,
            lender_composition_id=child.lender_composition_id,
            expires_at_ms=child.expires_at_ms,
            plan=child.plan,
            footprint=ResourceFootprint(
                exclusive_resources=("nonce:1",)
            ),
        )
        for child in children
    )
    with pytest.raises(IntentBatchError, match="SHARED_STATE_CONFLICT"):
        admit_atomic_intent_batch(conflict, now_ms=1)


def test_nf334_parent_plan_preserves_child_blocks() -> None:
    children = _children()
    proposal = admit_atomic_intent_batch(children, now_ms=1)
    parent = compose_atomic_parent_plan(
        proposal=proposal,
        children=children,
        ordering_proof_hash="6" * 64,
        maximum_application_instructions=8,
    )
    assert [
        bytes(item.instruction.data)
        for item in parent.transaction_plan.instructions
    ] == [b"\x01", b"\x02"]
    assert parent.transaction_plan.opportunity_id.startswith("batch:")
    assert parent.child_instruction_ranges == (
        ("a", 0, 1),
        ("b", 1, 2),
    )


def test_nf335_integer_cost_allocation_has_residual_and_floors() -> None:
    proposal = admit_atomic_intent_batch(_children(), now_ms=1)
    allocation = allocate_batch_costs_and_floors(
        proposal=proposal,
        costs=(
            ChildCostInput("a", 1, 100, 40),
            ChildCostInput("b", 1, 100, 40),
        ),
        parent_total_cost_lamports=21,
        residual_owner_id="b",
    )
    assert [
        item.allocated_cost_lamports for item in allocation.children
    ] == [10, 11]
    assert (
        sum(
            item.allocated_cost_lamports
            for item in allocation.children
        )
        == 21
    )

    with pytest.raises(IntentBatchError, match="CHILD_FLOOR_FAILED"):
        allocate_batch_costs_and_floors(
            proposal=proposal,
            costs=(
                ChildCostInput("a", 1, 10, 5),
                ChildCostInput("b", 1, 10, 5),
            ),
            parent_total_cost_lamports=20,
            residual_owner_id="b",
        )


def test_nf336_unknown_parent_blocks_child_release_and_labels() -> None:
    children = _children()
    proposal = admit_atomic_intent_batch(children, now_ms=1)
    parent = compose_atomic_parent_plan(
        proposal=proposal,
        children=children,
        ordering_proof_hash="6" * 64,
        maximum_application_instructions=8,
    )
    allocation = allocate_batch_costs_and_floors(
        proposal=proposal,
        costs=(
            ChildCostInput("a", 1, 100, 0),
            ChildCostInput("b", 1, 100, 0),
        ),
        parent_total_cost_lamports=20,
        residual_owner_id="b",
    )
    unknown = settle_atomic_parent_children(
        parent=parent,
        allocation=allocation,
        evidence=FinalizedParentEvidence(
            parent_plan_hash=parent.parent_plan_hash,
            membership_hash=proposal.membership_hash,
            finality=ParentFinality.UNKNOWN,
            actual_parent_cost_lamports=None,
            attribution_evidence_hash=None,
        ),
    )
    assert unknown.release_children is False
    assert unknown.qualifying_child_labels is False

    finalized = settle_atomic_parent_children(
        parent=parent,
        allocation=allocation,
        evidence=FinalizedParentEvidence(
            parent_plan_hash=parent.parent_plan_hash,
            membership_hash=proposal.membership_hash,
            finality=ParentFinality.FINALIZED,
            actual_parent_cost_lamports=20,
            attribution_evidence_hash="7" * 64,
            child_attributions=(
                ChildAttribution("a", 90),
                ChildAttribution("b", 90),
            ),
        ),
    )
    assert finalized.release_children is True
    assert finalized.qualifying_child_labels is True
