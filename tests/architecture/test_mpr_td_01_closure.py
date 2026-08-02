from __future__ import annotations

from scripts.verify_mpr_td_01_canonical_surface import build_evidence
from src.contracts import SchemaRegistry, SchemaRegistryError


def test_canonical_surface_and_registry_are_accepted() -> None:
    evidence = build_evidence()
    assert evidence["accepted"] is True, evidence["errors"]
    assert evidence["semantic_owner"] == "src.cli_entrypoint"
    assert evidence["alias_line_count"] < 80


def test_schema_registry_rejects_unknown_schema() -> None:
    registry = SchemaRegistry.load_default()
    assert "failure.reason-code-registry.v1" in registry.active_ids
    try:
        registry.require("unknown.schema.v1")
    except SchemaRegistryError:
        pass
    else:
        raise AssertionError("unknown schema was accepted")
