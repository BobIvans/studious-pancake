from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.verify_super06_research_frontier import (
    EXCLUDED_PRODUCT_NF,
    EXPECTED_CHILDREN,
    EXPECTED_NF,
    validate_super_payload,
    verify,
)


ROOT = Path(__file__).resolve().parents[1]


def _payload() -> dict[str, object]:
    return json.loads(
        (ROOT / "release_artifacts/super/SUPER-06/coverage.json").read_text(
            encoding="utf-8"
        )
    )


def test_super06_closure_verifier_accepts_current_canonical_owners() -> None:
    result = verify(ROOT)

    assert result["ok"] is True
    assert result["child_count"] == 7
    assert result["nf_count"] == 34
    assert result["live_enabled"] is False
    assert result["product_scope_included"] is False


def test_super06_exact_child_and_nf_scope_has_no_product_inflation() -> None:
    payload = _payload()
    child_ids = {row["source_pr"] for row in payload["children"]}
    observed_nf = {
        nf
        for row in payload["children"]
        for nf in row["nf"]
    }

    assert child_ids == set(EXPECTED_CHILDREN)
    assert observed_nf == EXPECTED_NF
    assert not (observed_nf & EXCLUDED_PRODUCT_NF)
    assert set(payload["excluded_adjacent_nf"]) == EXCLUDED_PRODUCT_NF


def test_super06_rejects_live_or_production_promotion() -> None:
    payload = _payload()
    for key in ("live_enabled", "signing_enabled", "submission_enabled", "production_ready"):
        mutated = copy.deepcopy(payload)
        mutated[key] = True
        with pytest.raises(ValueError, match="SUPER06_UNSAFE_FLAG"):
            validate_super_payload(mutated)


def test_super06_rejects_duplicate_or_scope_inflated_nf() -> None:
    payload = _payload()
    mutated = copy.deepcopy(payload)
    mutated["children"][0]["nf"].append("NF-318")
    with pytest.raises(ValueError, match="SUPER06_CHILD_NF_SCOPE_MISMATCH|SUPER06_NF_SCOPE_MISMATCH"):
        validate_super_payload(mutated)


def test_super06_requires_explicit_operational_blockers() -> None:
    payload = _payload()
    mutated = copy.deepcopy(payload)
    mutated["blockers"] = []
    with pytest.raises(ValueError, match="SUPER06_BLOCKERS_MUST_REMAIN_EXPLICIT"):
        validate_super_payload(mutated)
