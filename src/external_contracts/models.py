"""Strict data model for pinned external provider contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import re
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.config.chain_registry import validate_pubkey


class ContractStatus(StrEnum):
    ACTIVE = "active"
    DISCOVERY_ONLY = "discovery-only"
    DISABLED_UNVERIFIED = "disabled-unverified"
    QUARANTINED = "quarantined"


class ContractCapability(StrEnum):
    QUOTE = "quote"
    COMPOSABLE_INSTRUCTIONS = "composable-instructions"
    IMMUTABLE_TRANSACTION = "immutable-transaction"
    BUNDLE_STATUS = "bundle-status"
    READ_ONLY_RPC = "read-only-rpc"
    PROTOCOL_SOURCE = "protocol-source"


class ArtifactKind(StrEnum):
    SANITIZED_RESPONSE = "sanitized-response"
    OFFICIAL_SOURCE = "official-source"
    REVIEW_SNAPSHOT = "review-snapshot"
    GOLDEN_BYTES = "golden-bytes"
    SCHEMA = "schema"


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_HOSTS: dict[str, frozenset[str]] = {
    "jupiter": frozenset({"dev.jup.ag", "hub.jup.ag", "github.com"}),
    "okx": frozenset({"web3.okx.com", "www.okx.com", "github.com"}),
    "jito": frozenset({"docs.jito.wtf", "github.com"}),
    "openocean": frozenset({"docs.openocean.finance", "github.com"}),
    "odos": frozenset({"docs.odos.xyz", "github.com"}),
    "marginfi": frozenset({"github.com", "docs.marginfi.com"}),
}


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactPin(FrozenModel):
    path: str
    sha256: str
    kind: ArtifactKind
    fetched_at: datetime
    required: bool = True

    @field_validator("path")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if not value or value.startswith(("/", "~")) or any(
            part in {"", ".", ".."} for part in parts
        ):
            raise ValueError("artifact path must be a normalized relative path")
        return normalized

    @field_validator("sha256")
    @classmethod
    def _real_sha256(cls, value: str) -> str:
        lowered = value.lower()
        if not _SHA256_RE.fullmatch(lowered):
            raise ValueError("artifact sha256 must contain exactly 64 lowercase hex chars")
        if lowered == "0" * 64:
            raise ValueError("placeholder all-zero artifact hashes are forbidden")
        return lowered

    @field_validator("fetched_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware ISO-8601")
        return value


class ConformanceProbe(FrozenModel):
    url: str
    credential_env: str | None = None
    expected_status: int = Field(default=200, ge=100, le=599)
    required_json_paths: tuple[str, ...] = ()

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("conformance URL must be an absolute HTTPS URL")
        return value


class ExternalContract(FrozenModel):
    id: str
    provider: str
    status: ContractStatus
    capabilities: tuple[ContractCapability, ...] = ()
    official_source_url: str
    source_ref: str
    artifacts: tuple[ArtifactPin, ...] = ()
    deployment_program_id: str | None = None
    cluster: str | None = None
    conformance_probe: ConformanceProbe | None = None
    notes: str = ""

    @field_validator("official_source_url")
    @classmethod
    def _official_https_source(cls, value: str, info: Any) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("official_source_url must be an absolute HTTPS URL")
        provider = str(info.data.get("provider", "")).lower()
        allowed = _PROVIDER_HOSTS.get(provider)
        if allowed is None or parsed.hostname.lower() not in allowed:
            raise ValueError(f"source host is not allowlisted for provider {provider!r}")
        return value

    @field_validator("deployment_program_id")
    @classmethod
    def _valid_program_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_pubkey(value, field="external_contract.deployment_program_id")

    @model_validator(mode="after")
    def _status_contract(self) -> "ExternalContract":
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("contract capabilities must be unique")
        if self.status is ContractStatus.ACTIVE and not self.artifacts:
            raise ValueError("active contracts require at least one pinned artifact")
        if self.status is not ContractStatus.ACTIVE and (
            ContractCapability.COMPOSABLE_INSTRUCTIONS in self.capabilities
        ):
            raise ValueError("only active verified contracts may claim composable instructions")
        if self.status in {ContractStatus.ACTIVE, ContractStatus.DISCOVERY_ONLY} and not all(
            artifact.required for artifact in self.artifacts
        ):
            raise ValueError("active/discovery contracts require all pins")
        return self


class ExternalContractRegistryModel(FrozenModel):
    schema_version: str = "pr027.external-contracts.v1"
    contracts: tuple[ExternalContract, ...]

    @model_validator(mode="after")
    def _unique_contract_ids(self) -> "ExternalContractRegistryModel":
        ids = [contract.id for contract in self.contracts]
        if len(ids) != len(set(ids)):
            raise ValueError("external contract ids must be unique")
        if self.schema_version != "pr027.external-contracts.v1":
            raise ValueError("unsupported external contract registry schema")
        return self
