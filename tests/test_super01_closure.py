from __future__ import annotations

from pathlib import Path

import pytest

from src.agg02 import (
    AnalyticalDatasetPublisher,
    DatasetReplayReader,
    MarketLifecycleState,
    audit_universe_survivorship,
    materialize_market_membership,
    record_market_lifecycle_evidence,
    select_universe_as_known,
)
from src.agg02.contracts import Agg02Error
from scripts.verify_super01 import verify as verify_super01

pytestmark = pytest.mark.unit

A = "a" * 64
B = "b" * 64
C = "c" * 64


def _fact(
    event_id: str,
    market_id: str,
    state: MarketLifecycleState,
    effective_at_ms: int,
    observed_at_ms: int,
    *,
    source_hash: str = A,
    revision: int = 1,
    related_market_id: str | None = None,
    supersedes_event_id: str | None = None,
):
    return record_market_lifecycle_evidence(
        event_id=event_id,
        market_id=market_id,
        state=state,
        effective_at_ms=effective_at_ms,
        observed_at_ms=observed_at_ms,
        source_evidence_sha256=source_hash,
        revision=revision,
        related_market_id=related_market_id,
        supersedes_event_id=supersedes_event_id,
    )


def test_dataset_replay_reader_verifies_manifest_and_available_time(
    tmp_path: Path,
) -> None:
    publisher = AnalyticalDatasetPublisher()
    manifest = publisher.publish(
        dataset_id="events-v1",
        schema_version="super01.events.v1",
        rows=(
            {"event_id": "old", "available_at_ms": 100, "amount": 1},
            {"event_id": "future", "available_at_ms": 300, "amount": 2},
        ),
        destination=tmp_path / "events.parquet",
    )
    reader = DatasetReplayReader()
    rows = reader.read(
        manifest,
        expected_schema_version="super01.events.v1",
        max_available_at_ms=200,
    )
    assert rows == ({"event_id": "old", "available_at_ms": 100, "amount": 1},)

    with pytest.raises(Agg02Error, match="AGG02_REPLAY_SCHEMA_MISMATCH"):
        reader.read(manifest, expected_schema_version="other.v1")

    Path(manifest.path).write_bytes(b"tampered")
    with pytest.raises(Agg02Error, match="AGG02_DATASET_CHECKSUM_MISMATCH"):
        reader.read(manifest)


def test_late_lifecycle_evidence_does_not_leak_into_past_universe() -> None:
    facts = (
        _fact("a-active", "market-a", MarketLifecycleState.ACTIVE, 100, 110),
        _fact("b-active", "market-b", MarketLifecycleState.ACTIVE, 100, 110),
        _fact("b-close", "market-b", MarketLifecycleState.CLOSED, 150, 260),
    )

    before_late_knowledge = select_universe_as_known(
        facts,
        experiment_time_ms=200,
        knowledge_cutoff_ms=200,
        dataset_revision=1,
    )
    assert before_late_knowledge.included_market_ids == ("market-a", "market-b")

    future_market = _fact(
        "future-market",
        "market-future",
        MarketLifecycleState.ACTIVE,
        180,
        250,
    )
    no_identity_leak = select_universe_as_known(
        (*facts, future_market),
        experiment_time_ms=200,
        knowledge_cutoff_ms=200,
        dataset_revision=1,
    )
    assert "market-future" not in {
        decision.market_id for decision in no_identity_leak.decisions
    }

    after_late_knowledge = select_universe_as_known(
        facts,
        experiment_time_ms=300,
        knowledge_cutoff_ms=300,
        dataset_revision=1,
    )
    assert after_late_knowledge.included_market_ids == ("market-a",)
    assert after_late_knowledge.excluded_market_ids == ("market-b",)


def test_membership_keeps_migration_identity_explicit() -> None:
    facts = (
        _fact("old-active", "old", MarketLifecycleState.ACTIVE, 100, 100),
        _fact(
            "old-migrated",
            "old",
            MarketLifecycleState.MIGRATED,
            200,
            205,
            related_market_id="new",
        ),
        _fact("new-active", "new", MarketLifecycleState.ACTIVE, 200, 205),
    )
    intervals = materialize_market_membership(
        facts,
        dataset_revision=1,
        knowledge_cutoff_ms=300,
    )
    old = tuple(item for item in intervals if item.market_id == "old")
    new = tuple(item for item in intervals if item.market_id == "new")
    assert old[0].valid_to_ms == 200
    assert old[1].state is MarketLifecycleState.MIGRATED
    assert old[1].related_market_id == "new"
    assert new[0].valid_from_ms == 200


