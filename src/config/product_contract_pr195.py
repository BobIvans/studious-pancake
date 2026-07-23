"""PR-195 product contract validation for config, capabilities, endpoints and secrets.

This module is intentionally offline and fail-closed. It does not resolve
credentials, contact providers or enable live trading. The goal is to bind the
existing typed runtime config and capability matrix to one product-level
contract hash that can be carried into release evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from importlib import resources
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from src.capabilities import CapabilityMatrix
from src.config.canonical import canonical_digest
from src.config.runtime import RuntimeConfig, RuntimeMode


class ProductContractError(ValueError):
    """Raised when the PR-195 product contract is malformed."""


class ContractSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ContractDiagnostic:
    code: str
    severity: ContractSeverity
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class EndpointContract:
    provider: str
    origin: str
    paths: tuple[str, ...]
    base_url_field: str
    secret_reference_fields: tuple[str, ...]
    state: str

    @classmethod
    def from_dict(cls, provider: str, raw: Mapping[str, Any]) -> "EndpointContract":
        origin = str(raw.get("origin", "")).rstrip("/")
        parsed = urlparse(origin)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in {"", "/"}
        ):
            raise ProductContractError(
                f"endpoint origin for {provider} must be an HTTPS origin without a path"
            )
        paths_raw = raw.get("paths", ())
        if not isinstance(paths_raw, list) or not paths_raw:
            raise ProductContractError(f"endpoint paths for {provider} must be a list")
        paths = tuple(str(item) for item in paths_raw)
        if any(not item.startswith("/") for item in paths):
            raise ProductContractError(
                f"endpoint paths for {provider} must be absolute REST paths"
            )
        secret_fields_raw = raw.get("secret_reference_fields", ())
        if not isinstance(secret_fields_raw, list):
            raise ProductContractError(
                f"secret_reference_fields for {provider} must be a list"
            )
        return cls(
            provider=provider,
            origin=origin,
            paths=paths,
            base_url_field=str(raw.get("base_url_field", "")),
            secret_reference_fields=tuple(str(item) for item in secret_fields_raw),
            state=str(raw.get("state", "reviewed-disabled")),
        )


@dataclass(frozen=True, slots=True)
class ProductContract:
    schema_version: str
    product_state: str
    runtime_config_schema_version: str
    live_available: bool
    endpoint_contracts: tuple[EndpointContract, ...]
    legacy_secret_aliases: Mapping[str, str]
    forbidden_generated_secret_fields: tuple[str, ...]
    raw: Mapping[str, Any]
    source_path: Path
    installed_package: bool

    @classmethod
    def _from_raw(
        cls,
        raw: Mapping[str, Any],
        *,
        source_path: Path,
        installed_package: bool,
    ) -> "ProductContract":
        endpoints_raw = raw.get("endpoints", {})
        if not isinstance(endpoints_raw, Mapping):
            raise ProductContractError("product contract endpoints must be an object")
        endpoint_contracts = tuple(
            EndpointContract.from_dict(str(provider), value)
            for provider, value in sorted(endpoints_raw.items())
        )
        legacy_aliases = raw.get("legacy_secret_aliases", {})
        if not isinstance(legacy_aliases, Mapping):
            raise ProductContractError("legacy_secret_aliases must be an object")
        forbidden_fields = raw.get("forbidden_generated_secret_fields", ())
        if not isinstance(forbidden_fields, list):
            raise ProductContractError(
                "forbidden_generated_secret_fields must be a list"
            )
        schema_version = str(raw.get("schema_version", ""))
        if schema_version != "pr195.product-contract.v1":
            raise ProductContractError("unsupported PR-195 product contract schema")
        return cls(
            schema_version=schema_version,
            product_state=str(raw.get("product_state", "")),
            runtime_config_schema_version=str(
                raw.get("runtime_config_schema_version", "")
            ),
            live_available=bool(raw.get("live_available", False)),
            endpoint_contracts=endpoint_contracts,
            legacy_secret_aliases={
                str(name): str(replacement)
                for name, replacement in legacy_aliases.items()
            },
            forbidden_generated_secret_fields=tuple(
                str(item) for item in forbidden_fields
            ),
            raw=dict(raw),
            source_path=source_path,
            installed_package=installed_package,
        )

    @classmethod
    def load(cls, path: str | Path) -> "ProductContract":
        source = Path(path).resolve()
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProductContractError(f"product contract not found: {source}") from exc
        except json.JSONDecodeError as exc:
            raise ProductContractError(
                f"invalid product contract JSON: {source}: {exc}"
            ) from exc
        if not isinstance(raw, Mapping):
            raise ProductContractError("product contract root must be an object")
        return cls._from_raw(raw, source_path=source, installed_package=False)

    @classmethod
    def load_default(cls) -> "ProductContract":
        root = Path(__file__).resolve().parents[2]
        repository_contract = root / "config" / "product_contract_pr195.json"
        if repository_contract.is_file():
            return cls.load(repository_contract)
        try:
            package_contract = resources.files("src.resources").joinpath(
                "product_contract_pr195.json"
            )
            raw = json.loads(package_contract.read_text(encoding="utf-8"))
        except (FileNotFoundError, ModuleNotFoundError, json.JSONDecodeError) as exc:
            raise ProductContractError(
                "installed PR-195 product contract is missing or malformed"
            ) from exc
        if not isinstance(raw, Mapping):
            raise ProductContractError(
                "installed product contract root must be an object"
            )
        return cls._from_raw(
            raw,
            source_path=root / "src" / "resources" / "product_contract_pr195.json",
            installed_package=True,
        )

    def contract_hash(self) -> str:
        return canonical_digest(
            self.raw,
            domain="flashloan.product-contract",
            schema_version=self.schema_version,
            environment=self.product_state,
        )

    def validate_runtime_config(
        self, config: RuntimeConfig
    ) -> tuple[ContractDiagnostic, ...]:
        diagnostics: list[ContractDiagnostic] = []
        if config.schema_version != self.runtime_config_schema_version:
            diagnostics.append(
                ContractDiagnostic(
                    "RUNTIME_SCHEMA_MISMATCH",
                    ContractSeverity.ERROR,
                    "runtime config schema is not bound to the PR-195 contract",
                )
            )
        if config.runtime.mode is RuntimeMode.LIVE and not self.live_available:
            diagnostics.append(
                ContractDiagnostic(
                    "LIVE_MODE_HARD_DENIED",
                    ContractSeverity.ERROR,
                    "live mode is unavailable in the current product contract",
                )
            )

        endpoint_values = {
            "providers.jupiter.base_url": config.providers.jupiter.base_url,
            "providers.jito.base_url": config.providers.jito.base_url,
        }
        for endpoint in self.endpoint_contracts:
            value = endpoint_values.get(endpoint.base_url_field)
            if value is None:
                diagnostics.append(
                    ContractDiagnostic(
                        "ENDPOINT_FIELD_DEFERRED",
                        ContractSeverity.INFO,
                        f"{endpoint.provider} endpoint field is not active in "
                        "RuntimeConfig",
                    )
                )
                continue
            if value.rstrip("/") != endpoint.origin:
                diagnostics.append(
                    ContractDiagnostic(
                        "ENDPOINT_ORIGIN_DRIFT",
                        ContractSeverity.ERROR,
                        f"{endpoint.base_url_field}={value!r} does not match "
                        f"contract origin {endpoint.origin!r}",
                    )
                )

        redacted = json.dumps(config.redacted_dict(), sort_keys=True)
        for field in self.forbidden_generated_secret_fields:
            if field in redacted:
                diagnostics.append(
                    ContractDiagnostic(
                        "SECRET_FIELD_LEAK",
                        ContractSeverity.ERROR,
                        "redacted configuration contains forbidden secret field "
                        f"{field!r}",
                    )
                )
        return tuple(diagnostics)

    def validate_capabilities(
        self, matrix: CapabilityMatrix
    ) -> tuple[ContractDiagnostic, ...]:
        diagnostics: list[ContractDiagnostic] = []
        if matrix.product_state != self.product_state:
            diagnostics.append(
                ContractDiagnostic(
                    "PRODUCT_STATE_MISMATCH",
                    ContractSeverity.ERROR,
                    "capability matrix product_state does not match product contract",
                )
            )
        mode_availability = {
            mode: bool(details.get("available"))
            for mode, details in matrix.runtime_modes.items()
        }
        if mode_availability.get("live", False) and not self.live_available:
            diagnostics.append(
                ContractDiagnostic(
                    "LIVE_CAPABILITY_CONTRADICTION",
                    ContractSeverity.ERROR,
                    "capability matrix advertises live while product contract "
                    "denies it",
                )
            )

        default_parts = matrix.default_command.split()
        if "--mode" in default_parts:
            selected = default_parts[default_parts.index("--mode") + 1]
            if not mode_availability.get(selected, False):
                diagnostics.append(
                    ContractDiagnostic(
                        "DEFAULT_MODE_UNAVAILABLE",
                        ContractSeverity.ERROR,
                        f"default command selects unavailable mode {selected!r}",
                    )
                )
        default_mode = None
        if "--mode" in default_parts:
            default_mode = default_parts[default_parts.index("--mode") + 1]

        for component in matrix.components:
            if (
                default_mode is not None
                and component.active_in_supported_entrypoint
                and component.kind in {"runtime", "runner"}
                and default_mode not in component.allowed_modes
            ):
                diagnostics.append(
                    ContractDiagnostic(
                        "DEFAULT_MODE_NOT_ALLOWED_BY_ACTIVE_COMPONENT",
                        ContractSeverity.ERROR,
                        f"{component.id} is active but does not allow default mode "
                        f"{default_mode!r}",
                    )
                )
            for mode in component.allowed_modes:
                if mode not in mode_availability:
                    diagnostics.append(
                        ContractDiagnostic(
                            "UNKNOWN_COMPONENT_MODE",
                            ContractSeverity.ERROR,
                            f"{component.id} allows unknown mode {mode!r}",
                        )
                    )
                if mode == "live" and not self.live_available:
                    diagnostics.append(
                        ContractDiagnostic(
                            "LIVE_COMPONENT_NOT_PERMITTED",
                            ContractSeverity.ERROR,
                            f"{component.id} allows live while product contract "
                            "denies it",
                        )
                    )
            if component.active_in_supported_entrypoint and not any(
                mode_availability.get(mode, False) for mode in component.allowed_modes
            ):
                diagnostics.append(
                    ContractDiagnostic(
                        "ACTIVE_COMPONENT_HAS_NO_AVAILABLE_MODE",
                        ContractSeverity.ERROR,
                        f"{component.id} is active but has no available runtime mode",
                    )
                )
            if (
                not self.live_available
                and component.capability.value == "live-ready"
                and component.active_in_supported_entrypoint
            ):
                diagnostics.append(
                    ContractDiagnostic(
                        "ACTIVE_LIVE_READY_COMPONENT",
                        ContractSeverity.ERROR,
                        f"{component.id} is active live-ready before live contract "
                        "approval",
                    )
                )
        return tuple(diagnostics)

    def validate_environment(
        self, environ: Mapping[str, str]
    ) -> tuple[ContractDiagnostic, ...]:
        diagnostics: list[ContractDiagnostic] = []
        for legacy_name, replacement in sorted(self.legacy_secret_aliases.items()):
            raw = environ.get(legacy_name)
            if raw is None or raw.strip() == "":
                continue
            diagnostics.append(
                ContractDiagnostic(
                    "RAW_SECRET_ENV_REJECTED",
                    ContractSeverity.ERROR,
                    f"{legacy_name} contains raw secret material; use {replacement}",
                )
            )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class ProductContractReport:
    schema_version: str
    ok: bool
    contract_hash: str
    config_hash: str
    capability_schema_version: str
    installed_contract: bool
    diagnostics: tuple[ContractDiagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "contract_hash": self.contract_hash,
            "config_hash": self.config_hash,
            "capability_schema_version": self.capability_schema_version,
            "installed_contract": self.installed_contract,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def validate_product_contract(
    config: RuntimeConfig,
    matrix: CapabilityMatrix,
    *,
    contract: ProductContract | None = None,
    environ: Mapping[str, str] | None = None,
) -> ProductContractReport:
    active_contract = contract or ProductContract.load_default()
    diagnostics = (
        active_contract.validate_runtime_config(config)
        + active_contract.validate_capabilities(matrix)
        + active_contract.validate_environment({} if environ is None else environ)
    )
    ok = not any(item.severity is ContractSeverity.ERROR for item in diagnostics)
    return ProductContractReport(
        schema_version=active_contract.schema_version,
        ok=ok,
        contract_hash=active_contract.contract_hash(),
        config_hash=config.fingerprint(),
        capability_schema_version=matrix.schema_version,
        installed_contract=active_contract.installed_package,
        diagnostics=diagnostics,
    )


__all__ = [
    "ContractDiagnostic",
    "ContractSeverity",
    "EndpointContract",
    "ProductContract",
    "ProductContractError",
    "ProductContractReport",
    "validate_product_contract",
]
