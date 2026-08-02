"""Immutable release generation identity."""

from __future__ import annotations

from dataclasses import dataclass
import re

from src.kernel import canonical_json_bytes, domain_sha256

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


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
        if not re.fullmatch(r"[0-9a-f]{40}", self.source_sha):
            raise ValueError("source_sha must be a lowercase 40-character Git SHA")
        for field_name in (
            "wheel_sha256",
            "schema_registry_sha256",
            "provider_registry_sha256",
            "capability_manifest_sha256",
            "production_surface_sha256",
            "runtime_authority_sha256",
            "dependency_lock_sha256",
            "migration_set_sha256",
        ):
            if not _HEX64.fullmatch(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        if (
            self.image_digest is not None
            and not self.image_digest.startswith("sha256:")
        ):
            raise ValueError("image_digest must use sha256:<digest> form")
        if not self.config_identity or len(self.config_identity) > 256:
            raise ValueError("config_identity must be non-empty and bounded")

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
        return domain_sha256(
            domain="release-generation",
            schema_id=self.schema_id,
            payload=canonical_json_bytes(self.payload()),
        )