def test_revision_changes_new_manifest_without_rewriting_old_one() -> None:
    initial = _fact("market-active", "market", MarketLifecycleState.ACTIVE, 100, 100)
    old_manifest = select_universe_as_known(
        (initial,),
        experiment_time_ms=200,
        knowledge_cutoff_ms=200,
        dataset_revision=1,
    )
    correction = _fact(
        "market-active-r2",
        "market",
        MarketLifecycleState.UNKNOWN,
        100,
        250,
        source_hash=B,
        revision=2,
        supersedes_event_id="market-active",
    )
    new_manifest = select_universe_as_known(
        (initial, correction),
        experiment_time_ms=300,
        knowledge_cutoff_ms=300,
        dataset_revision=2,
    )
    assert old_manifest.included_market_ids == ("market",)
    assert new_manifest.unknown_market_ids == ("market",)
    assert old_manifest.manifest_hash != new_manifest.manifest_hash


def test_survivorship_audit_uses_exact_manifest_denominator() -> None:
    initial = (
        _fact("a-active", "a", MarketLifecycleState.ACTIVE, 100, 100),
        _fact("b-active", "b", MarketLifecycleState.ACTIVE, 100, 100),
        _fact("c-unknown", "c", MarketLifecycleState.UNKNOWN, 100, 100),
    )
    manifest = select_universe_as_known(
        initial,
        experiment_time_ms=150,
        knowledge_cutoff_ms=150,
        dataset_revision=1,
    )
    later = (
        *initial,
        _fact(
            "b-close",
            "b",
            MarketLifecycleState.CLOSED,
            200,
            220,
            source_hash=C,
        ),
    )
    audit = audit_universe_survivorship(
        manifest,
        later,
        result_market_ids=("a", "b"),
    )
    assert audit.denominator == 2
    assert audit.later_closed == ("b",)
    assert audit.unknown_at_cutoff == ("c",)

    with pytest.raises(Agg02Error, match="SUPER01_DENOMINATOR_MISMATCH"):
        audit_universe_survivorship(
            manifest,
            later,
            result_market_ids=("a",),
        )


def test_future_knowledge_and_conflicting_transition_fail_closed() -> None:
    with pytest.raises(Agg02Error, match="SUPER01_FUTURE_KNOWLEDGE"):
        select_universe_as_known(
            (),
            experiment_time_ms=100,
            knowledge_cutoff_ms=101,
            dataset_revision=1,
        )

    conflicting = (
        _fact("one", "m", MarketLifecycleState.ACTIVE, 100, 100),
        _fact(
            "two",
            "m",
            MarketLifecycleState.CLOSED,
            100,
            100,
            source_hash=B,
        ),
    )
    with pytest.raises(
        Agg02Error,
        match="SUPER01_UNRESOLVED_LIFECYCLE_CONFLICT",
    ):
        materialize_market_membership(conflicting, dataset_revision=1)


def test_super01_verifier_maps_all_children_without_claiming_live() -> None:
    evidence = verify_super01()
    assert evidence["accepted"] is True
    assert evidence["child_count"] == 11
    assert evidence["nf_count"] == 88
    assert evidence["operational_qualified"] is False
    assert evidence["live_enabled"] is False
    assert (
        "SUPER01_V1_PROVIDER_SDK_CODEC_NOT_QUALIFIED"
        in evidence["operational_blockers"]
    )


def test_revision_must_reference_known_prior_fact() -> None:
    orphan = _fact(
        "correction",
        "market",
        MarketLifecycleState.UNKNOWN,
        100,
        150,
        revision=2,
        supersedes_event_id="missing-original",
    )
    with pytest.raises(Agg02Error, match="SUPER01_UNRESOLVED_REVISION_LINK"):
        materialize_market_membership((orphan,), dataset_revision=2)
