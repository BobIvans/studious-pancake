"""Typed temporal ontology with bitemporal facts and as-of queries (OCA-W15).

A derived, read-only knowledge layer over the canonical owners (W2 episodes,
W13/W14 registries, repo-graph facts). Facts are bitemporal: an entity-valid
interval plus a transaction-time (recorded_at) — so historical as-of queries
are deterministic and migrations preserve evidence. Static relations never
become runtime observations here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA = "studious.temporal-ontology.v1"

LAYERS = (
    "code",
    "config",
    "strategy",
    "market",
    "provider",
    "runtime",
    "outcome",
    "governance",
)

# Predicate registry: static facts and runtime observations are distinct
# predicate namespaces and one is never promoted into the other.
STATIC_PREDICATES = frozenset(
    {
        "CALLS_STATIC",
        "CALLS_RESOLVED",
        "IMPORTS",
        "DEFINES",
        "TESTED_BY",
        "CONFIGURED_BY",
    }
)
RUNTIME_PREDICATES = frozenset(
    {"EXECUTED_BY", "OBSERVED_AT", "DECIDED_ON", "RESULTED_IN"}
)


@dataclass(frozen=True)
class TemporalFact:
    entity_id: str
    layer: str
    predicate: str
    obj: str
    valid_from: int
    valid_to: int | None = None  # open interval
    recorded_at: int = 0
    source_event_time: int | None = None
    evidence_ref: str | None = None
    verification_state: str = "STATIC_EXTRACTED"
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.layer not in LAYERS:
            raise ValueError(f"unknown layer: {self.layer}")
        if self.verification_state == "RUNTIME_OBSERVED" and (
            self.predicate not in RUNTIME_PREDICATES
        ):
            raise ValueError(
                f"RUNTIME_OBSERVED requires a runtime predicate, got {self.predicate}"
            )

    def valid_at(self, instant: int) -> bool:
        return self.valid_from <= instant and (
            self.valid_to is None or instant <= self.valid_to
        )

    def recorded_by(self, instant: int) -> bool:
        return self.recorded_at <= instant

    def to_record(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "layer": self.layer,
            "predicate": self.predicate,
            "obj": self.obj,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "recorded_at": self.recorded_at,
            "source_event_time": self.source_event_time,
            "evidence_ref": self.evidence_ref,
            "verification_state": self.verification_state,
            "attributes": dict(sorted(self.attributes.items())),
        }

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_record(), sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()


def as_of(
    facts: list[TemporalFact], *, valid_at: int, recorded_at: int
) -> list[TemporalFact]:
    """Deterministic bitemporal as-of query."""
    selected = [
        fact
        for fact in facts
        if fact.valid_at(valid_at) and fact.recorded_by(recorded_at)
    ]
    return sorted(
        selected,
        key=lambda fact: (fact.layer, fact.entity_id, fact.predicate, fact.digest()),
    )


def migration_receipt(
    records: list[dict[str, Any]], *, from_schema: str, to_schema: str
) -> dict[str, Any]:
    """Deterministic, evidence-preserving migration receipt.

    Every input record's digest appears in the receipt; migrations add fields,
    never rewrite history (no silent evidence deletion).
    """
    input_digests = [
        hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for record in records
    ]
    migrated = [{**record, "ontology_schema": to_schema} for record in records]
    migrated.sort(key=lambda record: json.dumps(record, sort_keys=True))
    return {
        "schema": "studious.temporal-ontology.migration-receipt.v1",
        "from_schema": from_schema,
        "to_schema": to_schema,
        "input_digests": input_digests,
        "output_count": len(migrated),
        "evidence_preserved": True,
        "migrated_digest": hashlib.sha256(
            json.dumps(migrated, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "migrated": migrated,
    }


def enforce_static_runtime_separation(
    facts: list[TemporalFact],
) -> dict[str, Any]:
    """Audit helper: static facts must never carry runtime verification."""
    violations = [
        fact.digest()
        for fact in facts
        if fact.predicate in STATIC_PREDICATES
        and fact.verification_state == "RUNTIME_OBSERVED"
    ]
    return {
        "checked": len(facts),
        "violations": violations,
        "ok": not violations,
        "rule": "static predicates (CALLS_*/IMPORTS/DEFINES/TESTED_BY/CONFIGURED_BY) never upgrade to RUNTIME_OBSERVED",
    }
