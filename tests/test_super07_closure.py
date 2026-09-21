from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_super07_closure.py"
COVERAGE = ROOT / "config" / "super07_coverage.json"


def api():
    return runpy.run_path(str(SCRIPT), run_name="super07_verifier_test")


def payload() -> dict:
    return json.loads(COVERAGE.read_text(encoding="utf-8"))


def test_super07_exact_child_and_nf_closure() -> None:
    result = api()["verify_payload"](payload(), root=ROOT)
    assert result["ok"] is True
    assert result["child_count"] == 16
    assert result["nf_count"] == 56
    assert result["operational_qualified"] is False
    assert result["live_enabled"] is False
    assert result["blockers"]


def test_super07_rejects_duplicate_primary_owner() -> None:
    broken = deepcopy(payload())
    broken["children"][1]["primary_nf"].append("NF-077")
    result = api()["verify_payload"](broken, root=ROOT)
    assert result["ok"] is False
    assert "DUPLICATE_PRIMARY_NF" in result["errors"]


def test_super07_never_promotes_live_or_operational_status() -> None:
    broken = deepcopy(payload())
    broken["live_enabled"] = True
    broken["operational_qualified"] = True
    result = api()["verify_payload"](broken, root=ROOT)
    assert result["ok"] is False
    assert "LIVE_MUST_REMAIN_DISABLED" in result["errors"]
    assert "OPERATIONAL_QUALIFICATION_MUST_REMAIN_FALSE" in result["errors"]


def test_super07_rejects_per_child_mapping_corruption() -> None:
    broken = deepcopy(payload())
    broken["children"][0]["w2_id"] = "W2-20"
    broken["children"][0]["scope"] = "INV-05"
    broken["children"][0]["primary_nf"] = ["NF-303", "NF-304", "NF-305"]
    broken["children"][0]["canonical_owner_paths"] = ["src/inventory/research.py"]
    broken["children"][0]["test_paths"] = ["tests/test_agg13_inventory_platform.py"]
    result = api()["verify_payload"](broken, root=ROOT)
    assert result["ok"] is False
    assert any(
        error.startswith("PR-129:CHILD_MAPPING_MISMATCH:") for error in result["errors"]
    )


def test_super07_requires_exact_operational_blockers() -> None:
    broken = deepcopy(payload())
    broken["blockers"] = ["UNRELATED"]
    result = api()["verify_payload"](broken, root=ROOT)
    assert result["ok"] is False
    assert "OPERATIONAL_BLOCKER_SET_MISMATCH" in result["errors"]

    duplicate = deepcopy(payload())
    duplicate["blockers"].append(duplicate["blockers"][0])
    result = api()["verify_payload"](duplicate, root=ROOT)
    assert "OPERATIONAL_BLOCKER_DUPLICATE" in result["errors"]


def test_super07_rejects_per_child_disposition_corruption() -> None:
    broken = deepcopy(payload())
    broken["children"][7]["implementation_status"] = "SATISFIED_BY_EXISTING"
    result = api()["verify_payload"](broken, root=ROOT)
    assert result["ok"] is False
    assert "PR-136:CHILD_MAPPING_MISMATCH:implementation_status" in result["errors"]

    research = deepcopy(payload())
    research["children"][5]["qualification_status"] = "UNQUALIFIED"
    result = api()["verify_payload"](research, root=ROOT)
    assert result["ok"] is False
    assert "PR-134:CHILD_MAPPING_MISMATCH:qualification_status" in result["errors"]


def test_super07_rejects_source_pr_range_drift() -> None:
    broken = deepcopy(payload())
    broken["source_pr_range"] = "PR-001..PR-999"
    result = api()["verify_payload"](broken, root=ROOT)
    assert result["ok"] is False
    assert "SOURCE_PR_RANGE_MISMATCH" in result["errors"]


def test_super07_rejects_blocker_identifier_whitespace() -> None:
    broken = deepcopy(payload())
    broken["blockers"][0] = f" {broken['blockers'][0]} "
    result = api()["verify_payload"](broken, root=ROOT)
    assert result["ok"] is False
    assert "OPERATIONAL_BLOCKER_SET_MISMATCH" in result["errors"]


def test_super07_requires_w2_packages_array() -> None:
    broken = deepcopy(payload())
    broken["w2_packages"] = {
        "W2-17": True,
        "W2-18": True,
        "W2-19": True,
        "W2-20": True,
    }
    result = api()["verify_payload"](broken, root=ROOT)
    assert result["ok"] is False
    assert "W2_PACKAGES_ARRAY_REQUIRED" in result["errors"]
