"""PR-278 / CATALOG-01: searchable immutable lineage catalog."""
from __future__ import annotations

from typing import Mapping, Sequence

from .core import Mega807Error, require_id, stable_hash


def catalog_dataset_lineage(
    dataset_id: str, revisions: Sequence[str]
) -> dict[str, object]:
    require_id(dataset_id, "dataset_id")
    rows = tuple(sorted(set(revisions)))
    if not rows:
        raise Mega807Error("DATASET_REVISIONS_REQUIRED")
    return {
        "kind": "dataset",
        "id": dataset_id,
        "revisions": rows,
        "sha256": stable_hash("mega8-07-dataset-lineage", rows),
    }


def catalog_feature_lineage(
    feature_id: str, dependencies: Sequence[str]
) -> dict[str, object]:
    require_id(feature_id, "feature_id")
    deps = tuple(sorted(set(dependencies)))
    if not deps:
        raise Mega807Error("FEATURE_DEPENDENCIES_REQUIRED")
    return {
        "kind": "feature",
        "id": feature_id,
        "dependencies": deps,
        "sha256": stable_hash("mega8-07-feature-lineage", deps),
    }


def search_evidence_graph(
    entries: Sequence[Mapping[str, object]], *, term: str
) -> tuple[Mapping[str, object], ...]:
    needle = term.lower().strip()
    if not needle:
        raise Mega807Error("SEARCH_TERM_REQUIRED")
    return tuple(
        entry
        for entry in entries
        if needle in str(entry.get("id", "")).lower()
        or needle in str(entry).lower()
    )


def export_lineage_manifest(
    entries: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    ordered = tuple(sorted((dict(item) for item in entries), key=lambda row: str(row)))
    return {
        "entries": ordered,
        "sha256": stable_hash("mega8-07-lineage-manifest", ordered),
    }
