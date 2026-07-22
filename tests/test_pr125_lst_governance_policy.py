from __future__ import annotations

import copy
import json
from pathlib import Path

from src.lst_governance_pr125 import evaluate_pr125_lst_governance_policy, main


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _load_policy(repo_root: Path) -> dict[str, object]:
    raw = repo_root / "src/resources/lst_governance_pr125.json"
    return json.loads(raw.read_text(encoding="utf-8"))


def _load_universe(repo_root: Path) -> dict[str, object]:
    raw = repo_root / "src/resources/discovery_universe.json"
    return json.loads(raw.read_text(encoding="utf-8"))


def test_pr125_default_policy_is_valid_but_lst_execution_disabled() -> None:
    result = evaluate_pr125_lst_governance_policy(repo_root=".")

    symbols = {decision.symbol for decision in result.asset_decisions}
    reasons: set[str] = set()
    for decision in result.asset_decisions:
        reasons.update(decision.reasons)

    assert result.policy_valid is True
    assert result.lst_execution_ready is False
    assert symbols == {"JitoSOL", "mSOL", "bSOL"}
    assert all(not decision.execution_allowed for decision in result.asset_decisions)
    assert all(not decision.execution_allowed for decision in result.pair_decisions)
    assert "PR125_LST_EXECUTION_DISABLED_UNTIL_REVIEWED_EVIDENCE" in result.warnings
    assert "PR125_ORACLE_MODEL_NOT_REVIEWED" in reasons
    assert "PR125_REDEMPTION_MODEL_NOT_REVIEWED" in reasons
    assert "PR125_DEPLOYMENT_ATTESTATION_NOT_REVIEWED" in reasons


def test_pr125_fair_value_strategy_cannot_use_only_dex_quotes(tmp_path: Path) -> None:
    policy = _load_policy(Path("."))
    universe = _load_universe(Path("."))
    mutated = copy.deepcopy(policy)
    for strategy in mutated["strategies"]:
        if strategy["strategy_id"] == "lst_fair_value_depeg":
            strategy["price_sources"] = ["dex_route_quote"]

    _write_json(tmp_path / "policy.json", mutated)
    _write_json(tmp_path / "universe.json", universe)

    result = evaluate_pr125_lst_governance_policy(
        repo_root=tmp_path,
        policy_path="policy.json",
        universe_path="universe.json",
    )

    assert result.policy_valid is False
    assert "PR125_FAIR_VALUE_USES_DEX_ONLY" in result.blockers


def test_pr125_required_lst_pair_is_policy_blocker(tmp_path: Path) -> None:
    policy = _load_policy(Path("."))
    universe = _load_universe(Path("."))
    mutated_universe = copy.deepcopy(universe)
    for pair in mutated_universe["pairs"]:
        if pair["pair_id"] == "sol-jitosol-loop":
            pair["required"] = True

    _write_json(tmp_path / "policy.json", policy)
    _write_json(tmp_path / "universe.json", mutated_universe)

    result = evaluate_pr125_lst_governance_policy(
        repo_root=tmp_path,
        policy_path="policy.json",
        universe_path="universe.json",
    )

    assert result.policy_valid is False
    assert "PR125_REQUIRED_LST_PAIR_FORBIDDEN:sol-jitosol-loop" in result.blockers


def test_pr125_exposure_caps_must_default_zero(tmp_path: Path) -> None:
    policy = _load_policy(Path("."))
    universe = _load_universe(Path("."))
    mutated = copy.deepcopy(policy)
    mutated["assets"][0]["max_asset_exposure_pct"] = 3

    _write_json(tmp_path / "policy.json", mutated)
    _write_json(tmp_path / "universe.json", universe)

    result = evaluate_pr125_lst_governance_policy(
        repo_root=tmp_path,
        policy_path="policy.json",
        universe_path="universe.json",
    )

    first = next(
        decision for decision in result.asset_decisions if decision.symbol == "JitoSOL"
    )
    assert "PR125_ASSET_EXPOSURE_MUST_DEFAULT_ZERO" in first.reasons
    assert result.lst_execution_ready is False


def test_pr125_cli_succeeds_for_structurally_valid_fail_closed_default() -> None:
    assert main(["--repo-root", ".", "--json"]) == 0
    assert main(["--repo-root", ".", "--require-lst-execution-ready"]) == 1
