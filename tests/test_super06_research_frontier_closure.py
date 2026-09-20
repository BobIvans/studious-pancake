from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.verify_super06_research_frontier import (
    EXCLUDED_PRODUCT_NF,
    EXPECTED_BLOCKERS,
    EXPECTED_CHILDREN,
    EXPECTED_NF,
    EXPECTED_RECEIPTS,
    EXPECTED_SOURCE_BLOBS,
    validate_pinned_source_blobs,
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
    assert result["pinned_source_blob_count"] == 12


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
    with pytest.raises(
        ValueError,
        match="SUPER06_CHILD_NF_SCOPE_MISMATCH|SUPER06_NF_SCOPE_MISMATCH",
    ):
        validate_super_payload(mutated)


def test_super06_requires_exact_operational_blocker_set() -> None:
    payload = _payload()
    assert frozenset(payload["blockers"]) == EXPECTED_BLOCKERS

    mutated = copy.deepcopy(payload)
    mutated["blockers"] = [payload["blockers"][0]]
    with pytest.raises(ValueError, match="SUPER06_BLOCKER_SET_MISMATCH"):
        validate_super_payload(mutated)

    mutated = copy.deepcopy(payload)
    mutated["blockers"][-1] = "ARBITRARY_NONEMPTY_BLOCKER"
    with pytest.raises(ValueError, match="SUPER06_BLOCKER_SET_MISMATCH"):
        validate_super_payload(mutated)


def test_super06_rejects_wrong_merged_source_receipt() -> None:
    payload = _payload()
    mutated = copy.deepcopy(payload)
    mutated["source_receipts"][0]["merge_sha"] = "0" * 40
    with pytest.raises(ValueError, match="SUPER06_SOURCE_RECEIPT_MISMATCH"):
        validate_super_payload(mutated)

    observed = {
        row["name"]: (row["pr"], row["merge_sha"])
        for row in payload["source_receipts"]
    }
    assert observed == dict(EXPECTED_RECEIPTS)


def test_super06_rejects_redirected_child_evidence_paths() -> None:
    payload = _payload()
    mutated = copy.deepcopy(payload)
    mutated["children"][0]["owner"] = "config/agg14_research_coverage.json"
    with pytest.raises(ValueError, match="SUPER06_CHILD_METADATA_MISMATCH:PR-123:owner"):
        validate_super_payload(mutated)

    mutated = copy.deepcopy(payload)
    mutated["children"][6]["test"] = "tests/test_agg10_intelligence.py"
    with pytest.raises(ValueError, match="SUPER06_CHILD_METADATA_MISMATCH:PR-147:test"):
        validate_super_payload(mutated)


def test_super06_pins_checked_out_canonical_source_blobs(tmp_path: Path) -> None:
    for relative in EXPECTED_SOURCE_BLOBS:
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    validate_pinned_source_blobs(tmp_path)

    mutated = tmp_path / "src/decision/agg10.py"
    mutated.write_bytes(mutated.read_bytes() + b"\n# provenance mutation\n")
    with pytest.raises(ValueError, match="SUPER06_SOURCE_BLOB_MISMATCH:src/decision/agg10.py"):
        validate_pinned_source_blobs(tmp_path)

    mutated.write_bytes((ROOT / "src/decision/agg10.py").read_bytes())
    common = tmp_path / "src/research/common.py"
    common.write_bytes(common.read_bytes() + b"\n# shared-helper mutation\n")
    with pytest.raises(ValueError, match="SUPER06_SOURCE_BLOB_MISMATCH:src/research/common.py"):
        validate_pinned_source_blobs(tmp_path)
