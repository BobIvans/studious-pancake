from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.release_gate.pr353_strategy_closure import (
    EXPECTED_STRATEGY_IDS,
    PR353ClosureError,
    audit_pr353_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release_artifacts/final8/PR-353/current-head-evidence.json"


def _payload() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_pr353_manifest_is_structurally_complete_and_fail_closed() -> None:
    audit = audit_pr353_manifest(_payload())
    assert audit.structurally_complete
    assert audit.nf_owner_count == 1016
    assert audit.strategy_count == 73
    assert audit.final_verdict == "NO_GO"
    assert audit.production_ready is False
    assert audit.live_enabled is False
    assert audit.signer_access is False
    assert audit.submission_access is False


def test_strategy_inventory_matches_document_scope_exactly() -> None:
    payload = _payload()
    ids = tuple(row["strategy_id"] for row in payload["strategy_dispositions"])
    assert len(ids) == len(set(ids)) == len(EXPECTED_STRATEGY_IDS) == 73
    assert set(ids) == set(EXPECTED_STRATEGY_IDS)


def test_wp2_reuses_merged_mega8_and_ultimate_code() -> None:
    payload = _payload()
    wp2 = next(row for row in payload["work_packages"] if row["wp_id"] == "WP-2")
    assert wp2["status"] == "SATISFIED_BY_EXISTING"
    evidence = " ".join(wp2["evidence_refs"])
    assert "#530" in evidence
    assert "MEGA8-08" in evidence


def test_canary_cannot_be_relabelled_authorized() -> None:
    payload = _payload()
    wp6 = next(row for row in payload["work_packages"] if row["wp_id"] == "WP-6")
    wp6["status"] = "IMPLEMENTED_CURRENT_HEAD"
    with pytest.raises(PR353ClosureError, match="WP6_EFFECT_BOUNDARY_MISMATCH"):
        audit_pr353_manifest(payload)


def test_live_or_production_flags_fail_closed() -> None:
    for field in ("production_ready", "live_enabled", "signer_access", "submission_access"):
        payload = _payload()
        payload["safety"][field] = True
        with pytest.raises(PR353ClosureError, match="UNSAFE_FLAG"):
            audit_pr353_manifest(payload)


def test_missing_strategy_is_rejected() -> None:
    payload = _payload()
    payload["strategy_dispositions"] = payload["strategy_dispositions"][:-1]
    with pytest.raises(PR353ClosureError, match="STRATEGY_SET_MISMATCH"):
        audit_pr353_manifest(payload)


def test_qualified_without_current_external_campaign_is_not_in_manifest() -> None:
    payload = _payload()
    assert all(
        row["disposition"] != "QUALIFIED"
        for row in payload["strategy_dispositions"]
    )


def test_retired_aliases_are_fixed() -> None:
    payload = copy.deepcopy(_payload())
    payload["retired_planning_aliases"].append(361)
    with pytest.raises(PR353ClosureError, match="RETIRED_ALIAS_SET_MISMATCH"):
        audit_pr353_manifest(payload)
