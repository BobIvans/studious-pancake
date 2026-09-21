from __future__ import annotations

import importlib
import json
from pathlib import Path

from src.release_gate.mega8_dependency_closure import (
    audit_receipts,
    verify_current_manifests,
)

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "release_artifacts" / "mega8" / "dependency_reconciliation.json"


def test_exact_historical_inversions_are_preserved_as_audit_facts() -> None:
    audit = audit_receipts(RECEIPT)
    assert audit.package_count == 7
    assert audit.all_dependencies_present is True
    assert audit.unresolved_dependencies == ()
    assert set(audit.historical_order_inversions) == {
        "MEGA8-02:before:MEGA8-01",
        "MEGA8-05:before:MEGA8-04",
        "MEGA8-06:before:MEGA8-04",
    }


def test_current_manifests_retire_only_stale_dependency_blockers() -> None:
    result = verify_current_manifests(ROOT, RECEIPT)
    assert result["accepted"] is True, result["errors"]
    assert result["production_ready"] is False
    assert result["live_enabled"] is False
    assert result["automatic_capital_increase_allowed"] is False


def test_cross_mega_owner_surfaces_import_on_one_current_head() -> None:
    modules = (
        "src.mega8_01",
        "src.mega8_02",
        "src.mega8_03",
        "src.mega8_04",
        "src.research.mega8_05",
        "src.mega8_06",
        "src.mega8_07",
    )
    imported = {name: importlib.import_module(name) for name in modules}
    assert len(imported["src.mega8_01"].NF_SYMBOLS) == 48
    assert imported["src.mega8_02"].FUNCTION_COUNT == 92
    assert imported["src.mega8_03"].MEGA8_03_SCHEMA == "mega8-03.offline.v1"
    assert len(imported["src.mega8_04"].NF_SYMBOLS) == 56
    assert len(imported["src.research.mega8_05"].__all__) >= 64
    assert imported["src.mega8_06"].FUNCTION_COUNT == 64
    assert imported["src.mega8_07"].FUNCTION_COUNT == 64


def test_mega8_02_is_requalified_after_mega8_01_and_super02() -> None:
    payload = json.loads((ROOT / "config/mega8_02_coverage.json").read_text())
    dependency = payload["dependency_status"]["MEGA8-01"]
    assert dependency["status"] == "MERGED_REQUALIFIED"
    assert dependency["merge_commit"] == "c786b74c3fdd614d16ef3db6c517e964cb43c194"
    assert payload["current_head_requalification"]["super02_merge_commit"] == (
        "23cb506c0dc54b9473dea574c2479bf113c79a69"
    )


def test_mega8_05_and_06_depend_on_merged_mega8_04() -> None:
    mega05 = json.loads(
        (ROOT / "release_artifacts/mega8/MEGA8-05/coverage.json").read_text()
    )
    assert mega05["operational_status"] == "BLOCKED_EXTERNAL_EVIDENCE"
    deps05 = {row["id"]: row for row in mega05["mega_dependencies"]}
    assert deps05["MEGA8-04"]["observed"] == "MERGED_REQUALIFIED"

    mega06 = json.loads((ROOT / "config/mega8_06_coverage.json").read_text())
    assert mega06["operational_status"] == "BLOCKED_EXTERNAL_EVIDENCE"
    assert mega06["dependency_snapshot"]["MEGA8-04"]["status"] == "MERGED_REQUALIFIED"
    assert mega06["dependency_snapshot"]["MEGA8-05"]["status"] == "MERGED_REQUALIFIED"


def test_mega8_07_is_resealed_not_reimplemented() -> None:
    payload = json.loads(
        (ROOT / "release_artifacts/mega8/MEGA8-07/coverage.json").read_text()
    )
    assert payload["operational_status"] == "BLOCKED_EXTERNAL_AND_PROMOTION_EVIDENCE"
    assert payload["dependency_status"]["MEGA8-04"]["status"] == "MERGED_REQUALIFIED"
    assert payload["dependency_reconciliation"]["mode"] == "RESEALED_CURRENT_HEAD"


def test_super02_agg04_code_contract_is_requalified_but_external_evidence_stays_blocked() -> (
    None
):
    payload = json.loads(
        (ROOT / "release_artifacts/super/SUPER-02/coverage.json").read_text()
    )
    current = payload["current_head_requalification"]
    assert current["status"] == "CODE_CONTRACT_REQUALIFIED"
    assert current["agg04_merge_commit"] == "b26c6a05c0646fb839f49f537fc21acbd863455c"
    assert payload["qualification_status"] == "BLOCKED_EXTERNAL"
    assert (
        "AGG04_EXTERNAL_CAMPAIGN_REQUALIFICATION_REQUIRED_FOR_EXACT_DEPLOYMENT_PROFILE_GENERATION"
        in payload["residual_blockers"]
    )
