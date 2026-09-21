"""SUPER-04 / W2-12 immutable atomic multi-intent parent planning.

A batch combines already-admitted canonical TransactionPlan objects. It is not
the split-flow solver and it does not create a signer, sender or settlement
ledger. Membership/order/cost attribution are explicit evidence and any
mutation produces a new parent identity.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Iterable

from solders.instruction import Instruction
from solders.pubkey import Pubkey

from src.execution.models import PlannedInstruction, TransactionPlan

SUPER04_BATCH_SCHEMA = "super04.atomic-intent-batch.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class IntentBatchError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ParentFinality(StrEnum):
    FINALIZED = "finalized"
    FAILED = "failed"
    UNKNOWN = "unknown"


def _sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise IntentBatchError(f"SUPER04_BATCH_INVALID_{label.upper()}")


def _positive(value: int, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise IntentBatchError(f"SUPER04_BATCH_INVALID_{label.upper()}")


def _nonnegative(value: int, label: str) -> None:
    if type(value) is not int or value < 0:
        raise IntentBatchError(f"SUPER04_BATCH_INVALID_{label.upper()}")


def _signed(value: int, label: str) -> None:
    if type(value) is not int:
        raise IntentBatchError(f"SUPER04_BATCH_INVALID_{label.upper()}")


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise IntentBatchError(f"SUPER04_BATCH_INVALID_{label.upper()}")


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _instruction_json(instruction: Instruction) -> dict[str, object]:
    return {
        "program_id": str(instruction.program_id),
        "data_hex": bytes(instruction.data).hex(),
        "accounts": [
            {
                "pubkey": str(meta.pubkey),
                "signer": meta.is_signer,
                "writable": meta.is_writable,
            }
            for meta in instruction.accounts
        ],
    }


def _plan_identity(plan: TransactionPlan) -> dict[str, object]:
    return {
        "opportunity_id": plan.opportunity_id,
        "payer": str(plan.payer),
        "instructions": [
            {
                "role": item.role,
                "name": item.name,
                "instruction": _instruction_json(item.instruction),
            }
            for item in plan.instructions
        ],
        "compute_budget_policy": asdict(plan.compute_budget_policy),
        "tip_policy": {
            "lamports": plan.tip_policy.lamports,
            "tip_account": (
                None
                if plan.tip_policy.tip_account is None
                else str(plan.tip_policy.tip_account)
            ),
        },
        "required_signers": [str(item) for item in plan.required_signers],
        "lookup_table_addresses": [
            str(item) for item in plan.lookup_table_addresses
        ],
        "required_lookup_addresses": [
            str(item) for item in plan.required_lookup_addresses
        ],
        "quote_slot": plan.quote_slot,
        "market_state_slot": plan.market_state_slot,
        "oracle_slot": plan.oracle_slot,
        "monitored_accounts": [
            str(item) for item in plan.monitored_accounts
        ],
    }


def canonical_transaction_plan_hash(plan: TransactionPlan) -> str:
    """Content-address one canonical child plan for immutable membership."""

    return _hash_json(
        {"schema": SUPER04_BATCH_SCHEMA, "plan": _plan_identity(plan)}
    )


@dataclass(frozen=True, slots=True)
class ResourceFootprint:
    exclusive_resources: tuple[str, ...] = ()
    sequential_state_resources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for values, label in (
            (self.exclusive_resources, "exclusive_resources"),
            (
                self.sequential_state_resources,
                "sequential_state_resources",
            ),
        ):
            if len(set(values)) != len(values):
                raise IntentBatchError(
                    f"SUPER04_BATCH_DUPLICATE_{label.upper()}"
                )
            for value in values:
                _text(value, label)


@dataclass(frozen=True, slots=True)
class AtomicIntentChild:
    child_id: str
    plan_hash: str
    state_identity_hash: str
    authority_scope_hash: str
    lender_composition_id: str
    expires_at_ms: int
    plan: TransactionPlan
    footprint: ResourceFootprint = ResourceFootprint()

    def __post_init__(self) -> None:
        _text(self.child_id, "child_id")
        _sha(self.plan_hash, "plan_hash")
        if self.plan_hash != canonical_transaction_plan_hash(self.plan):
            raise IntentBatchError("CHILD_PLAN_HASH_MISMATCH")
        _sha(self.state_identity_hash, "state_identity_hash")
        _sha(self.authority_scope_hash, "authority_scope_hash")
        _text(self.lender_composition_id, "lender_composition_id")
        _positive(self.expires_at_ms, "expires_at_ms")


@dataclass(frozen=True, slots=True)
class BatchProposal:
    child_ids: tuple[str, ...]
    child_plan_hashes: tuple[str, ...]
    state_identity_hash: str
    authority_scope_hash: str
    lender_composition_id: str
    payer: Pubkey
    required_signers: tuple[Pubkey, ...]
    membership_hash: str
    expires_at_ms: int
    live_enabled: bool = False


def admit_atomic_intent_batch(
    children: tuple[AtomicIntentChild, ...],
    *,
    now_ms: int,
    maximum_children: int = 8,
) -> BatchProposal:
    """NF-333: admit only immutable, authority-compatible children."""

    _nonnegative(now_ms, "now_ms")
    _positive(maximum_children, "maximum_children")
    if len(children) < 2 or len(children) > maximum_children:
        raise IntentBatchError("RESOURCE_LIMIT")
    if len({child.child_id for child in children}) != len(children):
        raise IntentBatchError("DUPLICATE_CHILD_EXECUTION")
    if any(now_ms >= child.expires_at_ms for child in children):
        raise IntentBatchError("EXPIRED_CHILD")

    first = children[0]
    for child in children[1:]:
        if child.state_identity_hash != first.state_identity_hash:
            raise IntentBatchError("SHARED_STATE_CONFLICT")
        if child.authority_scope_hash != first.authority_scope_hash:
            raise IntentBatchError("INCOMPATIBLE_AUTHORITY")
        if child.lender_composition_id != first.lender_composition_id:
            raise IntentBatchError("UNSUPPORTED_LENDER_COMPOSITION")
        if child.plan.payer != first.plan.payer:
            raise IntentBatchError("INCOMPATIBLE_AUTHORITY")
        if child.plan.required_signers != first.plan.required_signers:
            raise IntentBatchError("INCOMPATIBLE_AUTHORITY")
        if (
            child.plan.compute_budget_policy
            != first.plan.compute_budget_policy
        ):
            raise IntentBatchError("RESOURCE_LIMIT")
        if child.plan.tip_policy != first.plan.tip_policy:
            raise IntentBatchError("UNALLOCATED_COST")

    exclusive_seen: set[str] = set()
    for child in children:
        overlap = exclusive_seen.intersection(
            child.footprint.exclusive_resources
        )
        if overlap:
            raise IntentBatchError("SHARED_STATE_CONFLICT")
        exclusive_seen.update(child.footprint.exclusive_resources)

    payload = {
        "schema": SUPER04_BATCH_SCHEMA,
        "child_ids": [child.child_id for child in children],
        "child_plan_hashes": [child.plan_hash for child in children],
        "state_identity_hash": first.state_identity_hash,
        "authority_scope_hash": first.authority_scope_hash,
        "lender_composition_id": first.lender_composition_id,
        "payer": str(first.plan.payer),
        "required_signers": [
            str(item) for item in first.plan.required_signers
        ],
    }
    return BatchProposal(
        child_ids=tuple(child.child_id for child in children),
        child_plan_hashes=tuple(child.plan_hash for child in children),
        state_identity_hash=first.state_identity_hash,
        authority_scope_hash=first.authority_scope_hash,
        lender_composition_id=first.lender_composition_id,
        payer=first.plan.payer,
        required_signers=first.plan.required_signers,
        membership_hash=_hash_json(payload),
        expires_at_ms=min(child.expires_at_ms for child in children),
        live_enabled=False,
    )


def _ordered_unique(items: Iterable[Pubkey]) -> tuple[Pubkey, ...]:
    result: list[Pubkey] = []
    seen: set[Pubkey] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class AtomicParentPlan:
    proposal: BatchProposal
    transaction_plan: TransactionPlan
    ordering_proof_hash: str
    parent_plan_hash: str
    child_instruction_ranges: tuple[tuple[str, int, int], ...]


def compose_atomic_parent_plan(
    *,
    proposal: BatchProposal,
    children: tuple[AtomicIntentChild, ...],
    ordering_proof_hash: str,
    maximum_application_instructions: int,
) -> AtomicParentPlan:
    """NF-334: concatenate immutable child blocks under one canonical plan."""

    _sha(ordering_proof_hash, "ordering_proof_hash")
    _positive(
        maximum_application_instructions,
        "maximum_application_instructions",
    )
    by_id = {child.child_id: child for child in children}
    if (
        set(by_id) != set(proposal.child_ids)
        or len(by_id) != len(children)
    ):
        raise IntentBatchError("MEMBERSHIP_MISMATCH")
    ordered = tuple(by_id[child_id] for child_id in proposal.child_ids)
    if (
        tuple(child.plan_hash for child in ordered)
        != proposal.child_plan_hashes
    ):
        raise IntentBatchError("MEMBERSHIP_MISMATCH")
    if any(
        child.plan.tip_policy != ordered[0].plan.tip_policy
        for child in ordered
    ):
        raise IntentBatchError("UNALLOCATED_COST")

    instructions: list[PlannedInstruction] = []
    ranges: list[tuple[str, int, int]] = []
    for child in ordered:
        start = len(instructions)
        instructions.extend(child.plan.instructions)
        ranges.append((child.child_id, start, len(instructions)))
    if len(instructions) > maximum_application_instructions:
        raise IntentBatchError("RESOURCE_LIMIT")

    first_plan = ordered[0].plan
    parent = TransactionPlan(
        opportunity_id="batch:" + proposal.membership_hash,
        payer=proposal.payer,
        instructions=tuple(instructions),
        compute_budget_policy=first_plan.compute_budget_policy,
        tip_policy=first_plan.tip_policy,
        required_signers=proposal.required_signers,
        lookup_table_addresses=_ordered_unique(
            address
            for child in ordered
            for address in child.plan.lookup_table_addresses
        ),
        required_lookup_addresses=_ordered_unique(
            address
            for child in ordered
            for address in child.plan.required_lookup_addresses
        ),
        quote_slot=max(
            (child.plan.quote_slot or 0 for child in ordered),
            default=0,
        ),
        market_state_slot=max(
            (child.plan.market_state_slot or 0 for child in ordered),
            default=0,
        ),
        oracle_slot=max(
            (child.plan.oracle_slot or 0 for child in ordered),
            default=0,
        ),
        monitored_accounts=_ordered_unique(
            address
            for child in ordered
            for address in child.plan.monitored_accounts
        ),
    )
    payload = {
        "schema": SUPER04_BATCH_SCHEMA,
        "membership_hash": proposal.membership_hash,
        "ordering_proof_hash": ordering_proof_hash,
        "child_ranges": ranges,
        "parent_plan": _plan_identity(parent),
    }
    return AtomicParentPlan(
        proposal=proposal,
        transaction_plan=parent,
        ordering_proof_hash=ordering_proof_hash,
        parent_plan_hash=_hash_json(payload),
        child_instruction_ranges=tuple(ranges),
    )


@dataclass(frozen=True, slots=True)
class ChildCostInput:
    child_id: str
    allocation_weight: int
    net_before_parent_cost_lamports: int
    minimum_net_floor_lamports: int

    def __post_init__(self) -> None:
        _text(self.child_id, "child_id")
        _positive(self.allocation_weight, "allocation_weight")
        _signed(
            self.net_before_parent_cost_lamports,
            "net_before_parent_cost_lamports",
        )
        _signed(
            self.minimum_net_floor_lamports,
            "minimum_net_floor_lamports",
        )


@dataclass(frozen=True, slots=True)
class ChildCostAllocation:
    child_id: str
    allocated_cost_lamports: int
    net_after_parent_cost_lamports: int
    minimum_net_floor_lamports: int


@dataclass(frozen=True, slots=True)
class BatchCostAllocation:
    parent_total_cost_lamports: int
    residual_owner_id: str
    children: tuple[ChildCostAllocation, ...]
    allocation_hash: str


def allocate_batch_costs_and_floors(
    *,
    proposal: BatchProposal,
    costs: tuple[ChildCostInput, ...],
    parent_total_cost_lamports: int,
    residual_owner_id: str,
) -> BatchCostAllocation:
    """NF-335: integer allocation with explicit rounding residual owner."""

    _nonnegative(parent_total_cost_lamports, "parent_total_cost_lamports")
    _text(residual_owner_id, "residual_owner_id")
    by_id = {item.child_id: item for item in costs}
    if (
        set(by_id) != set(proposal.child_ids)
        or len(by_id) != len(costs)
    ):
        raise IntentBatchError("UNALLOCATED_COST")
    if residual_owner_id not in by_id:
        raise IntentBatchError("UNALLOCATED_COST")
    total_weight = sum(item.allocation_weight for item in costs)
    allocations = {
        child_id: (
            parent_total_cost_lamports * item.allocation_weight
            // total_weight
        )
        for child_id, item in by_id.items()
    }
    residual = parent_total_cost_lamports - sum(allocations.values())
    allocations[residual_owner_id] += residual

    rows: list[ChildCostAllocation] = []
    for child_id in proposal.child_ids:
        item = by_id[child_id]
        allocated = allocations[child_id]
        net = item.net_before_parent_cost_lamports - allocated
        if net < item.minimum_net_floor_lamports:
            raise IntentBatchError("CHILD_FLOOR_FAILED")
        rows.append(
            ChildCostAllocation(
                child_id=child_id,
                allocated_cost_lamports=allocated,
                net_after_parent_cost_lamports=net,
                minimum_net_floor_lamports=(
                    item.minimum_net_floor_lamports
                ),
            )
        )
    if (
        sum(row.allocated_cost_lamports for row in rows)
        != parent_total_cost_lamports
    ):
        raise IntentBatchError("UNALLOCATED_COST")
    payload = {
        "schema": SUPER04_BATCH_SCHEMA,
        "membership_hash": proposal.membership_hash,
        "parent_total_cost_lamports": parent_total_cost_lamports,
        "residual_owner_id": residual_owner_id,
        "children": [asdict(row) for row in rows],
    }
    return BatchCostAllocation(
        parent_total_cost_lamports=parent_total_cost_lamports,
        residual_owner_id=residual_owner_id,
        children=tuple(rows),
        allocation_hash=_hash_json(payload),
    )


@dataclass(frozen=True, slots=True)
class ChildAttribution:
    child_id: str
    actual_net_after_allocated_cost_lamports: int

    def __post_init__(self) -> None:
        _text(self.child_id, "child_id")
        _signed(
            self.actual_net_after_allocated_cost_lamports,
            "actual_net_after_allocated_cost_lamports",
        )


@dataclass(frozen=True, slots=True)
class FinalizedParentEvidence:
    parent_plan_hash: str
    membership_hash: str
    finality: ParentFinality
    actual_parent_cost_lamports: int | None
    attribution_evidence_hash: str | None
    child_attributions: tuple[ChildAttribution, ...] = ()

    def __post_init__(self) -> None:
        _sha(self.parent_plan_hash, "parent_plan_hash")
        _sha(self.membership_hash, "membership_hash")
        if self.actual_parent_cost_lamports is not None:
            _nonnegative(
                self.actual_parent_cost_lamports,
                "actual_parent_cost_lamports",
            )
        if self.attribution_evidence_hash is not None:
            _sha(
                self.attribution_evidence_hash,
                "attribution_evidence_hash",
            )


@dataclass(frozen=True, slots=True)
class AtomicParentSettlement:
    parent_plan_hash: str
    membership_hash: str
    finality: ParentFinality
    settlement_hash: str
    release_children: bool
    qualifying_child_labels: bool
    child_attributions: tuple[ChildAttribution, ...]
    reason_code: str


def settle_atomic_parent_children(
    *,
    parent: AtomicParentPlan,
    allocation: BatchCostAllocation,
    evidence: FinalizedParentEvidence,
) -> AtomicParentSettlement:
    """NF-336: project settlement without creating a second ledger."""

    if evidence.parent_plan_hash != parent.parent_plan_hash:
        raise IntentBatchError("MEMBERSHIP_MISMATCH")
    if evidence.membership_hash != parent.proposal.membership_hash:
        raise IntentBatchError("MEMBERSHIP_MISMATCH")
    if evidence.finality is ParentFinality.UNKNOWN:
        if (
            evidence.child_attributions
            or evidence.actual_parent_cost_lamports is not None
        ):
            raise IntentBatchError("AMBIGUOUS_ATTRIBUTION")
        reason = "PARENT_OUTCOME_UNKNOWN"
        qualifying = False
        release = False
    else:
        if evidence.actual_parent_cost_lamports is None:
            raise IntentBatchError("AMBIGUOUS_ATTRIBUTION")
        if (
            evidence.actual_parent_cost_lamports
            != allocation.parent_total_cost_lamports
        ):
            raise IntentBatchError("UNALLOCATED_COST")
        child_ids = tuple(
            item.child_id for item in evidence.child_attributions
        )
        if len(set(child_ids)) != len(child_ids):
            raise IntentBatchError("DUPLICATE_CHILD_EXECUTION")
        if evidence.finality is ParentFinality.FINALIZED:
            if (
                evidence.attribution_evidence_hash is None
                or set(child_ids) != set(parent.proposal.child_ids)
            ):
                reason = "PARENT_ONLY_ATTRIBUTION"
                qualifying = False
            else:
                reason = "CHILD_ATTRIBUTION_VERIFIED"
                qualifying = True
        else:
            reason = "PARENT_FAILED_ATOMICALLY"
            qualifying = False
        release = True

    payload = {
        "schema": SUPER04_BATCH_SCHEMA,
        "parent_plan_hash": parent.parent_plan_hash,
        "membership_hash": parent.proposal.membership_hash,
        "finality": evidence.finality.value,
        "allocation_hash": allocation.allocation_hash,
        "actual_parent_cost_lamports": (
            evidence.actual_parent_cost_lamports
        ),
        "attribution_evidence_hash": (
            evidence.attribution_evidence_hash
        ),
        "child_attributions": [
            asdict(item) for item in evidence.child_attributions
        ],
        "reason_code": reason,
    }
    return AtomicParentSettlement(
        parent_plan_hash=parent.parent_plan_hash,
        membership_hash=parent.proposal.membership_hash,
        finality=evidence.finality,
        settlement_hash=_hash_json(payload),
        release_children=release,
        qualifying_child_labels=qualifying,
        child_attributions=evidence.child_attributions,
        reason_code=reason,
    )


__all__ = [
    "AtomicIntentChild",
    "AtomicParentPlan",
    "AtomicParentSettlement",
    "BatchCostAllocation",
    "BatchProposal",
    "ChildAttribution",
    "ChildCostAllocation",
    "ChildCostInput",
    "FinalizedParentEvidence",
    "IntentBatchError",
    "ParentFinality",
    "ResourceFootprint",
    "SUPER04_BATCH_SCHEMA",
    "admit_atomic_intent_batch",
    "allocate_batch_costs_and_floors",
    "canonical_transaction_plan_hash",
    "compose_atomic_parent_plan",
    "settle_atomic_parent_children",
]
