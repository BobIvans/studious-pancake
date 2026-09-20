from __future__ import annotations

import json
from pathlib import Path

from scripts.qualify_release import collect_release_artifacts, resolve_debt_items
from src.production_qualification import validate_semantic_evidence


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _economics(*, source_commit: str = "abc", release_id: str = "rel-1", **overrides):
    payload = {
        "schema_version": "mpr-2610.finalized-economics.v1",
        "source_commit": source_commit,
        "release_id": release_id,
        "producer": "mpr-2610-finalized-economic-ledger",
        "production_evidence": True,
        "verdict": "settled",
        "transaction_finalized": True,
        "reconciliation_status": "reconciled",
        "realized_pnl_atomic_units": 1,
        "synthetic": False,
        "dry_run": False,
    }
    payload.update(overrides)
    return payload


def test_empty_economics_artifact_cannot_resolve_debt(tmp_path: Path):
    _write_json(tmp_path / "release_artifacts/finalized-economics-report.json", {})
    artifacts, by_id = collect_release_artifacts(
        tmp_path, source_commit="abc", release_id="rel-1"
    )
    record = by_id["finalized_economics_report_digest"]
    assert record["status"] == "invalid"
    assert record["semantic_sha256"] is None

    resolutions = resolve_debt_items(
        {"items": [{"id": "economics.capital-reservations"}]},
        by_id,
        product_state="production-ready",
        live_mode_available=True,
    )
    assert resolutions["economics.capital-reservations"]["resolved"] is False
    assert artifacts


def test_wrong_economics_schema_is_rejected(tmp_path: Path):
    path = tmp_path / "economics.json"
    _write_json(path, _economics(schema_version="wrong.v1"))
    result = validate_semantic_evidence(
        path,
        artifact_id="finalized_economics_report_digest",
        source_commit="abc",
        release_id="rel-1",
    )
    assert result.accepted is False
    assert "WRONG_SCHEMA_VERSION" in result.reason_codes


def test_economics_from_different_source_commit_is_rejected(tmp_path: Path):
    path = tmp_path / "economics.json"
    _write_json(path, _economics(source_commit="old"))
    result = validate_semantic_evidence(
        path,
        artifact_id="finalized_economics_report_digest",
        source_commit="new",
        release_id="rel-1",
    )
    assert result.accepted is False
    assert "SOURCE_COMMIT_MISMATCH" in result.reason_codes


def test_old_canary_bundle_cannot_resolve_new_release(tmp_path: Path):
    path = tmp_path / "canary.json"
    _write_json(
        path,
        {
            "schema_version": "mpr-2609.canary.v1",
            "source_commit": "abc",
            "release_id": "rel-old",
            "producer": "mpr-2609-limited-live-canary",
            "production_evidence": True,
            "verdict": "passed",
            "second_human_approval": True,
            "auto_rearm": False,
            "unknown_outcome": False,
        },
    )
    result = validate_semantic_evidence(
        path,
        artifact_id="signer_canary_approval_bundle_digest",
        source_commit="abc",
        release_id="rel-new",
    )
    assert result.accepted is False
    assert "RELEASE_ID_MISMATCH" in result.reason_codes


def test_failed_or_ambiguous_evidence_is_rejected(tmp_path: Path):
    path = tmp_path / "economics.json"
    _write_json(path, _economics(verdict="ambiguous"))
    result = validate_semantic_evidence(
        path,
        artifact_id="finalized_economics_report_digest",
        source_commit="abc",
        release_id="rel-1",
    )
    assert result.accepted is False
    assert "NON_SUCCESS_VERDICT" in result.reason_codes


def test_bool_is_not_accepted_as_realized_integer_pnl(tmp_path: Path):
    path = tmp_path / "economics.json"
    _write_json(path, _economics(realized_pnl_atomic_units=True))
    result = validate_semantic_evidence(
        path,
        artifact_id="finalized_economics_report_digest",
        source_commit="abc",
        release_id="rel-1",
    )
    assert result.accepted is False
    assert "MISSING_REALIZED_INTEGER_PNL" in result.reason_codes


def test_duplicate_json_key_is_rejected(tmp_path: Path):
    path = tmp_path / "economics.json"
    path.write_text(
        '{"schema_version":"mpr-2610.finalized-economics.v1",'
        '"schema_version":"mpr-2610.finalized-economics.v1"}\n',
        encoding="utf-8",
    )
    result = validate_semantic_evidence(
        path,
        artifact_id="finalized_economics_report_digest",
        source_commit="abc",
        release_id="rel-1",
    )
    assert result.accepted is False
    assert "INVALID_JSON_EVIDENCE" in result.reason_codes


def test_valid_economics_has_distinct_raw_and_semantic_digests(tmp_path: Path):
    path = tmp_path / "economics.json"
    _write_json(path, _economics())
    result = validate_semantic_evidence(
        path,
        artifact_id="finalized_economics_report_digest",
        source_commit="abc",
        release_id="rel-1",
    )
    assert result.accepted is True
    assert result.raw_sha256
    assert result.semantic_sha256


def test_shadow_requires_real_non_synthetic_duration(tmp_path: Path):
    path = tmp_path / "shadow.json"
    _write_json(
        path,
        {
            "schema_version": "mpr-2607.shadow-soak.v1",
            "source_commit": "abc",
            "release_id": "rel-1",
            "producer": "mpr-2607-shadow-soak",
            "production_evidence": True,
            "verdict": "passed",
            "synthetic": False,
            "eligible_duration_seconds": 3600,
        },
    )
    result = validate_semantic_evidence(
        path,
        artifact_id="shadow_campaign_report_digest",
        source_commit="abc",
        release_id="rel-1",
    )
    assert result.accepted is True
