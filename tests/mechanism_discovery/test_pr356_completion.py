from __future__ import annotations

from scripts.verify_pr356_completion import verify
from src.research.pr356_integrated_loop import run_integrated_science_fixture


def test_pr356_corrective_completion_verifier() -> None:
    result = verify()
    assert result["accepted"], result["errors"]
    assert result["requirements"] == 544
    assert result["corrective_residual_contracts"] == 391
    assert result["not_run"] == 0
    assert result["execution_right"] is False


def test_integrated_science_receipt_is_deterministic_and_research_only() -> None:
    first = run_integrated_science_fixture()
    second = run_integrated_science_fixture()
    assert first["integrated_receipt_hash"] == second["integrated_receipt_hash"]
    assert first["research_only"] is True
    assert first["execution_right"] is False
    assert first["external_qualification"] is False
    assert len(first["portfolio"]["strategy_cards"]) == 3
    assert first["portfolio"]["feasibility"]["feasible"] is True
