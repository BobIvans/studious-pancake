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
