from __future__ import annotations

import json

import pytest

from scripts.verify_mpr_4x_01_foundation import build_evidence
from src.contracts import (
    PayloadValidationError,
    SchemaRegistry,
    SchemaRegistryError,
    get_schema_registry,
)
from src.contracts.reachability import classify_module
from src.release import ReleaseGenerationIdentity


def test_foundation_verifier_accepts_current_installed_surface() -> None:
    evidence = build_evidence()
    assert evidence["accepted"] is True, evidence["errors"]
    assert evidence["release_unknown_field_rejected"] is True
    assert evidence["schema_registry_source_owners"] == ["src/contracts/registry.py"]
    assert evidence["missing_wheel_members"] == []


def test_registry_rejects_duplicate_json_keys() -> None:
    with pytest.raises(SchemaRegistryError, match="duplicate JSON key"):
        SchemaRegistry.from_json_text(
            '{"schema_id":"canonical.schema-registry.v1",'
            '"schema_id":"canonical.schema-registry.v1"}'
        )


def test_release_identity_uses_strict_registered_schema() -> None:
    digest = "a" * 64
    with pytest.raises(PayloadValidationError):
        ReleaseGenerationIdentity(
            source_sha="b" * 40,
            wheel_sha256=digest,
            image_digest="sha256:not-a-digest",
            schema_registry_sha256=digest,
            config_identity="fixture",
            provider_registry_sha256=digest,
            capability_manifest_sha256=digest,
            production_surface_sha256=digest,
            runtime_authority_sha256=digest,
            dependency_lock_sha256=digest,
            migration_set_sha256=digest,
        )


def test_reachability_classifies_every_declared_boundary() -> None:
    assert classify_module("src.contracts.registry") == "canonical"
    assert classify_module("src.cli_pr189") == "compatibility-alias"
    assert classify_module("src.execution.senders.rpc") == "quarantined"
    assert classify_module("src.capabilities") == "installed-support"
    assert "mpr-4x-01.architecture-reachability.v1" in (
        get_schema_registry().active_ids
    )


def _versioned_schema_registry(
    previous_schema: dict[str, object],
    candidate_schema: dict[str, object],
    *,
    candidate_schema_id: str = "fixture.sample.v2",
) -> SchemaRegistry:
    def record(schema_id: str, schema: dict[str, object]) -> dict[str, object]:
        return {
            "schema_id": schema_id,
            "owner_module": "tests.schema_compatibility",
            "boundary_class": "runtime-contract",
            "compatibility": "backward-readable",
            "unknown_fields": "reject",
            "canonical_encoding": "canonical-json-v1",
            "max_bytes": 65536,
            "max_depth": 16,
            "max_nodes": 4096,
            "max_list_items": 256,
            "max_string_length": 4096,
            "max_integer_abs": 9223372036854775807,
            "status": "active",
            "validation_mode": "json-schema",
            "schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                **schema,
            },
        }

    payload = {
        "authority": {
            "module": "src.contracts.registry",
            "resource": "src/resources/schema_registry.json",
            "canonical_json_module": "src.kernel.canonical_json",
            "hash_module": "src.kernel.hashing",
        },
        "dialect": "https://json-schema.org/draft/2020-12/schema",
        "schema_id": "canonical.schema-registry.v1",
        "schemas": [
            record("fixture.sample.v1", previous_schema),
            record(candidate_schema_id, candidate_schema),
        ],
    }
    return SchemaRegistry.from_json_text(json.dumps(payload))


def _object_schema(
    *, required: tuple[str, ...], extra_properties: bool
) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "label": {"type": "string", "minLength": 1},
            "version": {"type": "integer", "minimum": 1},
        },
        "required": list(required),
        "additionalProperties": extra_properties,
    }


def test_schema_registry_accepts_backward_and_forward_compatible_versions() -> None:
    schema = _object_schema(required=("id",), extra_properties=True)
    registry = _versioned_schema_registry(schema, schema)

    report = registry.check_compatibility(
        previous_schema_id="fixture.sample.v1",
        candidate_schema_id="fixture.sample.v2",
        mode="FULL",
        backward_fixtures=({"id": "old-record"},),
        forward_fixtures=({"id": "new-record", "label": "optional"},),
    )

    assert report.compatible is True
    assert report.backward_fixtures_checked == 1
    assert report.forward_fixtures_checked == 1
    assert report.findings == ()
    assert report.evidence_level == "fixture-sampled-not-schema-subsumption-proof"


def test_schema_registry_detects_backward_incompatibility() -> None:
    previous = _object_schema(required=("id",), extra_properties=True)
    candidate = _object_schema(required=("id", "version"), extra_properties=True)
    registry = _versioned_schema_registry(previous, candidate)

    report = registry.check_compatibility(
        previous_schema_id="fixture.sample.v1",
        candidate_schema_id="fixture.sample.v2",
        mode="BACKWARD",
        backward_fixtures=({"id": "legacy-record"},),
    )

    assert report.compatible is False
    assert report.findings[0].startswith("BACKWARD_INCOMPATIBLE:0:")


def test_schema_registry_detects_forward_incompatibility() -> None:
    previous = _object_schema(required=("id",), extra_properties=False)
    candidate = _object_schema(required=("id",), extra_properties=True)
    registry = _versioned_schema_registry(previous, candidate)

    report = registry.check_compatibility(
        previous_schema_id="fixture.sample.v1",
        candidate_schema_id="fixture.sample.v2",
        mode="FORWARD",
        forward_fixtures=({"id": "new-record", "new_field": "new-field"},),
    )

    assert report.compatible is False
    assert report.findings[0].startswith("FORWARD_INCOMPATIBLE:0:")


def test_schema_registry_rejects_invalid_compatibility_fixture() -> None:
    schema = _object_schema(required=("id",), extra_properties=True)
    registry = _versioned_schema_registry(schema, schema)

    report = registry.check_compatibility(
        previous_schema_id="fixture.sample.v1",
        candidate_schema_id="fixture.sample.v2",
        mode="BACKWARD",
        backward_fixtures=({"label": "missing-id"},),
    )

    assert report.compatible is False
    assert report.findings[0].startswith("BACKWARD_SOURCE_FIXTURE_INVALID:0:")


def test_schema_registry_requires_ordered_versions_and_fixtures() -> None:
    schema = _object_schema(required=("id",), extra_properties=True)
    registry = _versioned_schema_registry(schema, schema)

    with pytest.raises(SchemaRegistryError, match="newer"):
        registry.check_compatibility(
            previous_schema_id="fixture.sample.v2",
            candidate_schema_id="fixture.sample.v1",
            mode="BACKWARD",
            backward_fixtures=({"id": "record"},),
        )

    with pytest.raises(SchemaRegistryError, match="requires previous-version fixtures"):
        registry.check_compatibility(
            previous_schema_id="fixture.sample.v1",
            candidate_schema_id="fixture.sample.v2",
            mode="BACKWARD",
        )


def test_schema_registry_rejects_cross_family_compatibility() -> None:
    schema = _object_schema(required=("id",), extra_properties=True)
    registry = _versioned_schema_registry(
        schema, schema, candidate_schema_id="other.sample.v2"
    )

    with pytest.raises(SchemaRegistryError, match="same schema family"):
        registry.check_compatibility(
            previous_schema_id="fixture.sample.v1",
            candidate_schema_id="other.sample.v2",
            mode="BACKWARD",
            backward_fixtures=({"id": "record"},),
        )
