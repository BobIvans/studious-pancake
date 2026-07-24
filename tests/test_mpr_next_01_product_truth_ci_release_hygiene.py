from __future__ import annotations

import json
from pathlib import Path

from src.mpr_next_01_product_truth_gate import (
    REQUIRED_GATE_IDS,
    evaluate_mpr_next_01,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _product_contract(paths: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": "pr195.product-contract.v1",
        "product_state": "not-production-ready",
        "live_available": False,
        "endpoints": {
            "jupiter": {
                "origin": "https://api.jup.ag",
                "paths": paths or ["/price/v3", "/swap/v2/build"],
                "state": "reviewed-disabled",
            }
        },
    }


def _closure_map() -> dict[str, object]:
    return {
        "schema_version": "mpr-next-01.production-debt-closure-map.v1",
        "production_ready": False,
        "live_enabled": False,
        "policy": {
            "materialized_runtime_evidence_required": True,
            "offline_validators_do_not_close_blockers": True,
        },
        "gates": [
            {
                "gate_id": gate_id,
                "status": "implemented-offline-validator",
                "module_path": f"src/{gate_id.lower().replace('-', '_')}.py",
                "can_close_blocker_ids": [f"{gate_id}.blocker"],
                "required_evidence": [f"{gate_id}.evidence"],
            }
            for gate_id in REQUIRED_GATE_IDS
        ],
    }


def _fixture_repo(root: Path) -> None:
    _write_json(root / "src/resources/production_debt_closure_map.json", _closure_map())
    for rel in (
        "src/resources/product_contract_pr195.json",
        "config/product_contract_pr195.json",
    ):
        _write_json(root / rel, _product_contract())
    _write_text(
        root / ".github/workflows/mpr31-final-promotion-gate.yml",
        """
name: MPR-31
permissions:
  contents: read
jobs:
  gate:
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
        with:
          python-version: '3.13'
""",
    )
    _write_text(
        root / ".github/workflows/pr190-diagnostics.yml",
        """
name: PR-190 diagnostics
permissions:
  contents: read
jobs:
  capture:
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
        with:
          python-version: '3.13'
      - run: python scripts/verify_repo.py > /tmp/pr190-diagnostics.txt
""",
    )


def test_mpr_next_01_accepts_clean_release_surface(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    result = evaluate_mpr_next_01(tmp_path)
    assert result.accepted, result.blockers
    assert result.to_dict()["live_enabled"] is False
    assert result.to_dict()["production_ready"] is False


def test_mpr_next_01_rejects_swap_v1_product_contract(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    _write_json(
        tmp_path / "src/resources/product_contract_pr195.json",
        _product_contract(["/price/v2", "/swap/v1/quote"]),
    )
    result = evaluate_mpr_next_01(tmp_path)
    assert "product_contracts:src/resources/product_contract_pr195.json:contains-swap-v1" in result.blockers


def test_mpr_next_01_rejects_missing_swap_v2_build(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    _write_json(
        tmp_path / "config/product_contract_pr195.json",
        _product_contract(["/price/v3"]),
    )
    result = evaluate_mpr_next_01(tmp_path)
    assert "product_contracts:config/product_contract_pr195.json:missing-swap-v2-build" in result.blockers


def test_mpr_next_01_rejects_committed_diagnostics(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    _write_text(tmp_path / "pr190-diagnostics.txt", "failed")
    result = evaluate_mpr_next_01(tmp_path)
    assert "release_hygiene:committed-generated-artifact:pr190-diagnostics.txt" in result.blockers


def test_mpr_next_01_rejects_branch_writing_workflow(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    _write_text(
        tmp_path / ".github/workflows/pr190-diagnostics.yml",
        """
permissions:
  contents: write
jobs:
  capture:
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
        with:
          python-version: '3.13'
      - run: git push origin HEAD:main
""",
    )
    result = evaluate_mpr_next_01(tmp_path)
    assert "workflows:.github/workflows/pr190-diagnostics.yml:branch-writing-diagnostics" in result.blockers


def test_mpr_next_01_rejects_python_version_drift(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    path = tmp_path / ".github/workflows/mpr31-final-promotion-gate.yml"
    path.write_text(path.read_text(encoding="utf-8").replace("3.13", "3.11"), encoding="utf-8")
    result = evaluate_mpr_next_01(tmp_path)
    assert "workflows:.github/workflows/mpr31-final-promotion-gate.yml:python-version-drift" in result.blockers


def test_mpr_next_01_rejects_missing_closure_gate(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    payload = _closure_map()
    payload["gates"] = payload["gates"][:-1]
    _write_json(tmp_path / "src/resources/production_debt_closure_map.json", payload)
    result = evaluate_mpr_next_01(tmp_path)
    assert "closure_map:missing-gate:PR-228" in result.blockers


def test_mpr_next_01_rejects_live_enabled_closure_map(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    payload = _closure_map()
    payload["live_enabled"] = True
    _write_json(tmp_path / "src/resources/production_debt_closure_map.json", payload)
    result = evaluate_mpr_next_01(tmp_path)
    assert "closure_map:must-not-enable-live-or-production" in result.blockers
