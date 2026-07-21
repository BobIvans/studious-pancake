"""Strict data model for pinned external provider contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

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


class CredentialMode(StrEnum):
    NONE = "none"
    HEADER_API_KEY = "header-api-key"
    BEARER_TOKEN = "bearer-token"
    OKX_SIGNED = "okx-signed"
    OPTIONAL_UUID = "optional-uuid"
    WHITELIST_API_KEY = "whitelist-api-key"


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"


class JsonValueType(StrEnum):
    OBJECT = "object"
    ARRAY = "array"
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    NULL = "null"


class JsonSemanticType(StrEnum):
    PUBKEY = "pubkey"
    INTEGER_STRING = "integer-string"


class PromotionState(StrEnum):
    LOCAL_ARTIFACT_INTEGRITY_ONLY = "local-artifact-integrity-only"
    REMOTE_SCHEMA_FRESHNESS_PENDING = "remote-schema-freshness-pending"
    CREDENTIALED_CONFORMANCE_PENDING = "credentialed-conformance-pending"
    DEPLOYMENT_ATTESTATION_PENDING = "deployment-attestation-pending"
    EXECUTION_CONFORMANCE_PENDING = "execution-conformance-pending"
    PROMOTION_EVIDENCE_PENDING = "promotion-evidence-pending"
    EXECUTION_ALLOWED = "execution-allowed"


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_HOSTS: dict[str, frozenset[str]] = {
    "jupiter": frozenset(
        {"dev.jup.ag", "developers.jup.ag", "hub.jup.ag", "github.com"}
    ),
    "okx": frozenset({"web3.okx.com", "www.okx.com", "github.com"}),
    "jito": frozenset({"docs.jito.wtf", "github.com"}),
    "openocean": frozenset({"docs.openocean.finance", "github.com"}),
    "odos": frozenset({"docs.odos.xyz", "github.com"}),
    "marginfi": frozenset({"github.com", "docs.marginfi.com"}),
}
_JSON_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9_\-]+")


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JsonPathAssertion(FrozenModel):
    path: str
    value_type: JsonValueType | None = None
    min_size: int | None = Field(default=None, ge=0)
    expected_value: str | int | float | bool | None = None
    enum_values: tuple[str | int | float | bool, ...] = ()
    semantic_type: JsonSemanticType | None = None
    array_item_semantic_type: JsonSemanticType | None = None

    @field_validator("path")
    @classmethod
    def _valid_json_path(cls, value: str) -> str:
        if not value:
            raise ValueError("json assertion path must not be empty")
        segments = value.split(".")
        if any(not _JSON_PATH_SEGMENT_RE.fullmatch(segment) for segment in segments):
            raise ValueError(f"invalid json path segment in {value!r}")
        return value

    @model_validator(mode="after")
    def _semantic_contract(self) -> "JsonPathAssertion":
        if self.min_size is not None and self.value_type not in {
            JsonValueType.ARRAY,
            JsonValueType.OBJECT,
        }:
            raise ValueError("min_size assertions require array or object value_type")
        if self.enum_values and self.value_type is JsonValueType.ARRAY:
            raise ValueError("enum_values apply to scalar JSON values, not arrays")
        if (
            self.semantic_type
            in {JsonSemanticType.PUBKEY, JsonSemanticType.INTEGER_STRING}
            and self.value_type is not JsonValueType.STRING
        ):
            raise ValueError("scalar semantic assertions require string value_type")
        if (
            self.array_item_semantic_type is not None
            and self.value_type is not JsonValueType.ARRAY
        ):
            raise ValueError("array item semantic assertions require array value_type")
        return self


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
            raise ValueError(
                "artifact sha256 must contain exactly 64 lowercase hex chars"
            )
        if lowered == "0" * 64:
            raise ValueError("placeholder all-zero artifact hashes are forbidden")
        return lowered

    @field_validator("fetched_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware ISO-8601")
        return value


class ContractEvidence(FrozenModel):
    local_artifact_integrity: bool = False
    remote_schema_freshness: bool = False
    credentialed_api_conformance: bool = False
    deployed_program_attestation: bool = False
    execution_conformance: bool = False
    promotion_evidence: bool = False

    @property
    def execution_allowed(self) -> bool:
        return (
            self.local_artifact_integrity
            and self.remote_schema_freshness
            and self.credentialed_api_conformance
            and self.execution_conformance
            and self.promotion_evidence
        )


class ConformanceProbe(FrozenModel):
    url: str
    method: HttpMethod = HttpMethod.GET
    credential_env: str | None = None
    credential_mode: CredentialMode = CredentialMode.NONE
    required_env: tuple[str, ...] = ()
    optional_env: tuple[str, ...] = ()
    credential_header_name: str | None = None
    credential_header_env: str | None = None
    expected_status: int = Field(default=200, ge=100, le=599)
    required_json_paths: tuple[str, ...] = ()
    forbidden_json_paths: tuple[str, ...] = ()
    json_assertions: tuple[JsonPathAssertion, ...] = ()
    business_code_path: str | None = None
    business_code_equals: str | int | None = None
    json_body: dict[str, Any] | None = None
    timeout_seconds: int = Field(default=10, ge=1, le=60)

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("conformance URL must be an absolute HTTPS URL")
        return value

    @field_validator("required_env", "optional_env")
    @classmethod
    def _environment_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for name in value:
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", name):
                raise ValueError(f"invalid environment variable name: {name}")
        if len(set(value)) != len(value):
            raise ValueError("environment variable names must be unique")
        return value

    @field_validator("credential_header_name")
    @classmethod
    def _header_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", value):
            raise ValueError("invalid credential header name")
        return value

    @field_validator(
        "required_json_paths", "forbidden_json_paths", "business_code_path"
    )
    @classmethod
    def _json_path_names(
        cls, value: tuple[str, ...] | str | None
    ) -> tuple[str, ...] | str | None:
        if value is None:
            return None
        paths = (value,) if isinstance(value, str) else value
        for path in paths:
            segments = path.split(".")
            if not path or any(
                not _JSON_PATH_SEGMENT_RE.fullmatch(segment) for segment in segments
            ):
                raise ValueError(f"invalid json path: {path!r}")
        return value

    @model_validator(mode="after")
    def _credential_contract(self) -> "ConformanceProbe":
        if self.credential_env and not self.required_env:
            return self
        if self.credential_header_env and self.credential_header_env not in (
            self.required_env + self.optional_env
        ):
            raise ValueError("credential_header_env must be declared in env lists")
        if self.credential_header_name and not self.credential_header_env:
            raise ValueError("credential_header_name requires credential_header_env")
        if self.credential_mode in {
            CredentialMode.HEADER_API_KEY,
            CredentialMode.BEARER_TOKEN,
            CredentialMode.WHITELIST_API_KEY,
        } and not (self.required_env or self.credential_env):
            raise ValueError("credentialed probes must declare required_env")
        if self.credential_mode is CredentialMode.OKX_SIGNED:
            missing = {
                "OKX_API_KEY",
                "OKX_SECRET_KEY",
                "OKX_API_PASSPHRASE",
            }.difference(self.required_env)
            if missing:
                raise ValueError(
                    f"okx-signed probe missing required env: {sorted(missing)}"
                )
        if (self.business_code_path is None) != (self.business_code_equals is None):
            raise ValueError("business code assertions require path and expected value")
        self._validate_protocol_shape()
        return self

    def _validate_protocol_shape(self) -> None:
        parsed = urlparse(self.url)
        hostname = (parsed.hostname or "").lower()
        query = parse_qs(parsed.query)
        if hostname == "api.jup.ag" and parsed.path == "/swap/v2/build":
            if not query.get("taker"):
                raise ValueError("Jupiter /swap/v2/build conformance requires taker")
            invalid_transaction_paths = (
                set(self.required_json_paths)
                | {assertion.path for assertion in self.json_assertions}
            )
            if "transaction" in invalid_transaction_paths:
                raise ValueError(
                    "Jupiter /swap/v2/build conformance must assert raw "
                    "instruction fields, not legacy transaction"
                )
        if "jito" in hostname and parsed.path.endswith("/getTipAccounts"):
            if self.method is not HttpMethod.POST:
                raise ValueError("Jito getTipAccounts conformance must use POST")
            if not self.json_body or self.json_body.get("method") != "getTipAccounts":
                raise ValueError(
                    "Jito getTipAccounts conformance requires JSON-RPC body"
                )


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
    promotion_state: PromotionState = PromotionState.LOCAL_ARTIFACT_INTEGRITY_ONLY
    evidence: ContractEvidence = Field(default_factory=ContractEvidence)
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
            raise ValueError(
                f"source host is not allowlisted for provider {provider!r}"
            )
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
            raise ValueError(
                "only active verified contracts may claim composable instructions"
            )
        if self.status in {
            ContractStatus.ACTIVE,
            ContractStatus.DISCOVERY_ONLY,
        } and not all(artifact.required for artifact in self.artifacts):
            raise ValueError("active/discovery contracts require all pins")
        if (
            self.promotion_state is PromotionState.EXECUTION_ALLOWED
            and not self.execution_allowed
        ):
            raise ValueError(
                "execution-allowed promotion requires all execution evidence gates"
            )
        if self.execution_allowed and self.status is not ContractStatus.ACTIVE:
            raise ValueError("only active contracts can become execution-allowed")
        return self

    @property
    def execution_allowed(self) -> bool:
        if (
            self.deployment_program_id
            and not self.evidence.deployed_program_attestation
        ):
            return False
        return self.evidence.execution_allowed


class ExternalContractRegistryModel(FrozenModel):
    schema_version: str = "pr054.external-contracts.v2"
    contracts: tuple[ExternalContract, ...]

    @model_validator(mode="after")
    def _registry_contract(self) -> "ExternalContractRegistryModel":
        ids = [contract.id for contract in self.contracts]
        if len(ids) != len(set(ids)):
            raise ValueError("external contract ids must be unique")
        if self.schema_version not in {
            "pr027.external-contracts.v1",
            "pr054.external-contracts.v2",
        }:
            raise ValueError("unsupported external contract registry schema")
        return self
