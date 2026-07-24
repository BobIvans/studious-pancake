from __future__ import annotations

import json
from pathlib import Path

from src.readiness.debt_closure_map import GATE_DEBT_MAP, MPR31_REQUIRED_UPSTREAMS


def test_packaged_debt_closure_manifest_matches_runtime_map() -> None:
    path = Path("src/resources/debt_closure_map_pr_next_07.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["production_ready"] is False
    assert payload["paper_ready"] is False
    assert payload["live_ready"] is False
    assert set(payload["gates"]) == set(GATE_DEBT_MAP)

    for gate_id, mapping in GATE_DEBT_MAP.items():
        manifest_gate = payload["gates"][gate_id]
        assert manifest_gate["evidence_kind"] == mapping.evidence_kind
        assert set(manifest_gate["debt_ids"]) == set(mapping.debt_ids)

    assert set(payload["gates"]["MPR-31"]["requires_upstream_mprs"]) == set(
        MPR31_REQUIRED_UPSTREAMS
    )
