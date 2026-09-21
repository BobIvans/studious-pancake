from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.super05_strategy_closure import (
    AGG06_SUPER05_NF,
    AGG07_SUPER05_NF,
    AGG10_SUPER05_NF,
    ARTIFACT_PATHS,
    CHILD_CONTRACTS,
    EXPECTED_PRIMARY_NF,
    evaluate_super05,
)

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]


def _artifacts() -> dict[str, dict[str, object]]:
    return {
        agg_id: json.loads((ROOT / path).read_text(encoding="utf-8"))
        for agg_id, path in ARTIFACT_PATHS.items()
    }


def test_super05_has_exact_child_and_primary_nf_ownership() -> None:
    assert len(CHILD_CONTRACTS) == 11
    assert len(EXPECTED_PRIMARY_NF) == 26
    owned = [nf for child in CHILD_CONTRACTS for nf in child.primary_nf]
    assert len(owned) == len(set(owned)) == 26
    assert set(owned) == EXPECTED_PRIMARY_NF
    related_only = [child for child in CHILD_CONTRACTS if not child.primary_nf]
    assert [child.child_pr for child in related_only] == ["PR-109"]


def test_super05_coverage_is_partitioned_across_existing_agg_owners() -> None:
    assert AGG06_SUPER05_NF.isdisjoint(AGG07_SUPER05_NF)
    assert AGG06_SUPER05_NF.isdisjoint(AGG10_SUPER05_NF)
    assert AGG07_SUPER05_NF.isdisjoint(AGG10_SUPER05_NF)
    assert AGG06_SUPER05_NF | AGG07_SUPER05_NF | AGG10_SUPER05_NF == (
        EXPECTED_PRIMARY_NF
    )


def test_current_super05_implementation_closes_offline_but_not_operationally() -> None:
    report = evaluate_super05()
    assert report.errors == ()
    assert report.implementation_complete is True
    assert report.implementation_status == "VERIFIED_OFFLINE"
    assert report.qualification_complete is False
    assert report.operational_status == "UNQUALIFIED"
    assert report.live_enabled is False
    assert report.release_claim_allowed is False
    assert "SUPER05_ORDERBOOK_RUNTIME_FIXTURE_ONLY" in report.blockers
    assert "SUPER05_AGG06_OPERATIONAL_EVIDENCE_UNQUALIFIED" in report.blockers
    assert "SUPER05_AGG07_OPERATIONAL_EVIDENCE_UNQUALIFIED" in report.blockers
    assert "SUPER05_AGG10_OPERATIONAL_EVIDENCE_UNQUALIFIED" in report.blockers


def test_agg06_external_qualified_status_does_not_keep_requirements_as_blockers() -> (
    None
):
    artifacts = _artifacts()
    agg06 = dict(artifacts["AGG-06"])
    agg06["operational_status"] = "EXTERNALLY_QUALIFIED_FOR_PROFILE"
    artifacts["AGG-06"] = agg06

    report = evaluate_super05(artifacts=artifacts)

    assert "SUPER05_AGG06_OPERATIONAL_EVIDENCE_UNQUALIFIED" not in report.blockers
    assert not any(
        blocker.startswith("SUPER05_AGG06_EXTERNAL:") for blocker in report.blockers
    )


def test_agg10_unqualified_status_blocks_super05_operational_qualification() -> None:
    artifacts = _artifacts()
    agg10 = dict(artifacts["AGG-10"])
    agg10["operational_status"] = "UNQUALIFIED"
    artifacts["AGG-10"] = agg10

    report = evaluate_super05(artifacts=artifacts)

    assert "SUPER05_AGG10_OPERATIONAL_EVIDENCE_UNQUALIFIED" in report.blockers
    assert report.qualification_complete is False


def test_missing_existing_owner_evidence_fails_implementation_closure() -> None:
    artifacts = _artifacts()
    agg06 = dict(artifacts["AGG-06"])
    agg06["primary_nf"] = [item for item in agg06["primary_nf"] if item != "NF-138"]
    artifacts["AGG-06"] = agg06

    report = evaluate_super05(artifacts=artifacts)

    assert report.implementation_complete is False
    assert any(
        error == "SUPER05_ARTIFACT_NF_MISSING:AGG-06:NF-138" for error in report.errors
    )


def test_existing_owner_cannot_silently_enable_live() -> None:
    artifacts = _artifacts()
    agg07 = dict(artifacts["AGG-07"])
    agg07["live_enabled"] = True
    artifacts["AGG-07"] = agg07

    report = evaluate_super05(artifacts=artifacts)

    assert report.implementation_complete is False
    assert "SUPER05_ARTIFACT_LIVE_NOT_FALSE:AGG-07" in report.errors
    assert report.live_enabled is False
    assert report.release_claim_allowed is False
