from __future__ import annotations

import json
from pathlib import Path

from src.mpr_next_01_product_truth_gate import (
    CLOSURE_MAP_SCHEMA,
    REQUIRED_GATE_IDS,
    evaluate_mpr_next_01,
)


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _product_contract(paths: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": "pr195.product-contract.v1",
        "product_state": "not-production-ready",
        "live_available": False,
        "endpoints": {
            "jupiter": {
                "base_url_field": "providers.jupiter.base_url",
                "origin": "https://api.jup.ag",
                "paths": paths or ["/price/v3", "/swap/v2/build"],
                "secret_reference_fields": ["providers.jupiter.api_key_reference"],
                "state": "reviewed-disabled",
            }
        },
    }


def _closure_map(extra: dict[str, object] | None = None) -> dict[str, object]:
    gates = [
        {
            "gate_id": gate_id,
            "status": "required-runtime-artifact",
            "can_close_blocker_ids": ["runtime.product-state"],
            "required_evidence": ["materialized release artifact"],
        }
        for gate_id in REQUIRED_GATE_IDS
    ]
    payload: dict[str, object] = {
        "schema_version": CLOSURE_MAP_SCHEMA,
        "live_enabled": False,
        "production_ready": False,
        "policy": {
            "materialized_runtime_evidence_required": True,
            "offline_validators_do_not_close_blockers": True,
        },
        "gates": gates,
    }
    if extra:
        payload.update(extra)
    return payload


def _workflow(*, python_version: str = "3.13", writable: bool = False) -> str:
    permission = "write" if writable else "read"
    return f"""name: sample
on: [pull_request]
permissions:
  contents: {permission}
jobs:
  sample:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
        with:
          python-version: \"{python_version}\"
      - run: python -m pytest -q
"""


def _fixture_repo(root: Path) -> None:
    _write(
        root / "src/resources/production_debt_closure_map.json",
        json.dumps(_closure_map()),
    )
    for rel in (
        "src/resources/product_contract_pr195.json",
        "config/product_contract_pr195.json",
    ):
        _write(root / rel, json.dumps(_product_contract()))
    _write(root / ".github/workflows/mpr31-final-promotion-gate.yml", _workflow())
    _write(root / ".github/workflows/pr190-diagnostics.yml", _workflow())


def test_gate_accepts_clean_product_truth_and_release_hygiene(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)

    result = evaluate_mpr_next_01(tmp_path)

    assert result.accepted is True
    assert result.blockers == ()
    assert result.to_dict()["live_enabled"] is False
    assert result.to_dict()["production_ready"] is False


def test_gate_rejects_missing_closure_map_gate(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    payload = _closure_map()
    payload["gates"] = payload["gates"][:-1]  # type: ignore[index]
    _write(tmp_path / "src/resources/production_debt_closure_map.json", json.dumps(payload))

    result = evaluate_mpr_next_01(tmp_path)

    assert "closure_map:missing-gate:PR-228" in result.blockers


def test_gate_rejects_offline_validator_as_closure_policy(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    payload = _closure_map(
        {"policy": {"materialized_runtime_evidence_required": True}}
    )
    _write(tmp_path / "src/resources/production_debt_closure_map.json", json.dumps(payload))

    result = evaluate_mpr_next_01(tmp_path)

    assert "closure_map:missing-offline-validator-policy" in result.blockers


def test_gate_rejects_stale_jupiter_swap_v1(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    stale = json.dumps(_product_contract(["/swap/v1/quote", "/swap/v2/build"]))
    _write(tmp_path / "config/product_contract_pr195.json", stale)

    result = evaluate_mpr_next_01(tmp_path)

    assert "product_contracts:config/product_contract_pr195.json:contains-swap-v1" in result.blockers


def test_gate_rejects_missing_jupiter_v2_build(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    stale = json.dumps(_product_contract(["/price/v3"]))
    _write(tmp_path / "src/resources/product_contract_pr195.json", stale)

    result = evaluate_mpr_next_01(tmp_path)

    assert (
        "product_contracts:src/resources/product_contract_pr195.json:missing-swap-v2-build"
        in result.blockers
    )


def test_gate_rejects_committed_release_artifacts(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    _write(tmp_path / "pr190-diagnostics.txt", "exit_status=1\n")

    result = evaluate_mpr_next_01(tmp_path)

    assert "release_hygiene:committed-generated-artifact:pr190-diagnostics.txt" in result.blockers


def test_gate_rejects_python_version_drift(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    _write(
        tmp_path / ".github/workflows/mpr31-final-promotion-gate.yml",
        _workflow(python_version="3.11"),
    )

    result = evaluate_mpr_next_01(tmp_path)

    assert (
        "workflows:.github/workflows/mpr31-final-promotion-gate.yml:python-version-drift"
        in result.blockers
    )


def test_gate_rejects_branch_writing_diagnostics(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    _write(tmp_path / ".github/workflows/pr190-diagnostics.yml", _workflow(writable=True))

    result = evaluate_mpr_next_01(tmp_path)

    assert "workflows:.github/workflows/pr190-diagnostics.yml:branch-writing-diagnostics" in result.blockers
