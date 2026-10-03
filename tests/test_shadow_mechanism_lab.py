from src.research.shadow_mechanism_lab import (
    demand_response,
    run_finite_mechanism_controls,
)


def test_fee_and_subsidy_change_participation_instead_of_freezing_flow():
    demand = (("a", 1), ("b", 3), ("c", 5))
    rows = demand_response(willingness_to_pay=demand, fees=(1, 3, 5, 6))
    assert tuple(len(r.participating_ids) for r in rows) == (3, 2, 1, 0)
    result = run_finite_mechanism_controls(
        willingness_to_pay=demand, fees=(6,), subsidy_units=5
    )
    assert len(result["elastic"][0].participating_ids) == 3
    assert not result["subsidy_removed"][0].participating_ids
    assert not result["execution_right"]
