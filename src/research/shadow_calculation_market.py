"""Read-only route calculation procurement; no payments or external providers.

Uses exact evaluation and existing Wave15 procurement allocation. Local offers
are rejected unless independently recomputed against the requested route/frame.
"""

from dataclasses import dataclass
from src.strategy.exact_cpmm_capacity import (
    ExactCpmmRoutePlan,
    evaluate_exact_cpmm_route,
)
from src.research.pr359_wave15_institution import (
    RuleSnapshot,
    ServiceTask,
    Offer,
    AgentProfile,
    allocate_service,
)


@dataclass(frozen=True, slots=True)
class RouteCalculationOffer:
    supplier_id: str
    evaluation_id: str
    output_atoms: int
    quoted_cost_units: int
    latency_ns: int
    available_at_ns: int

    def __post_init__(self):
        if not self.supplier_id.strip() or len(self.evaluation_id) != 64:
            raise ValueError("offer identity required")
        for field in (
            "output_atoms",
            "quoted_cost_units",
            "latency_ns",
            "available_at_ns",
        ):
            if type(getattr(self, field)) is not int or getattr(self, field) < 0:
                raise ValueError("integer offer terms required")


@dataclass(frozen=True, slots=True)
class CalculationProcurementReceipt:
    supplier_id: str | None
    independently_verified_ids: tuple[str, ...]
    rejected_ids: tuple[str, ...]
    total_cost_units: int
    execution_right: bool = False


def procure_route_calculation(
    plan: ExactCpmmRoutePlan,
    *,
    amount: int,
    snapshot_now: float,
    offers: tuple[RouteCalculationOffer, ...],
    now_ns: int,
    deadline_ns: int,
    verification_cost_units: int,
    budget_units: int,
) -> CalculationProcurementReceipt:
    if len(offers) > 16 or len({o.supplier_id for o in offers}) != len(offers):
        raise ValueError("supplier bound or duplicate")
    for value in (now_ns, deadline_ns, verification_cost_units, budget_units):
        if type(value) is not int or value < 0:
            raise ValueError("integer procurement bounds required")
    expected = evaluate_exact_cpmm_route(plan, input_amount=amount, now=snapshot_now)
    verified = []
    rejected = []
    checking_cost = len(offers) * verification_cost_units
    if checking_cost > budget_units:
        raise ValueError("independent verification budget exceeded")
    for offer in sorted(offers, key=lambda o: o.supplier_id):
        if (
            offer.available_at_ns > now_ns
            or now_ns + offer.latency_ns >= deadline_ns
            or offer.evaluation_id != expected.evaluation_id
            or offer.output_atoms != expected.conservative_output
        ):
            rejected.append(offer.supplier_id)
        else:
            verified.append(offer)
    # The existing institution owns deterministic supplier selection, tie policy
    # and posted/first/critical-price mechanism semantics.
    remaining = budget_units - checking_cost
    if not verified:
        return CalculationProcurementReceipt(None, (), tuple(rejected), checking_cost)
    rules = RuleSnapshot("route-offer-first-price", 1, "first_price", remaining)
    # ServiceTask is used solely for the existing synthetic allocation boundary;
    # its sum-int executor is never called for route verification.
    task = ServiceTask(
        expected.evaluation_id,
        "route-selection",
        expected.evaluation_id,
        rules.rule_hash,
        remaining,
        deadline_ns,
        (0,),
    )
    decision = allocate_service(
        task=task,
        rules=rules,
        profiles=tuple(
            AgentProfile(o.supplier_id, "route-selection") for o in verified
        ),
        offers=tuple(
            Offer(task.task_id, o.supplier_id, o.quoted_cost_units) for o in verified
        ),
    )
    return CalculationProcurementReceipt(
        decision.winner_id,
        tuple(o.supplier_id for o in verified),
        tuple(rejected),
        checking_cost + decision.payment_units,
    )
