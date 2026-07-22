"""Immutable runtime configuration with file -> environment -> CLI precedence."""

from __future__ import annotations

from copy import deepcopy
from enum import StrEnum
from importlib import resources
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from src.config.canonical import canonical_digest
from src.config.chain_registry import (
    ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
    COMPUTE_BUDGET_PROGRAM_ADDRESS,
    NATIVE_SOL_MINT_ADDRESS,
    SYSTEM_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
    ChainRegistry,
    ChainRegistryError,
    validate_genesis_hash,
    validate_pubkey,
)
from src.config.secret_resolver import SecretHandle, resolve_secret_reference
from src.config.strict_yaml import StrictYamlError, loads_strict_yaml


class ConfigurationLoadError(ValueError):
    """Raised when a configuration source is invalid or unsafe."""


class RuntimeMode(StrEnum):
    DISABLED = "disabled"
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


class Commitment(StrEnum):
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"


class JitoAuthMode(StrEnum):
    NONE = "none"
    UUID = "uuid"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


_SECRET_REF_PATTERN = re.compile(r"^(env|file|keychain):(.+)$")
_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SecretReference(FrozenModel):
    scheme: str
    locator: str

    @classmethod
    def parse(cls, value: str | "SecretReference" | None) -> "SecretReference" | None:
        if value is None or value == "":
            return None
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise ConfigurationLoadError("secret reference must be a string reference")
        match = _SECRET_REF_PATTERN.fullmatch(value.strip())
        if not match:
            raise ConfigurationLoadError(
                "secret reference must use env:, file:, or keychain:; "
                "inline secrets are forbidden"
            )
        scheme, locator = match.groups()
        if scheme == "env" and not _ENV_NAME_PATTERN.fullmatch(locator):
            raise ConfigurationLoadError(
                f"invalid environment secret reference: {value!r}"
            )
        if scheme == "file" and not Path(locator).is_absolute():
            raise ConfigurationLoadError(
                "file secret references must use an absolute path"
            )
        return cls(scheme=scheme, locator=locator)

    def display(self) -> str:
        return f"{self.scheme}:<redacted>"

    def fingerprint_identity(self) -> str:
        return f"{self.scheme}:{self.locator}"

    def resolve(self, *, environ: Mapping[str, str] | None = None) -> SecretHandle:
        return resolve_secret_reference(self, environ=environ)

    def resolve_from_environment(self, environ: Mapping[str, str]) -> str:
        return self.resolve(environ=environ).reveal()


