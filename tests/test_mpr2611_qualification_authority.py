from __future__ import annotations

import json
from pathlib import Path

from scripts.run_mpr2611_clean_qualification import run_repeated
from scripts.verify_mpr2611_production_qualification import verify

ROOT = Path(__file__).resolve().parents[1]


def test_authority_map_is_single_owner_and_fail_closed():
    payload = verify(ROOT)
    assert payload["accepted"] is True, payload["reason_codes"]
    assert payload["release_claim_allowed"] is False
    assert payload["live_enabled"] is False


def test_parallel_2607_2610_paths_do_not_collide_with_mpr2611_owned_paths():
    authority = json.loads(
        (ROOT / "config" / "mpr2611_qualification_authority.json").read_text(
            encoding="utf-8"
        )
    )
    owned = set(authority["mpr2611_owned_paths"])
    parallel = {
        path
        for owner in authority["parallel_owners"].values()
        for path in owner["paths"]
    }
    assert owned.isdisjoint(parallel)


def test_repeated_clean_snapshot_is_deterministic_and_cannot_promote_release():
    payload = run_repeated(
        ROOT,
        release_id="mpr2611-test-release",
        source_commit="68788d7f7f7da8a2e03b170f93c48af7421ee805",
        repeat=2,
    )
    assert payload["verified"] is True
    assert payload["stable"] is True
    assert payload["independent_digest_match"] is True
    assert len(set(payload["run_digests"])) == 1
    assert payload["release_claim_allowed"] is False
    assert payload["live_enabled"] is False


def test_missing_real_predecessor_evidence_stays_blocked_in_clean_snapshot():
    payload = run_repeated(
        ROOT,
        release_id="mpr2611-no-fabrication",
        source_commit="68788d7f7f7da8a2e03b170f93c48af7421ee805",
        repeat=2,
    )
    snapshot = payload["snapshot"]
    assert snapshot["production_qualification_passed"] is False
    assert snapshot["eligible_for_release_review"] is False
    assert snapshot["missing_artifacts"] or snapshot["invalid_artifacts"] or snapshot["open_debt_items"]
