"""Immutable release generation identity."""

from __future__ import annotations

from dataclasses import dataclass

from src.contracts import get_schema_registry


@dataclass(frozen=True, slots=True)
class ReleaseGenerationIdentity:
    """Identity of one immutable installed release generation."""

    source_sha: str
    wheel_sha256: str
    image_digest: str | None
    schema_registry_sha256: str
    config_identity: str
    provider_registry_sha256: str
    capability_manifest_sha256: str
    production_surface_sha256: str
    runtime_authority_sha256: str
    dependency_lock_sha256: str
    migration_set_sha256: str
    schema_id: str = "release-generation-identity.v1"

    def __post_init__(self) -> None:
        get_schema_registry().validate_payload(
            self.schema_id,
            self.payload(),
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_id": self.schema_id,
            "source_sha": self.source_sha,
            "wheel_sha256": self.wheel_sha256,
            "image_digest": self.image_digest,
            "schema_registry_sha256": self.schema_registry_sha256,
            "config_identity": self.config_identity,
            "provider_registry_sha256": self.provider_registry_sha256,
            "capability_manifest_sha256": self.capability_manifest_sha256,
            "production_surface_sha256": self.production_surface_sha256,
            "runtime_authority_sha256": self.runtime_authority_sha256,
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "migration_set_sha256": self.migration_set_sha256,
        }

    @property
    def generation_id(self) -> str:
        return get_schema_registry().payload_digest(
            domain="release-generation",
            schema_id=self.schema_id,
            payload=self.payload(),
        )