class ClusterConfig(FrozenModel):
    name: str = "mainnet-beta"
    genesis_hash: str = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
    commitment: Commitment = Commitment.CONFIRMED
    rpc_http_url: str | None = None
    rpc_ws_url: str | None = None

    @field_validator("genesis_hash")
    @classmethod
    def _valid_genesis_hash(cls, value: str) -> str:
        try:
            return validate_genesis_hash(value, field="cluster.genesis_hash")
        except ChainRegistryError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("rpc_http_url")
    @classmethod
    def _valid_http_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("rpc_http_url must be an http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("RPC credentials must not be embedded in URLs")
        return value

    @field_validator("rpc_ws_url")
    @classmethod
    def _valid_ws_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
            raise ValueError("rpc_ws_url must be a ws(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("RPC credentials must not be embedded in URLs")
        return value


class RuntimeSection(FrozenModel):
    mode: RuntimeMode = RuntimeMode.DISABLED
    opportunity_queue_size: int = Field(default=1024, ge=1, le=100_000)
    shutdown_drain_timeout_ms: int = Field(default=250, ge=1, le=60_000)


class StrategyConfig(FrozenModel):
    lst_depeg: RuntimeMode = RuntimeMode.DISABLED
    lst_unstake: RuntimeMode = RuntimeMode.DISABLED
    circular_arbitrage: RuntimeMode = RuntimeMode.DISABLED

    @model_validator(mode="after")
    def _no_live_strategy_before_gate(self) -> "StrategyConfig":
        if RuntimeMode.LIVE in {
            self.lst_depeg,
            self.lst_unstake,
            self.circular_arbitrage,
        }:
            raise ValueError("strategy live mode remains unavailable before PR-046")
        return self


class WalletConfig(FrozenModel):
    public_key: str | None = None
    signer_reference: SecretReference | None = None

    @field_validator("public_key")
    @classmethod
    def _valid_public_key(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        try:
            return validate_pubkey(value, field="wallet.public_key")
        except ChainRegistryError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("signer_reference", mode="before")
    @classmethod
    def _parse_signer_reference(cls, value: Any) -> SecretReference | None:
        return SecretReference.parse(value)


class JupiterConfig(FrozenModel):
    enabled: bool = False
    base_url: str = "https://api.jup.ag"
    api_key_reference: SecretReference | None = None

    @field_validator("base_url")
    @classmethod
    def _valid_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "Jupiter base_url must be an HTTPS origin without an API path"
            )
        return value.rstrip("/")

    @field_validator("api_key_reference", mode="before")
    @classmethod
    def _parse_api_key_reference(cls, value: Any) -> SecretReference | None:
        return SecretReference.parse(value)


class JitoConfig(FrozenModel):
    enabled: bool = False
    base_url: str = "https://mainnet.block-engine.jito.wtf"
    auth_mode: JitoAuthMode = JitoAuthMode.NONE
    auth_reference: SecretReference | None = None
    min_tip_lamports: StrictInt = Field(default=1000, ge=0)

    @field_validator("base_url")
    @classmethod
    def _valid_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Jito base_url must use HTTPS")
        normalized_path = parsed.path.rstrip("/")
        if normalized_path.endswith("/api/v1/bundles") or normalized_path.endswith(
            "/api/v1/transactions"
        ):
            raise ValueError(
                "Jito base_url must not include a transaction or bundle endpoint"
            )
        return value.rstrip("/")

    @field_validator("auth_reference", mode="before")
    @classmethod
    def _parse_auth_reference(cls, value: Any) -> SecretReference | None:
        return SecretReference.parse(value)

    @model_validator(mode="after")
    def _auth_contract_matches_mode(self) -> "JitoConfig":
        if self.auth_mode is JitoAuthMode.UUID and self.auth_reference is None:
            raise ValueError(
                "Jito auth_mode=uuid requires an issued UUID secret reference"
            )
        if self.auth_mode is JitoAuthMode.NONE and self.auth_reference is not None:
            raise ValueError("Jito auth_reference requires auth_mode=uuid")
        return self


class MarginFiConfig(FrozenModel):
    enabled: bool = False
    program_id: str | None = None
    group: str | None = None
    margin_account: str | None = None
    banks: tuple[str, ...] = ()

    @field_validator("program_id", "group", "margin_account")
    @classmethod
    def _valid_optional_pubkey(cls, value: str | None, info: Any) -> str | None:
        if value is None or value == "":
            return None
        try:
            return validate_pubkey(value, field=f"providers.marginfi.{info.field_name}")
        except ChainRegistryError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("banks")
    @classmethod
    def _valid_banks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(
            validate_pubkey(item, field="providers.marginfi.banks") for item in value
        )
        if len(checked) != len(set(checked)):
            raise ValueError("MarginFi bank addresses must be unique")
        return checked

    @model_validator(mode="after")
    def _required_fields_when_enabled(self) -> "MarginFiConfig":
        if self.enabled:
            missing = [
                name
                for name, value in (
                    ("program_id", self.program_id),
                    ("group", self.group),
                    ("margin_account", self.margin_account),
                    ("banks", self.banks),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "enabled MarginFi requires explicit values for: "
                    f"{', '.join(missing)}"
                )
        return self


class ProviderConfig(FrozenModel):
    jupiter: JupiterConfig = Field(default_factory=JupiterConfig)
    jito: JitoConfig = Field(default_factory=JitoConfig)
    marginfi: MarginFiConfig = Field(default_factory=MarginFiConfig)


class MonetaryPolicy(FrozenModel):
    protected_reserve_lamports: StrictInt = Field(default=10_000_000, ge=0)
    minimum_net_profit_lamports: StrictInt = Field(default=100_000, ge=0)
    maximum_priority_fee_lamports: StrictInt = Field(default=1_000_000, ge=0)
    contingency_lamports: StrictInt = Field(default=500_000, ge=0)

    @field_validator("*")
    @classmethod
    def _integer_only(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("monetary configuration must use integer lamports")
        return value


class AllowlistConfig(FrozenModel):
    program_ids: tuple[str, ...] = (
        SYSTEM_PROGRAM_ADDRESS,
        TOKEN_PROGRAM_ADDRESS,
        TOKEN_2022_PROGRAM_ADDRESS,
        ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
        COMPUTE_BUDGET_PROGRAM_ADDRESS,
    )
    mint_ids: tuple[str, ...] = (NATIVE_SOL_MINT_ADDRESS,)

    @field_validator("program_ids")
    @classmethod
    def _valid_programs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(
            validate_pubkey(item, field="allowlist.program_ids") for item in value
        )
        if len(checked) != len(set(checked)):
            raise ValueError("allowlist.program_ids must be unique")
        return checked

    @field_validator("mint_ids")
    @classmethod
    def _valid_mints(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(
            validate_pubkey(item, field="allowlist.mint_ids") for item in value
        )
        if len(checked) != len(set(checked)):
            raise ValueError("allowlist.mint_ids must be unique")
        return checked


class AccountOwnerExpectation(FrozenModel):
    account: str
    owner: str
    label: str

    @field_validator("account", "owner")
    @classmethod
    def _valid_pubkey(cls, value: str, info: Any) -> str:
        try:
            return validate_pubkey(value, field=f"owner_expectations.{info.field_name}")
        except ChainRegistryError as exc:
            raise ValueError(str(exc)) from exc


class ValidationConfig(FrozenModel):
    verify_rpc_at_startup: bool = False
    owner_expectations: tuple[AccountOwnerExpectation, ...] = ()


class RuntimeConfig(FrozenModel):
    schema_version: str = "pr026.runtime-config.v1"
    runtime: RuntimeSection = Field(default_factory=RuntimeSection)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    strategies: StrategyConfig = Field(default_factory=StrategyConfig)
    wallet: WalletConfig = Field(default_factory=WalletConfig)
    providers: ProviderConfig = Field(default_factory=ProviderConfig)
    monetary: MonetaryPolicy = Field(default_factory=MonetaryPolicy)
    allowlist: AllowlistConfig = Field(default_factory=AllowlistConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)

    @model_validator(mode="after")
    def _cross_validate(self) -> "RuntimeConfig":
        registry = ChainRegistry.load_default()
        registry.validate_cluster(self.cluster.name, self.cluster.genesis_hash)
        additional_programs: list[str] = []
        if self.providers.marginfi.program_id:
            additional_programs.append(self.providers.marginfi.program_id)
        registry.validate_allowlisted_programs(
            self.allowlist.program_ids,
            cluster=self.cluster.name,
            additional_addresses=additional_programs,
        )
        if self.runtime.mode is RuntimeMode.LIVE:
            if self.wallet.signer_reference is None:
                raise ValueError("live mode requires an isolated signer reference")
            if not self.validation.verify_rpc_at_startup:
                raise ValueError(
                    "live mode requires RPC identity/owner validation at startup"
                )
        return self

    @property
    def strategy_modes(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "lst_depeg": self.strategies.lst_depeg.value,
                "lst_unstake": self.strategies.lst_unstake.value,
                "circular_arbitrage": self.strategies.circular_arbitrage.value,
            }
        )

    @property
    def opportunity_queue_size(self) -> int:
        return self.runtime.opportunity_queue_size

    @property
    def shutdown_drain_timeout_seconds(self) -> float:
        return self.runtime.shutdown_drain_timeout_ms / 1000

    def redacted_dict(self) -> dict[str, Any]:
        def redact(value: Any) -> Any:
            if isinstance(value, SecretReference):
                return value.display()
            if isinstance(value, BaseModel):
                return {
                    name: redact(getattr(value, name))
                    for name in type(value).model_fields
                }
            if isinstance(value, tuple):
                return [redact(item) for item in value]
            if isinstance(value, Mapping):
                return {str(key): redact(item) for key, item in value.items()}
            if isinstance(value, StrEnum):
                return value.value
            return value

        return redact(self)

    def _fingerprint_dict(self) -> dict[str, Any]:
        def normalize(value: Any) -> Any:
            if isinstance(value, SecretReference):
                return value.fingerprint_identity()
            if isinstance(value, BaseModel):
                return {
                    name: normalize(getattr(value, name))
                    for name in type(value).model_fields
                }
            if isinstance(value, tuple):
                return [normalize(item) for item in value]
            if isinstance(value, Mapping):
                return {str(key): normalize(item) for key, item in value.items()}
            if isinstance(value, StrEnum):
                return value.value
            return value

        return normalize(self)

    def safe_display(self) -> dict[str, Any]:
        return self.redacted_dict()

    def identity_payload(self) -> dict[str, Any]:
        return self._fingerprint_dict()

    def runtime_materialization(self) -> dict[str, Any]:
        return self._fingerprint_dict()

    def fingerprint(self) -> str:
        return canonical_digest(
            self.identity_payload(),
            domain="flashloan.runtime-config",
            schema_version=self.schema_version,
            environment=self.cluster.name,
        )


_ENV_BINDINGS: dict[str, tuple[str, str]] = {
    "FLASHLOAN_RUNTIME_MODE": ("runtime.mode", "str"),
    "FLASHLOAN_OPPORTUNITY_QUEUE_SIZE": ("runtime.opportunity_queue_size", "int"),
    "FLASHLOAN_SHUTDOWN_DRAIN_TIMEOUT_MS": (
        "runtime.shutdown_drain_timeout_ms",
        "int",
    ),
    "FLASHLOAN_CLUSTER_NAME": ("cluster.name", "str"),
    "FLASHLOAN_CLUSTER_GENESIS_HASH": ("cluster.genesis_hash", "str"),
    "FLASHLOAN_COMMITMENT": ("cluster.commitment", "str"),
    "SOLANA_RPC_HTTP": ("cluster.rpc_http_url", "str"),
    "SOLANA_RPC_WS": ("cluster.rpc_ws_url", "str"),
    "FLASHLOAN_WALLET_PUBLIC_KEY": ("wallet.public_key", "str"),
    "FLASHLOAN_SIGNER_REFERENCE": ("wallet.signer_reference", "str"),
    "FLASHLOAN_JUPITER_ENABLED": ("providers.jupiter.enabled", "bool"),
    "FLASHLOAN_JUPITER_BASE_URL": ("providers.jupiter.base_url", "str"),
    "FLASHLOAN_JUPITER_API_KEY_REFERENCE": (
        "providers.jupiter.api_key_reference",
        "str",
    ),
    "FLASHLOAN_JITO_ENABLED": ("providers.jito.enabled", "bool"),
    "FLASHLOAN_JITO_BASE_URL": ("providers.jito.base_url", "str"),
    "FLASHLOAN_JITO_AUTH_MODE": ("providers.jito.auth_mode", "str"),
    "FLASHLOAN_JITO_AUTH_REFERENCE": ("providers.jito.auth_reference", "str"),
    "FLASHLOAN_JITO_MIN_TIP_LAMPORTS": ("providers.jito.min_tip_lamports", "int"),
    "FLASHLOAN_MARGINFI_ENABLED": ("providers.marginfi.enabled", "bool"),
    "FLASHLOAN_MARGINFI_PROGRAM_ID": ("providers.marginfi.program_id", "str"),
    "FLASHLOAN_MARGINFI_GROUP": ("providers.marginfi.group", "str"),
    "FLASHLOAN_MARGINFI_ACCOUNT": ("providers.marginfi.margin_account", "str"),
    "FLASHLOAN_MARGINFI_BANKS": ("providers.marginfi.banks", "csv"),
    "FLASHLOAN_PROTECTED_RESERVE_LAMPORTS": (
        "monetary.protected_reserve_lamports",
        "int",
    ),
    "FLASHLOAN_MINIMUM_NET_PROFIT_LAMPORTS": (
        "monetary.minimum_net_profit_lamports",
        "int",
    ),
    "FLASHLOAN_MAXIMUM_PRIORITY_FEE_LAMPORTS": (
        "monetary.maximum_priority_fee_lamports",
        "int",
    ),
    "FLASHLOAN_CONTINGENCY_LAMPORTS": ("monetary.contingency_lamports", "int"),
    "FLASHLOAN_ALLOWLIST_PROGRAM_IDS": ("allowlist.program_ids", "csv"),
    "FLASHLOAN_ALLOWLIST_MINT_IDS": ("allowlist.mint_ids", "csv"),
    "FLASHLOAN_VERIFY_RPC_AT_STARTUP": ("validation.verify_rpc_at_startup", "bool"),
}

_DANGEROUS_LEGACY_FLAGS = {
    "LIVE_TRADING_ENABLED",
    "JITO_ENABLED",
    "KAMINO_LIQUIDATION_ENABLED",
    "OKX_EXECUTION_PROMOTION_ENABLED",
}


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(dict(result[key]), value)
        else:
            result[key] = deepcopy(value)
    return result


def _set_dotted(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        nested = current.setdefault(part, {})
        if not isinstance(nested, dict):
            raise ConfigurationLoadError(f"cannot override non-object path: {path}")
        current = nested
    current[parts[-1]] = value


def _parse_scalar(raw: str, kind: str, *, name: str) -> Any:
    value = raw.strip()
    if kind == "str":
        return value or None
    if kind == "int":
        if not re.fullmatch(r"-?[0-9]+", value):
            raise ConfigurationLoadError(f"{name} must be an integer, got {raw!r}")
        return int(value)
    if kind == "bool":
        lowered = value.lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
        raise ConfigurationLoadError(f"{name} must be a strict boolean")
    if kind == "csv":
        return tuple(item.strip() for item in value.split(",") if item.strip())
    raise ConfigurationLoadError(f"unsupported configuration parser: {kind}")


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        return loads_strict_yaml(path.read_text(encoding="utf-8"))
    except (OSError, StrictYamlError) as exc:
        raise ConfigurationLoadError(
            f"cannot read configuration file {path}: {exc}"
        ) from exc


def _default_payload() -> dict[str, Any]:
    resource = resources.files("src.resources").joinpath("runtime.default.yaml")
    try:
        return loads_strict_yaml(resource.read_text(encoding="utf-8"))
    except StrictYamlError as exc:
        raise ConfigurationLoadError("packaged runtime defaults are invalid") from exc


def load_runtime_config(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> RuntimeConfig:
    """Load one immutable configuration with strict source precedence.

    Precedence is packaged fail-closed defaults, optional YAML file,
    environment variables, then explicit CLI overrides.
    """
    env = os.environ if environ is None else environ
    for name in _DANGEROUS_LEGACY_FLAGS:
        raw = env.get(name)
        if raw and raw.strip().lower() in {"1", "true", "yes"}:
            raise ConfigurationLoadError(
                f"legacy activation flag {name}=true is rejected; "
                "use typed PR-026 configuration"
            )

    payload = _default_payload()
    configured_path = path or env.get("FLASHLOAN_CONFIG_FILE")
    if configured_path:
        payload = _deep_merge(payload, _read_yaml(Path(configured_path)))

    env_overlay: dict[str, Any] = {}
    for name, (dotted_path, kind) in _ENV_BINDINGS.items():
        if name in env and env[name] != "":
            _set_dotted(
                env_overlay,
                dotted_path,
                _parse_scalar(env[name], kind, name=name),
            )
    payload = _deep_merge(payload, env_overlay)

    if cli_overrides:
        cli_overlay: dict[str, Any] = {}
        for dotted_path, value in cli_overrides.items():
            _set_dotted(cli_overlay, dotted_path, value)
        payload = _deep_merge(payload, cli_overlay)

    try:
        return RuntimeConfig.model_validate(payload)
    except Exception as exc:
        raise ConfigurationLoadError(str(exc)) from exc
