"""OCA-W15 tests: bitemporal as-of, migration receipts, static/runtime gate."""

from __future__ import annotations

import pytest

from src.intelligence.temporal_ontology import (
    TemporalFact,
    as_of,
    enforce_static_runtime_separation,
    migration_receipt,
)


def test_bitemporal_as_of_deterministic() -> None:
    facts = [
        TemporalFact(
            entity_id="provider:jupiter",
            layer="provider",
            predicate="DECLARED_CAPABILITY",
            obj="quotes",
            valid_from=100,
            valid_to=200,
            recorded_at=110,
        ),
        TemporalFact(
            entity_id="provider:jupiter",
            layer="provider",
            predicate="DECLARED_CAPABILITY",
            obj="quotes-v2",
            valid_from=200,
            valid_to=None,
            recorded_at=210,
        ),
    ]
    before = as_of(facts, valid_at=150, recorded_at=500)
    assert len(before) == 1 and before[0].obj == "quotes"
    # v2 not yet recorded at transaction-time 150: nothing visible.
    # At valid 250 / transaction-time 150: fact1 expired (valid_to=200) and
    # fact2 not yet recorded -> empty. Bitemporal honesty, not a gap.
    early = as_of(facts, valid_at=250, recorded_at=150)
    assert early == []
    late = as_of(facts, valid_at=250, recorded_at=500)
    assert len(late) == 1 and late[0].obj == "quotes-v2"
    assert as_of(facts, valid_at=250, recorded_at=500) == late


def test_runtime_observed_requires_runtime_predicate() -> None:
    with pytest.raises(ValueError):
        TemporalFact(
            entity_id="py::src/pkg/core.py::run",
            layer="code",
            predicate="CALLS_RESOLVED",
            obj="target",
            valid_from=1,
            recorded_at=1,
            verification_state="RUNTIME_OBSERVED",
        )
    runtime_fact = TemporalFact(
        entity_id="py::src/pkg/core.py::run",
        layer="runtime",
        predicate="EXECUTED_BY",
        obj="vertical-opp-1",
        valid_from=1,
        recorded_at=2,
        verification_state="RUNTIME_OBSERVED",
    )
    audit = enforce_static_runtime_separation([runtime_fact])
    assert audit["ok"]
    static_fact = TemporalFact(
        entity_id="py::src/pkg/core.py::run",
        layer="code",
        predicate="CALLS_RESOLVED",
        obj="target",
        valid_from=1,
        recorded_at=1,
    )
    bad = enforce_static_runtime_separation([static_fact, runtime_fact])
    assert bad["checked"] == 2


def test_migration_receipt_preserves_evidence() -> None:
    records = [
        {"entity_id": "a", "predicate": "IMPORTS", "obj": "b"},
        {"entity_id": "c", "predicate": "CONFIGURED_BY", "obj": "d"},
    ]
    receipt = migration_receipt(records, from_schema="v0", to_schema="v1")
    assert receipt["from_schema"] == "v0" and receipt["to_schema"] == "v1"
    assert receipt["input_digests"] == [
        __import__("hashlib")
        .sha256(
            __import__("json").dumps(r, sort_keys=True, separators=(",", ":")).encode()
        )
        .hexdigest()
        for r in records
    ]
    assert all(record["ontology_schema"] == "v1" for record in receipt["migrated"])
    assert receipt["evidence_preserved"] is True
    # Deterministic re-run.
    assert migration_receipt(records, from_schema="v0", to_schema="v1") == receipt
