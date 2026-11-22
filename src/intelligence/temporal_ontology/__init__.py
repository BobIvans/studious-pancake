"""OCA-W15: typed temporal ontology, bitemporal facts, as-of queries."""

from .ontology import (
    LAYERS,
    RUNTIME_PREDICATES,
    STATIC_PREDICATES,
    SCHEMA,
    TemporalFact,
    as_of,
    enforce_static_runtime_separation,
    migration_receipt,
)

__all__ = [
    "LAYERS",
    "RUNTIME_PREDICATES",
    "SCHEMA",
    "STATIC_PREDICATES",
    "TemporalFact",
    "as_of",
    "enforce_static_runtime_separation",
    "migration_receipt",
]
