"""PR-359 / Wave 15 INST-01 autonomous market-institution research vertical.

This module implements a deliberately narrow, deterministic and offline-only
procurement institution on top of the existing PR-358/AGG-14 research owners.
It never signs, submits, transfers funds, mutates remote state, or claims live
market demand/profitability.

Implemented scope:
- immutable institution/rule/task/offer/allocation/verification contracts;
- fixed-eligibility posted-price, reverse first-price and capped reverse
  critical-price procurement for one homogeneous service;
- a semantic evidence resolver layered on AGG-14 DataEvidenceApi metadata;
- a deterministic sum-int-v1 service runner and independent recomputation;
- one-obligation lifecycle with HELD_UNKNOWN and duplicate-close protection;
- finite unilateral report enumeration for first/critical price baselines.

This is INST-01 finite research evidence, not a general incentive-compatibility
proof, a production marketplace, or authorization for live execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from itertools import product
import json
from typing import Any, Iterable, Mapping, Sequence

from src.research.product import DataEvidenceApi, DataEvidenceArtifact, DataEvidenceKind
from src.research.pr358_contracts import canonical_hash


class Wave15InstitutionError(ValueError):
    """Stable fail-closed error for the bounded Wave 15 institution slice."""


def _text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Wave15InstitutionError(code)
    return value


def _money(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Wave15InstitutionError(code)
    return value


def _positive(value: int, code: str) -> int:
    _money(value, code)
    if value == 0:
        raise Wave15InstitutionError(code)
    return value


def _bool(value: bool, code: str) -> bool:
    if type(value) is not bool:
        raise Wave15InstitutionError(code)
    return value


@dataclass(frozen=True, slots=True)
class InstitutionSpec:
    institution_id: str
    service_id: str
    money_unit: str = "synthetic-unit"
    synthetic_only: bool = True
    execution_right: bool = False

    def __post_init__(self) -> None:
        _text(self.institution_id, "W15_INSTITUTION_ID_REQUIRED")
        _text(self.service_id, "W15_SERVICE_ID_REQUIRED")
        _text(self.money_unit, "W15_MONEY_UNIT_REQUIRED")
        if self.synthetic_only is not True or self.execution_right:
            raise Wave15InstitutionError("W15_OFFLINE_BOUNDARY_REQUIRED")


@dataclass(frozen=True, slots=True)
class RuleSnapshot:
    rule_id: str
    generation: int
    mechanism: str
    reserve_units: int
    posted_price_units: int | None = None
    invitation_order: tuple[str, ...] = ()
    tie_policy: str = "supplier_id_asc"
    fixed_eligibility: bool = True

    def __post_init__(self) -> None:
        _text(self.rule_id, "W15_RULE_ID_REQUIRED")
        _positive(self.generation, "W15_RULE_GENERATION_POSITIVE_REQUIRED")
        if self.mechanism not in {"posted_price", "first_price", "critical_price"}:
            raise Wave15InstitutionError("W15_UNKNOWN_MECHANISM")
        _money(self.reserve_units, "W15_RESERVE_INTEGER_REQUIRED")
        if self.tie_policy != "supplier_id_asc":
            raise Wave15InstitutionError("W15_TIE_POLICY_NOT_PRECOMMITTED")
        if self.fixed_eligibility is not True:
            raise Wave15InstitutionError("W15_FIXED_ELIGIBILITY_REQUIRED")
        if len(set(self.invitation_order)) != len(self.invitation_order):
            raise Wave15InstitutionError("W15_DUPLICATE_INVITATION_ID")
        for supplier_id in self.invitation_order:
            _text(supplier_id, "W15_INVITATION_ID_REQUIRED")
        if self.mechanism == "posted_price":
            if self.posted_price_units is None:
                raise Wave15InstitutionError("W15_POSTED_PRICE_REQUIRED")
            _money(self.posted_price_units, "W15_POSTED_PRICE_INTEGER_REQUIRED")
            if self.posted_price_units > self.reserve_units:
                raise Wave15InstitutionError("W15_POSTED_PRICE_EXCEEDS_RESERVE")
            if not self.invitation_order:
                raise Wave15InstitutionError("W15_INVITATION_ORDER_REQUIRED")
        elif self.posted_price_units is not None:
            raise Wave15InstitutionError("W15_POSTED_PRICE_ONLY_FOR_POSTED_RULE")

    @property
    def rule_hash(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True, slots=True)
class AgentProfile:
    supplier_id: str
    service_id: str
    eligible: bool = True

    def __post_init__(self) -> None:
        _text(self.supplier_id, "W15_SUPPLIER_ID_REQUIRED")
        _text(self.service_id, "W15_AGENT_SERVICE_ID_REQUIRED")
        _bool(self.eligible, "W15_ELIGIBLE_BOOL_REQUIRED")


@dataclass(frozen=True, slots=True)
class InformationView:
    view_id: str
    task_id: str
    access_scope: str
    visible_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.view_id, "W15_VIEW_ID_REQUIRED")
        _text(self.task_id, "W15_VIEW_TASK_ID_REQUIRED")
        _text(self.access_scope, "W15_VIEW_SCOPE_REQUIRED")
        if not self.visible_fields or len(set(self.visible_fields)) != len(
            self.visible_fields
        ):
            raise Wave15InstitutionError("W15_VIEW_FIELDS_INVALID")
        for field_name in self.visible_fields:
            _text(field_name, "W15_VIEW_FIELD_REQUIRED")


@dataclass(frozen=True, slots=True)
class ServiceTask:
    task_id: str
    service_id: str
    state_hash: str
    rule_hash: str
    budget_units: int
    deadline: int
    input_values: tuple[int, ...]
    service_kind: str = "sum-int-v1"
    synthetic: bool = True

    def __post_init__(self) -> None:
        _text(self.task_id, "W15_TASK_ID_REQUIRED")
        _text(self.service_id, "W15_TASK_SERVICE_ID_REQUIRED")
        _text(self.state_hash, "W15_STATE_HASH_REQUIRED")
        _text(self.rule_hash, "W15_TASK_RULE_HASH_REQUIRED")
        _money(self.budget_units, "W15_TASK_BUDGET_INTEGER_REQUIRED")
        _money(self.deadline, "W15_TASK_DEADLINE_INTEGER_REQUIRED")
        if self.service_kind != "sum-int-v1":
            raise Wave15InstitutionError("W15_UNSUPPORTED_SERVICE_KIND")
        if not self.input_values:
            raise Wave15InstitutionError("W15_TASK_INPUT_REQUIRED")
        for value in self.input_values:
            if isinstance(value, bool) or not isinstance(value, int):
                raise Wave15InstitutionError("W15_TASK_INPUT_INTEGER_REQUIRED")
        if self.synthetic is not True:
            raise Wave15InstitutionError("W15_INST01_SYNTHETIC_TASK_REQUIRED")


@dataclass(frozen=True, slots=True)
class Offer:
    task_id: str
    supplier_id: str
    price_units: int

    def __post_init__(self) -> None:
        _text(self.task_id, "W15_OFFER_TASK_ID_REQUIRED")
        _text(self.supplier_id, "W15_OFFER_SUPPLIER_ID_REQUIRED")
        _money(self.price_units, "W15_OFFER_PRICE_INTEGER_REQUIRED")


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    task_id: str
    rule_hash: str
    mechanism: str
    winner_id: str | None
    payment_units: int
    reserve_units: int
    reason: str
    offer_set_hash: str
    trace_hash: str
    synthetic: bool = True
    execution_right: bool = False

    def __post_init__(self) -> None:
        _text(self.task_id, "W15_ALLOCATION_TASK_ID_REQUIRED")
        _text(self.rule_hash, "W15_ALLOCATION_RULE_HASH_REQUIRED")
        _money(self.payment_units, "W15_PAYMENT_INTEGER_REQUIRED")
        _money(self.reserve_units, "W15_ALLOCATION_RESERVE_INTEGER_REQUIRED")
        _text(self.reason, "W15_ALLOCATION_REASON_REQUIRED")
        _text(self.offer_set_hash, "W15_OFFER_SET_HASH_REQUIRED")
        _text(self.trace_hash, "W15_TRACE_HASH_REQUIRED")
        if self.winner_id is not None:
            _text(self.winner_id, "W15_WINNER_ID_REQUIRED")
        if self.payment_units > self.reserve_units:
            raise Wave15InstitutionError("W15_PAYMENT_EXCEEDS_RESERVE")
        if self.synthetic is not True or self.execution_right:
            raise Wave15InstitutionError("W15_ALLOCATION_EFFECT_BOUNDARY")


@dataclass(frozen=True, slots=True)
class ResourceCommitment:
    obligation_id: str
    task_id: str
    supplier_id: str
    reserved_units: int
    state: str

    def __post_init__(self) -> None:
        _text(self.obligation_id, "W15_OBLIGATION_ID_REQUIRED")
        _text(self.task_id, "W15_OBLIGATION_TASK_ID_REQUIRED")
        _text(self.supplier_id, "W15_OBLIGATION_SUPPLIER_ID_REQUIRED")
        _money(self.reserved_units, "W15_OBLIGATION_RESERVE_INTEGER_REQUIRED")
        if self.state not in {"AWARDED", "ACCEPTED", "HELD_UNKNOWN", "CLOSED"}:
            raise Wave15InstitutionError("W15_OBLIGATION_STATE_INVALID")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    artifact_id: str
    version: str
    artifact_sha256: str

    def __post_init__(self) -> None:
        _text(self.artifact_id, "W15_EVIDENCE_ID_REQUIRED")
        _text(self.version, "W15_EVIDENCE_VERSION_REQUIRED")
        if (
            not isinstance(self.artifact_sha256, str)
            or len(self.artifact_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.artifact_sha256)
        ):
            raise Wave15InstitutionError("W15_EVIDENCE_SHA256_REQUIRED")


@dataclass(frozen=True, slots=True)
class EvidencePayload:
    artifact_id: str
    version: str
    task_id: str
    state_hash: str
    rule_hash: str
    supplier_id: str
    body_json: str
    claims_actual_pnl: bool = False
    finalized_economic_proof: bool = False

    def __post_init__(self) -> None:
        for value, code in (
            (self.artifact_id, "W15_PAYLOAD_ID_REQUIRED"),
            (self.version, "W15_PAYLOAD_VERSION_REQUIRED"),
            (self.task_id, "W15_PAYLOAD_TASK_ID_REQUIRED"),
            (self.state_hash, "W15_PAYLOAD_STATE_HASH_REQUIRED"),
            (self.rule_hash, "W15_PAYLOAD_RULE_HASH_REQUIRED"),
            (self.supplier_id, "W15_PAYLOAD_SUPPLIER_ID_REQUIRED"),
            (self.body_json, "W15_PAYLOAD_BODY_REQUIRED"),
        ):
            _text(value, code)
        _bool(self.claims_actual_pnl, "W15_PNL_CLAIM_BOOL_REQUIRED")
        _bool(
            self.finalized_economic_proof,
            "W15_FINALIZED_ECONOMIC_PROOF_BOOL_REQUIRED",
        )

    @property
    def artifact_sha256(self) -> str:
        return sha256(self.body_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SemanticVerification:
    status: str
    reason: str
    completed_at: int | None
    expected_result: int
    observed_result: int | None
    actual_pnl_claimed: bool = False
    external_economic_success: bool = False


@dataclass(frozen=True, slots=True)
class VerificationReceipt:
    task_id: str
    supplier_id: str
    status: str
    reason: str
    payable_units: int | None
    refund_units: int
    reservation_held_units: int
    evidence_ref: EvidenceRef | None
    payment_is_real: bool = False
    execution_right: bool = False
    actual_pnl_claimed: bool = False

    def __post_init__(self) -> None:
        _text(self.task_id, "W15_RECEIPT_TASK_ID_REQUIRED")
        _text(self.supplier_id, "W15_RECEIPT_SUPPLIER_ID_REQUIRED")
        _text(self.status, "W15_RECEIPT_STATUS_REQUIRED")
        _text(self.reason, "W15_RECEIPT_REASON_REQUIRED")
        if self.payable_units is not None:
            _money(self.payable_units, "W15_RECEIPT_PAYABLE_INTEGER_REQUIRED")
        _money(self.refund_units, "W15_RECEIPT_REFUND_INTEGER_REQUIRED")
        _money(self.reservation_held_units, "W15_RECEIPT_HELD_INTEGER_REQUIRED")
        if self.payment_is_real or self.execution_right or self.actual_pnl_claimed:
            raise Wave15InstitutionError("W15_RECEIPT_LIVE_CLAIM_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class InstitutionEpisode:
    episode_id: str
    task_id: str
    events: tuple[str, ...]
    trace_hash: str


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    experiment_id: str
    reserve_units: int
    true_cost_grid: tuple[int, ...]
    report_grid: tuple[int, ...]
    opponent_policy: str = "truthful"


@dataclass(frozen=True, slots=True)
class InstitutionVerdict:
    verdict: str
    scope: str
    total_unilateral_checks: int
    first_price_counterexample_found: bool
    critical_price_max_tested_gain: int
    production_ready: bool = False
    live_enabled: bool = False


@dataclass(frozen=True, slots=True)
class _BidRow:
    supplier_id: str
    price_units: int


def _eligible_rows(
    *,
    task: ServiceTask,
    rules: RuleSnapshot,
    profiles: Sequence[AgentProfile],
    offers: Sequence[Offer],
) -> tuple[_BidRow, ...]:
    if task.rule_hash != rules.rule_hash:
        raise Wave15InstitutionError("W15_TASK_RULE_BINDING_MISMATCH")
    if rules.reserve_units > task.budget_units:
        raise Wave15InstitutionError("W15_RESERVE_EXCEEDS_TASK_BUDGET")

    by_supplier: dict[str, AgentProfile] = {}
    for profile in profiles:
        if profile.supplier_id in by_supplier:
            raise Wave15InstitutionError("W15_DUPLICATE_AGENT_PROFILE")
        if profile.service_id != task.service_id:
            continue
        by_supplier[profile.supplier_id] = profile

    seen: set[str] = set()
    rows: list[_BidRow] = []
    for offer in offers:
        if offer.task_id != task.task_id:
            raise Wave15InstitutionError("W15_OFFER_TASK_BINDING_MISMATCH")
        if offer.supplier_id in seen:
            raise Wave15InstitutionError("W15_DUPLICATE_SUPPLIER_OFFER")
        seen.add(offer.supplier_id)
        profile = by_supplier.get(offer.supplier_id)
        if profile is None:
            raise Wave15InstitutionError("W15_OFFER_SUPPLIER_NOT_REGISTERED")
        if not profile.eligible or offer.price_units > rules.reserve_units:
            continue
        rows.append(_BidRow(offer.supplier_id, offer.price_units))
    return tuple(rows)


def allocate_service(
    *,
    task: ServiceTask,
    rules: RuleSnapshot,
    profiles: Sequence[AgentProfile],
    offers: Sequence[Offer],
) -> AllocationDecision:
    """Allocate one homogeneous service under a frozen rule snapshot."""

    rows = _eligible_rows(task=task, rules=rules, profiles=profiles, offers=offers)
    offer_set_hash = canonical_hash(
        [asdict(row) for row in sorted(rows, key=lambda row: row.supplier_id)]
    )

    winner: _BidRow | None = None
    payment = 0
    if rules.mechanism == "posted_price":
        assert rules.posted_price_units is not None
        by_id = {
            row.supplier_id: row
            for row in rows
            if row.price_units <= rules.posted_price_units
        }
        for supplier_id in rules.invitation_order:
            candidate = by_id.get(supplier_id)
            if candidate is not None:
                winner = candidate
                break
        if winner is not None:
            payment = rules.posted_price_units
    else:
        ranked = sorted(rows, key=lambda row: (row.price_units, row.supplier_id))
        if ranked:
            winner = ranked[0]
            if rules.mechanism == "first_price":
                payment = winner.price_units
            else:
                payment = (
                    ranked[1].price_units if len(ranked) > 1 else rules.reserve_units
                )

    reason = "AWARDED" if winner is not None else "NO_ACCEPTABLE_OFFER"
    trace_payload = {
        "task_id": task.task_id,
        "rule_hash": rules.rule_hash,
        "mechanism": rules.mechanism,
        "winner_id": None if winner is None else winner.supplier_id,
        "payment_units": payment,
        "reserve_units": rules.reserve_units,
        "reason": reason,
        "offer_set_hash": offer_set_hash,
    }
    return AllocationDecision(
        task_id=task.task_id,
        rule_hash=rules.rule_hash,
        mechanism=rules.mechanism,
        winner_id=None if winner is None else winner.supplier_id,
        payment_units=payment,
        reserve_units=rules.reserve_units,
        reason=reason,
        offer_set_hash=offer_set_hash,
        trace_hash=canonical_hash(trace_payload),
    )


def supplier_utility(
    decision: AllocationDecision, supplier_id: str, true_cost: int
) -> int:
    _text(supplier_id, "W15_UTILITY_SUPPLIER_ID_REQUIRED")
    _money(true_cost, "W15_TRUE_COST_INTEGER_REQUIRED")
    return (
        decision.payment_units - true_cost if decision.winner_id == supplier_id else 0
    )


def welfare(
    decision: AllocationDecision,
    *,
    buyer_value_units: int,
    true_costs: Mapping[str, int],
) -> Mapping[str, int]:
    """Evaluator-only synthetic welfare; internal payment cancels as a transfer."""

    _money(buyer_value_units, "W15_BUYER_VALUE_INTEGER_REQUIRED")
    for supplier_id, cost in true_costs.items():
        _text(supplier_id, "W15_COST_SUPPLIER_ID_REQUIRED")
        _money(cost, "W15_TRUE_COST_INTEGER_REQUIRED")
    if decision.winner_id is None:
        return {
            "buyer_utility": 0,
            "supplier_utility": 0,
            "social_welfare": 0,
            "transfer_sum": 0,
        }
    if decision.winner_id not in true_costs:
        raise Wave15InstitutionError("W15_WINNER_TRUE_COST_MISSING")
    buyer = buyer_value_units - decision.payment_units
    supplier = decision.payment_units - true_costs[decision.winner_id]
    return {
        "buyer_utility": buyer,
        "supplier_utility": supplier,
        "social_welfare": buyer + supplier,
        "transfer_sum": 0,
    }


def execute_service(
    *,
    task: ServiceTask,
    supplier_id: str,
    completed_at: int,
    result_override: int | None = None,
) -> str:
    """Run the provider-visible deterministic service without hidden evaluator fields."""

    _text(supplier_id, "W15_EXECUTION_SUPPLIER_ID_REQUIRED")
    _money(completed_at, "W15_COMPLETED_AT_INTEGER_REQUIRED")
    result = sum(task.input_values) if result_override is None else result_override
    if isinstance(result, bool) or not isinstance(result, int):
        raise Wave15InstitutionError("W15_SERVICE_RESULT_INTEGER_REQUIRED")
    return json.dumps(
        {
            "service_kind": task.service_kind,
            "task_id": task.task_id,
            "state_hash": task.state_hash,
            "rule_hash": task.rule_hash,
            "supplier_id": supplier_id,
            "result_value": result,
            "completed_at": completed_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def build_evidence(
    *,
    task: ServiceTask,
    supplier_id: str,
    body_json: str,
    artifact_id: str,
    version: str = "v1",
    evidence_kind: DataEvidenceKind = DataEvidenceKind.SIMULATED,
    access_scope: str = "research",
    claims_actual_pnl: bool = False,
    finalized_economic_proof: bool = False,
) -> tuple[DataEvidenceArtifact, EvidencePayload, EvidenceRef]:
    payload = EvidencePayload(
        artifact_id=artifact_id,
        version=version,
        task_id=task.task_id,
        state_hash=task.state_hash,
        rule_hash=task.rule_hash,
        supplier_id=supplier_id,
        body_json=body_json,
        claims_actual_pnl=claims_actual_pnl,
        finalized_economic_proof=finalized_economic_proof,
    )
    artifact = DataEvidenceArtifact(
        artifact_id=artifact_id,
        version=version,
        artifact_sha256=payload.artifact_sha256,
        provenance_sha256=canonical_hash(
            {
                "task_id": task.task_id,
                "state_hash": task.state_hash,
                "rule_hash": task.rule_hash,
                "supplier_id": supplier_id,
            }
        ),
        evidence_kind=evidence_kind,
        distribution_allowed=True,
        access_scopes=(access_scope,),
        max_queries_per_lease=16,
    )
    ref = EvidenceRef(
        artifact_id=artifact_id,
        version=version,
        artifact_sha256=payload.artifact_sha256,
    )
    return artifact, payload, ref


class SemanticEvidenceResolver:
    """Semantic layer over AGG-14 evidence admission/rights/query-budget policy."""

    def __init__(
        self,
        *,
        api: DataEvidenceApi,
        payloads: Iterable[EvidencePayload],
    ) -> None:
        self._api = api
        self._payloads: dict[str, EvidencePayload] = {}
        for payload in payloads:
            prior = self._payloads.get(payload.artifact_id)
            if prior is not None and prior != payload:
                raise Wave15InstitutionError("W15_EVIDENCE_PAYLOAD_ID_CONFLICT")
            self._payloads[payload.artifact_id] = payload

    def resolve(
        self,
        *,
        evidence_ref: EvidenceRef,
        task: ServiceTask,
        expected_supplier_id: str,
        lease_id: str,
        access_scope: str,
    ) -> SemanticVerification:
        metadata = self._api.read(
            artifact_id=evidence_ref.artifact_id,
            lease_id=lease_id,
            access_scope=access_scope,
        )
        payload = self._payloads.get(evidence_ref.artifact_id)
        if payload is None:
            raise Wave15InstitutionError("W15_EVIDENCE_BYTES_MISSING")
        if (
            metadata.version != evidence_ref.version
            or payload.version != evidence_ref.version
            or metadata.artifact_sha256 != evidence_ref.artifact_sha256
            or payload.artifact_sha256 != evidence_ref.artifact_sha256
        ):
            return SemanticVerification(
                status="REJECTED_SYNTHETIC",
                reason="HASH_OR_VERSION_MISMATCH",
                completed_at=None,
                expected_result=sum(task.input_values),
                observed_result=None,
            )

        if (
            payload.task_id != task.task_id
            or payload.state_hash != task.state_hash
            or payload.rule_hash != task.rule_hash
            or payload.supplier_id != expected_supplier_id
        ):
            return SemanticVerification(
                status="REJECTED_SYNTHETIC",
                reason="BINDING_MISMATCH",
                completed_at=None,
                expected_result=sum(task.input_values),
                observed_result=None,
            )

        if payload.claims_actual_pnl and not payload.finalized_economic_proof:
            return SemanticVerification(
                status="REJECTED_SYNTHETIC",
                reason="ECONOMIC_CLAIM_UNFINALIZED",
                completed_at=None,
                expected_result=sum(task.input_values),
                observed_result=None,
            )

        try:
            body = json.loads(payload.body_json)
        except json.JSONDecodeError:
            return SemanticVerification(
                status="REJECTED_SYNTHETIC",
                reason="MALFORMED_EVIDENCE_JSON",
                completed_at=None,
                expected_result=sum(task.input_values),
                observed_result=None,
            )
        if not isinstance(body, dict):
            return SemanticVerification(
                status="REJECTED_SYNTHETIC",
                reason="EVIDENCE_OBJECT_REQUIRED",
                completed_at=None,
                expected_result=sum(task.input_values),
                observed_result=None,
            )

        binding = {
            "service_kind": task.service_kind,
            "task_id": task.task_id,
            "state_hash": task.state_hash,
            "rule_hash": task.rule_hash,
            "supplier_id": expected_supplier_id,
        }
        if any(body.get(key) != expected for key, expected in binding.items()):
            return SemanticVerification(
                status="REJECTED_SYNTHETIC",
                reason="BODY_BINDING_MISMATCH",
                completed_at=None,
                expected_result=sum(task.input_values),
                observed_result=None,
            )

        completed_at = body.get("completed_at")
        observed = body.get("result_value")
        if (
            isinstance(completed_at, bool)
            or not isinstance(completed_at, int)
            or completed_at < 0
            or isinstance(observed, bool)
            or not isinstance(observed, int)
        ):
            return SemanticVerification(
                status="REJECTED_SYNTHETIC",
                reason="EVIDENCE_NUMERIC_TYPE_INVALID",
                completed_at=None,
                expected_result=sum(task.input_values),
                observed_result=None,
            )
        expected = sum(task.input_values)
        if completed_at > task.deadline:
            return SemanticVerification(
                status="LATE",
                reason="LATE",
                completed_at=completed_at,
                expected_result=expected,
                observed_result=observed,
            )
        if observed != expected:
            return SemanticVerification(
                status="REJECTED_SYNTHETIC",
                reason="SEMANTIC_VALIDATION_FAILED",
                completed_at=completed_at,
                expected_result=expected,
                observed_result=observed,
            )
        return SemanticVerification(
            status="ACCEPTED_SYNTHETIC",
            reason="VALID_TIMELY_BOUND_AND_RECOMPUTED",
            completed_at=completed_at,
            expected_result=expected,
            observed_result=observed,
            actual_pnl_claimed=False,
            external_economic_success=False,
        )


class InstitutionRuntime:
    """In-memory research lifecycle with one allocation/obligation per task."""

    def __init__(self) -> None:
        self._decisions: dict[str, AllocationDecision] = {}
        self._commitments: dict[str, ResourceCommitment] = {}
        self._receipts: dict[str, VerificationReceipt] = {}

    def award_once(
        self,
        *,
        task: ServiceTask,
        rules: RuleSnapshot,
        profiles: Sequence[AgentProfile],
        offers: Sequence[Offer],
    ) -> AllocationDecision:
        if task.task_id in self._decisions:
            raise Wave15InstitutionError("W15_TASK_ALREADY_ALLOCATED")
        decision = allocate_service(
            task=task,
            rules=rules,
            profiles=profiles,
            offers=offers,
        )
        self._decisions[task.task_id] = decision
        if decision.winner_id is not None:
            self._commitments[task.task_id] = ResourceCommitment(
                obligation_id=f"obligation:{task.task_id}",
                task_id=task.task_id,
                supplier_id=decision.winner_id,
                reserved_units=decision.payment_units,
                state="AWARDED",
            )
        return decision

    def accept(self, *, task_id: str, supplier_id: str) -> ResourceCommitment:
        commitment = self._commitments.get(task_id)
        if commitment is None:
            raise Wave15InstitutionError("W15_OBLIGATION_NOT_FOUND")
        if commitment.supplier_id != supplier_id:
            raise Wave15InstitutionError("W15_OBLIGATION_SUPPLIER_MISMATCH")
        if commitment.state != "AWARDED":
            raise Wave15InstitutionError("W15_OBLIGATION_NOT_AWARDABLE")
        accepted = replace(commitment, state="ACCEPTED")
        self._commitments[task_id] = accepted
        return accepted

    def settle(
        self,
        *,
        task: ServiceTask,
        resolver: SemanticEvidenceResolver | None,
        evidence_ref: EvidenceRef | None,
        outcome: str,
        lease_id: str = "inst01",
        access_scope: str = "research",
    ) -> VerificationReceipt:
        if task.task_id in self._receipts:
            raise Wave15InstitutionError("W15_TASK_ALREADY_CLOSED")
        commitment = self._commitments.get(task.task_id)
        if commitment is None:
            raise Wave15InstitutionError("W15_OBLIGATION_NOT_FOUND")
        if commitment.state not in {"ACCEPTED", "HELD_UNKNOWN"}:
            raise Wave15InstitutionError("W15_OBLIGATION_NOT_ACCEPTED")
        if outcome not in {"delivered", "unknown"}:
            raise Wave15InstitutionError("W15_OUTCOME_INVALID")

        if outcome == "unknown":
            held = replace(commitment, state="HELD_UNKNOWN")
            self._commitments[task.task_id] = held
            return VerificationReceipt(
                task_id=task.task_id,
                supplier_id=commitment.supplier_id,
                status="HELD_UNKNOWN",
                reason="UNKNOWN_NOT_SUCCESS_OR_FAILURE",
                payable_units=None,
                refund_units=0,
                reservation_held_units=commitment.reserved_units,
                evidence_ref=None,
            )

        if resolver is None or evidence_ref is None:
            raise Wave15InstitutionError("W15_DELIVERY_EVIDENCE_REQUIRED")
        verification = resolver.resolve(
            evidence_ref=evidence_ref,
            task=task,
            expected_supplier_id=commitment.supplier_id,
            lease_id=lease_id,
            access_scope=access_scope,
        )
        accepted = verification.status == "ACCEPTED_SYNTHETIC"
        receipt = VerificationReceipt(
            task_id=task.task_id,
            supplier_id=commitment.supplier_id,
            status=verification.status,
            reason=verification.reason,
            payable_units=commitment.reserved_units if accepted else 0,
            refund_units=0 if accepted else commitment.reserved_units,
            reservation_held_units=0,
            evidence_ref=evidence_ref,
        )
        self._receipts[task.task_id] = receipt
        self._commitments[task.task_id] = replace(commitment, state="CLOSED")
        return receipt


def enumerate_unilateral_deviations(mechanism: str) -> Mapping[str, Any]:
    """Finite unilateral reports versus truthful opponents; not equilibrium search."""

    if mechanism not in {"first_price", "critical_price"}:
        raise Wave15InstitutionError("W15_DEVIATION_MECHANISM_UNSUPPORTED")
    rules = RuleSnapshot(
        rule_id=f"finite-{mechanism}",
        generation=1,
        mechanism=mechanism,
        reserve_units=5,
    )
    supplier_ids = ("A", "B", "C")
    profiles = tuple(AgentProfile(supplier_id, "svc") for supplier_id in supplier_ids)
    checks = 0
    positive_checks = 0
    profiles_with_positive = 0
    max_gain = 0
    first_counterexample: Mapping[str, Any] | None = None
    for costs in product(range(1, 6), repeat=3):
        task = ServiceTask(
            task_id="finite-task",
            service_id="svc",
            state_hash="finite-state",
            rule_hash=rules.rule_hash,
            budget_units=5,
            deadline=10,
            input_values=(1,),
        )
        honest = tuple(
            Offer(task.task_id, supplier_id, cost)
            for supplier_id, cost in zip(supplier_ids, costs, strict=True)
        )
        reference = allocate_service(
            task=task,
            rules=rules,
            profiles=profiles,
            offers=honest,
        )
        profile_has = False
        for index, supplier_id in enumerate(supplier_ids):
            base = supplier_utility(reference, supplier_id, costs[index])
            for report in range(7):
                altered = list(honest)
                altered[index] = Offer(task.task_id, supplier_id, report)
                alternative = allocate_service(
                    task=task,
                    rules=rules,
                    profiles=profiles,
                    offers=tuple(altered),
                )
                alt = supplier_utility(alternative, supplier_id, costs[index])
                gain = max(0, alt - base)
                checks += 1
                if gain:
                    positive_checks += 1
                    profile_has = True
                    if first_counterexample is None:
                        first_counterexample = {
                            "costs": dict(zip(supplier_ids, costs, strict=True)),
                            "deviating_supplier": supplier_id,
                            "report": report,
                            "reference": asdict(reference),
                            "alternative": asdict(alternative),
                            "reference_utility": base,
                            "alternative_utility": alt,
                            "gain": gain,
                        }
                max_gain = max(max_gain, gain)
        profiles_with_positive += int(profile_has)
    return {
        "mechanism": mechanism,
        "cost_profiles": 125,
        "unilateral_checks": checks,
        "positive_gain_checks": positive_checks,
        "profiles_with_positive_gain": profiles_with_positive,
        "max_tested_gain": max_gain,
        "first_counterexample": first_counterexample,
        "true_cost_grid": [1, 2, 3, 4, 5],
        "report_grid": list(range(7)),
        "opponent_policy": "truthful",
        "reserve_units": 5,
        "scope": "FINITE_DOMAIN_ONLY_NOT_GLOBAL_IC_CERTIFICATE",
    }


def _task(*, task_id: str, rules: RuleSnapshot, values: tuple[int, ...]) -> ServiceTask:
    return ServiceTask(
        task_id=task_id,
        service_id="verified-sum",
        state_hash=canonical_hash({"task_id": task_id, "values": values}),
        rule_hash=rules.rule_hash,
        budget_units=rules.reserve_units,
        deadline=10,
        input_values=values,
    )


def run_inst01_vertical() -> Mapping[str, Any]:
    """Run the merged Wave 15 INST-01 finite offline research vertical."""

    institution = InstitutionSpec(
        institution_id="wave15-inst01",
        service_id="verified-sum",
    )
    critical = RuleSnapshot(
        rule_id="inst01-critical",
        generation=1,
        mechanism="critical_price",
        reserve_units=5,
    )
    task = _task(task_id="inst01-task-accepted", rules=critical, values=(2, 3, 5))
    profiles = tuple(
        AgentProfile(supplier_id, institution.service_id)
        for supplier_id in ("A", "B", "C")
    )
    offers = tuple(
        Offer(task.task_id, supplier_id, price)
        for supplier_id, price in (("A", 2), ("B", 3), ("C", 5))
    )
    runtime = InstitutionRuntime()
    decision = runtime.award_once(
        task=task,
        rules=critical,
        profiles=profiles,
        offers=offers,
    )
    assert decision.winner_id is not None
    runtime.accept(task_id=task.task_id, supplier_id=decision.winner_id)

    correct_body = execute_service(
        task=task,
        supplier_id=decision.winner_id,
        completed_at=9,
    )
    artifact, payload, ref = build_evidence(
        task=task,
        supplier_id=decision.winner_id,
        body_json=correct_body,
        artifact_id="inst01-correct-result",
    )
    resolver = SemanticEvidenceResolver(
        api=DataEvidenceApi((artifact,)),
        payloads=(payload,),
    )
    accepted_receipt = runtime.settle(
        task=task,
        resolver=resolver,
        evidence_ref=ref,
        outcome="delivered",
    )

    wrong_body = execute_service(
        task=task,
        supplier_id=decision.winner_id,
        completed_at=9,
        result_override=11,
    )
    wrong_artifact, wrong_payload, wrong_ref = build_evidence(
        task=task,
        supplier_id=decision.winner_id,
        body_json=wrong_body,
        artifact_id="inst01-wrong-well-hashed-result",
    )
    wrong_verification = SemanticEvidenceResolver(
        api=DataEvidenceApi((wrong_artifact,)),
        payloads=(wrong_payload,),
    ).resolve(
        evidence_ref=wrong_ref,
        task=task,
        expected_supplier_id=decision.winner_id,
        lease_id="wrong",
        access_scope="research",
    )

    unknown_task = _task(
        task_id="inst01-task-unknown",
        rules=critical,
        values=(1, 4),
    )
    unknown_offers = tuple(
        Offer(unknown_task.task_id, supplier_id, price)
        for supplier_id, price in (("A", 2), ("B", 3), ("C", 5))
    )
    unknown_decision = runtime.award_once(
        task=unknown_task,
        rules=critical,
        profiles=profiles,
        offers=unknown_offers,
    )
    assert unknown_decision.winner_id is not None
    runtime.accept(
        task_id=unknown_task.task_id,
        supplier_id=unknown_decision.winner_id,
    )
    unknown_receipt = runtime.settle(
        task=unknown_task,
        resolver=None,
        evidence_ref=None,
        outcome="unknown",
    )

    first = enumerate_unilateral_deviations("first_price")
    critical_result = enumerate_unilateral_deviations("critical_price")
    verdict = InstitutionVerdict(
        verdict="PASS_FINITE_INST01",
        scope="OFFLINE_SYNTHETIC_HOMOGENEOUS_SERVICE_ONLY",
        total_unilateral_checks=first["unilateral_checks"]
        + critical_result["unilateral_checks"],
        first_price_counterexample_found=first["max_tested_gain"] > 0,
        critical_price_max_tested_gain=critical_result["max_tested_gain"],
    )
    report: dict[str, Any] = {
        "roadmap_id": "PR-359",
        "wave": 15,
        "vertical": "INST-01",
        "institution": asdict(institution),
        "allocation": asdict(decision),
        "accepted_receipt": asdict(accepted_receipt),
        "wrong_well_hashed_verification": asdict(wrong_verification),
        "unknown_receipt": asdict(unknown_receipt),
        "deviations": {
            "first_price": first,
            "critical_price": critical_result,
        },
        "verdict": asdict(verdict),
        "effect_boundary": {
            "production_ready": False,
            "live_enabled": False,
            "execution_right": False,
            "signer_access": False,
            "submission_access": False,
            "wallet_access": False,
            "remote_mutation": False,
            "customer_billing": False,
            "payment_is_real": False,
            "actual_pnl_claimed": False,
        },
        "known_limits": (
            "fixed bid-independent eligibility",
            "homogeneous deterministic service",
            "synthetic integer accounting",
            "no strategic quality/effort model",
            "no Sybil/collusion proof",
            "no external demand/revenue evidence",
            "no real settlement or live execution",
            "finite deviation grid is not a global IC certificate",
        ),
    }
    report["integrated_receipt_hash"] = canonical_hash(report)
    return report


__all__ = [
    "AgentProfile",
    "AllocationDecision",
    "EvidencePayload",
    "EvidenceRef",
    "ExperimentSpec",
    "InformationView",
    "InstitutionEpisode",
    "InstitutionRuntime",
    "InstitutionSpec",
    "InstitutionVerdict",
    "Offer",
    "ResourceCommitment",
    "RuleSnapshot",
    "SemanticEvidenceResolver",
    "SemanticVerification",
    "ServiceTask",
    "VerificationReceipt",
    "Wave15InstitutionError",
    "allocate_service",
    "build_evidence",
    "enumerate_unilateral_deviations",
    "execute_service",
    "run_inst01_vertical",
    "supplier_utility",
    "welfare",
]
