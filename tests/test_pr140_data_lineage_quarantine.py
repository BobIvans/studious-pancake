from __future__ import annotations

from pathlib import Path

import pytest

from src.data_lineage_pr140 import (
    PR140DatasetLineage,
    PR140LineageError,
    PR140SourceKind,
    assert_no_forbidden_root_artifacts,
    artifact_sha256_bytes,
    forbidden_root_artifacts,
    load_pr140_policy,
    validate_actual_fields,
    validate_csv_text_shape,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "src/resources/data_lineage_policy_pr140.json"
SHA = "a" * 64
SETTLEMENT_SHA = "b" * 64


def synthetic_lineage() -> PR140DatasetLineage:
    return PR140DatasetLineage(
        artifact_path="datasets/synthetic/example.csv",
        artifact_sha256=SHA,
        source_kind=PR140SourceKind.SYNTHETIC,
        synthetic=True,
        exclude_from_financial_performance=True,
        generator_version="fixture-generator-pr140.v1",
        seed="seed-1",
    )


def live_lineage(
    settlement_hash: str | None = None,
) -> PR140DatasetLineage:
    return PR140DatasetLineage(
        artifact_path="datasets/live/trades.csv",
        artifact_sha256=SHA,
        source_kind=PR140SourceKind.LIVE,
        synthetic=False,
        exclude_from_financial_performance=False,
        finalized_settlement_evidence_sha256=settlement_hash,
        source="finalized-getTransaction-export",
        time_range=("2026-07-21T00:00:00Z", "2026-07-21T01:00:00Z"),
        contract_pins=("pr138.finalized-settlement.v1",),
        config_pins=("paper-only",),
    )


def test_pr140_forbidden_runtime_artifacts_are_removed_from_root() -> None:
    assert forbidden_root_artifacts(ROOT) == ()
    assert_no_forbidden_root_artifacts(ROOT)


def test_pr140_policy_lists_all_quarantined_artifacts() -> None:
    policy = load_pr140_policy(POLICY)

    assert policy["schema_version"] == "pr140.data-lineage-policy.v1"
    assert {
        item["path"] for item in policy["forbidden_tracked_root_artifacts"]
    } == {
        "ai_training_data.csv",
        "trade_history.csv",
        "bot_health.json",
        "helius-sanctum-lst-webhook.json",
    }


def test_pr140_synthetic_lineage_is_excluded_from_performance() -> None:
    lineage = synthetic_lineage()

    assert lineage.eligible_for_financial_performance is False
    validate_actual_fields(lineage=lineage, row={"actual_profit_sol": "0.01"})

    with pytest.raises(PR140LineageError):
        PR140DatasetLineage(
            artifact_path="datasets/synthetic/bad.csv",
            artifact_sha256=SHA,
            source_kind=PR140SourceKind.SYNTHETIC,
            synthetic=True,
            exclude_from_financial_performance=False,
            generator_version="generator",
            seed="seed",
        )


def test_pr140_actual_fields_need_finalized_settlement_evidence() -> None:
    with pytest.raises(PR140LineageError):
        validate_actual_fields(
            lineage=live_lineage(),
            row={"actual_profit_sol": "0.01", "signature": "sig"},
        )

    settled = live_lineage(SETTLEMENT_SHA)
    validate_actual_fields(
        lineage=settled,
        row={"actual_profit_sol": "0.01", "signature": "sig"},
    )
    assert settled.eligible_for_financial_performance is True


def test_pr140_csv_shape_rejects_malformed_trade_rows() -> None:
    assert validate_csv_text_shape("a,b,c\n1,2,3\n") == 1

    with pytest.raises(PR140LineageError):
        validate_csv_text_shape("a,b,c\n1,2,3\n4,5,6,7\n")


def test_pr140_recorded_or_live_lineage_requires_pins() -> None:
    with pytest.raises(PR140LineageError):
        PR140DatasetLineage(
            artifact_path="datasets/live/trades.csv",
            artifact_sha256=SHA,
            source_kind=PR140SourceKind.LIVE,
            synthetic=False,
            exclude_from_financial_performance=False,
            source="rpc-export",
            time_range=("2026-07-21T00:00:00Z", "2026-07-21T01:00:00Z"),
        )


def test_pr140_artifact_hash_is_deterministic() -> None:
    assert artifact_sha256_bytes(b"abc") == artifact_sha256_bytes(b"abc")
    assert artifact_sha256_bytes(b"abc") != artifact_sha256_bytes(b"abcd")
