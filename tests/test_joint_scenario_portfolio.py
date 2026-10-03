import pytest
from src.research.pr356_allocation import (
    solve_opportunity_portfolio,
    verify_portfolio_feasibility,
)
from src.mechanism_discovery.pr356_contracts import PR356ContractError


def problem():
    return {
        "candidates": [
            {
                "candidate_id": cid,
                "expected_utility_units": utility,
                "tail_loss_units": 0,
                "resource_usage": {"positions": 1},
            }
            for cid, utility in (("A", 9), ("B", 8), ("C", 7))
        ],
        "budget": {"positions": 2},
        "max_tail_loss_units": 10,
        "risk_unit": "synthetic-USD-micros",
        "scenario_cvar_confidence_ppm": 500000,
        "scenario_loss_vectors": {"A": (10, 0), "B": (10, 0), "C": (0, 10)},
    }


def test_common_tail_risk_and_diversification_are_evaluated_jointly():
    inputs = problem()
    result = solve_opportunity_portfolio(inputs)
    assert result.candidate_ids == ("A", "C")
    assert result.expected_utility_units == 16
    assert result.tail_loss_units == 10
    assert "EQUAL_WEIGHT_EMPIRICAL_JOINT_CVAR" in result.evidence_refs
    assert verify_portfolio_feasibility(result, inputs)["feasible"]
    assert not result.execution_right
    assert (
        solve_opportunity_portfolio({**inputs, "max_tail_loss_units": 9}).candidate_ids
        == ()
    )


def test_fractional_tail_mass_rounds_conservatively_and_invalid_vectors_block():
    inputs = problem()
    inputs["candidates"] = inputs["candidates"][:1]
    inputs["scenario_loss_vectors"] = {"A": (10, 0)}
    inputs["scenario_cvar_confidence_ppm"] = 250000
    assert solve_opportunity_portfolio(inputs).tail_loss_units == 7
    for changes in (
        {"scenario_cvar_confidence_ppm": True},
        {"scenario_loss_vectors": {"A": (10, False)}},
        {"risk_unit": ""},
        {"scenario_loss_vectors": {}},
    ):
        with pytest.raises(PR356ContractError):
            solve_opportunity_portfolio({**inputs, **changes})


def test_feasibility_recomputes_proposal_economics_and_unknown_ids():
    from dataclasses import replace

    inputs = problem()
    result = solve_opportunity_portfolio(inputs)
    assert not verify_portfolio_feasibility(
        replace(result, expected_utility_units=999), inputs
    )["feasible"]
    with pytest.raises(PR356ContractError, match="UNKNOWN_CANDIDATE"):
        verify_portfolio_feasibility(
            replace(result, candidate_ids=("unknown",)), inputs
        )


@pytest.mark.parametrize("bad", [True, 1.5, -1])
def test_budget_builder_cannot_launder_invalid_units(bad):
    from src.research.pr356_allocation import build_opportunity_portfolio_problem

    with pytest.raises(PR356ContractError):
        build_opportunity_portfolio_problem(problem()["candidates"], {"positions": bad})
