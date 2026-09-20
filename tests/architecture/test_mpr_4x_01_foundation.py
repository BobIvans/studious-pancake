from __future__ import annotations

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
