from dataclasses import replace
import pytest
from tests.test_exact_cpmm_capacity import _three_hop_plan, NOW
from src.strategy.exact_cpmm_capacity import evaluate_exact_cpmm_route
from src.research.shadow_calculation_market import (
    RouteCalculationOffer,
    procure_route_calculation,
)


def test_independent_validation_total_cost_latency_and_price_competition():
    plan = _three_hop_plan()
    route = evaluate_exact_cpmm_route(plan, input_amount=20, now=NOW)
    good = RouteCalculationOffer(
        "good", route.evaluation_id, route.conservative_output, 5, 1, 10
    )
    offers = (
        good,
        replace(good, supplier_id="bad", output_atoms=9999, quoted_cost_units=0),
        replace(good, supplier_id="slow", latency_ns=100, quoted_cost_units=0),
        replace(good, supplier_id="second", quoted_cost_units=7),
    )
    result = procure_route_calculation(
        plan,
        amount=20,
        snapshot_now=NOW,
        offers=offers,
        now_ns=20,
        deadline_ns=30,
        verification_cost_units=2,
        budget_units=20,
    )
    assert result.supplier_id == "good"
    assert result.total_cost_units == 13
    assert result.rejected_ids == ("bad", "slow")
    assert not result.execution_right
    insufficient = procure_route_calculation(
        plan,
        amount=20,
        snapshot_now=NOW,
        offers=offers,
        now_ns=20,
        deadline_ns=30,
        verification_cost_units=2,
        budget_units=10,
    )
    assert insufficient.supplier_id is None
    assert insufficient.total_cost_units == 8
