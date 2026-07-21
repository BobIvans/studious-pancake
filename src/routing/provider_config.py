"""Typed provider configuration for runtime discovery composition.

This module closes the PR-073 gap where the discovery registry was still fed
by broad process environment variables.  It builds a small, redacted,
provider-specific credential environment from typed runtime configuration and
explicit provider enablement flags before constructing the discovery registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.config.runtime import ConfigurationLoadError, RuntimeConfig, SecretReference
from src.providers.jupiter.quota import JupiterQuotaManager
from src.routing.registry import ProviderRegistry
from src.routing.transport import Transport

_TRUE_VALUES = frozenset({"1", "true", "yes"})
_FALSE_VALUES = frozenset({"0", "false", "no"})

JUPITER_PROVIDER_ID = "jupiter_router"
OKX_PROVIDER_ID = "okx_dex"
OPENOCEAN_PROVIDER_ID = "openocean"
ODOS_PROVIDER_ID = "odos"


def _env_bool(environ: Mapping[str, str], name: str) -> bool | None:
    raw = environ.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise ConfigurationLoadError(f"{name} must be a strict boolean")


def _provider_section(config: RuntimeConfig, name: str) -> Any | None:
    providers = getattr(config, "providers", None)
    return getattr(providers, name, None) if providers is not None else None


def _enabled(
    section: Any | None,
    environ: Mapping[str, str],
    env_name: str,
    *,
    default: bool = False,
) -> bool:
    env_value = _env_bool(environ, env_name)
    if env_value is not None:
        return env_value
    if section is not None and hasattr(section, "enabled"):
        return bool(getattr(section, "enabled"))
    return default


def _coerce_secret_reference(value: Any, label: str) -> Any | None:
    if value is None or value == "":
        return None
    if isinstance(value, (str, SecretReference)):
        return SecretReference.parse(value)
    if hasattr(value, "resolve_from_environment"):
        # Some older unit tests pass a minimal duck-typed secret reference.  Keep
        # accepting it here so this PR changes provider admission only, not the
        # public build_runtime_discovery test contract.
        return value
    raise ConfigurationLoadError(f"{label} must be a secret reference")


def _secret_reference(
    section: Any | None,
    environ: Mapping[str, str],
    env_name: str,
    attribute: str,
) -> Any | None:
    raw = environ.get(env_name)
    if raw is not None and raw != "":
        return _coerce_secret_reference(raw, env_name)
    if section is not None and hasattr(section, attribute):
        return _coerce_secret_reference(getattr(section, attribute), attribute)
    return None


def _resolve(
    reference: Any | None,
    environ: Mapping[str, str],
) -> str | None:
    if reference is None:
        return None
    return reference.resolve_from_environment(environ)


def _redacted(reference: Any | None) -> str | None:
    if reference is None:
        return None
    if hasattr(reference, "display"):
        return str(reference.display())
    return "secret:<redacted>"


@dataclass(frozen=True)
class DiscoveryProviderRuntimeConfig:
    """Runtime-admitted provider settings with secret-safe representation."""

    jupiter_enabled: bool = False
    jupiter_api_key_reference: Any | None = None
    jupiter_api_key: str | None = field(default=None, repr=False)
    okx_enabled: bool = False
    okx_api_key_reference: Any | None = None
    okx_passphrase_reference: Any | None = None
    okx_secret_key_reference: Any | None = None
    okx_api_key: str | None = field(default=None, repr=False)
    okx_passphrase: str | None = field(default=None, repr=False)
    okx_secret_key: str | None = field(default=None, repr=False)
    openocean_enabled: bool = False
    openocean_api_key_reference: Any | None = None
    openocean_api_key: str | None = field(default=None, repr=False)
    odos_enabled: bool = False

    @classmethod
    def from_runtime(
        cls,
        config: RuntimeConfig,
        environ: Mapping[str, str],
    ) -> "DiscoveryProviderRuntimeConfig":
        jupiter = _provider_section(config, "jupiter")
        okx = _provider_section(config, "okx")
        openocean = _provider_section(config, "openocean")
        odos = _provider_section(config, "odos")

        jupiter_ref = _secret_reference(
            jupiter,
            environ,
            "FLASHLOAN_JUPITER_API_KEY_REFERENCE",
            "api_key_reference",
        )
        okx_api_ref = _secret_reference(
            okx,
            environ,
            "FLASHLOAN_OKX_API_KEY_REFERENCE",
            "api_key_reference",
        )
        okx_passphrase_ref = _secret_reference(
            okx,
            environ,
            "FLASHLOAN_OKX_PASSPHRASE_REFERENCE",
            "passphrase_reference",
        )
        okx_secret_ref = _secret_reference(
            okx,
            environ,
            "FLASHLOAN_OKX_SECRET_KEY_REFERENCE",
            "secret_key_reference",
        )
        openocean_ref = _secret_reference(
            openocean,
            environ,
            "FLASHLOAN_OPENOCEAN_API_KEY_REFERENCE",
            "api_key_reference",
        )

        return cls(
            jupiter_enabled=_enabled(
                jupiter,
                environ,
                "FLASHLOAN_JUPITER_ENABLED",
            ),
            jupiter_api_key_reference=jupiter_ref,
            jupiter_api_key=_resolve(jupiter_ref, environ),
            okx_enabled=_enabled(okx, environ, "FLASHLOAN_OKX_ENABLED"),
            okx_api_key_reference=okx_api_ref,
            okx_passphrase_reference=okx_passphrase_ref,
            okx_secret_key_reference=okx_secret_ref,
            okx_api_key=_resolve(okx_api_ref, environ),
            okx_passphrase=_resolve(okx_passphrase_ref, environ),
            okx_secret_key=_resolve(okx_secret_ref, environ),
            openocean_enabled=_enabled(
                openocean,
                environ,
                "FLASHLOAN_OPENOCEAN_ENABLED",
            ),
            openocean_api_key_reference=openocean_ref,
            openocean_api_key=_resolve(openocean_ref, environ),
            odos_enabled=_enabled(odos, environ, "FLASHLOAN_ODOS_ENABLED"),
        )

    @property
    def enabled_provider_ids(self) -> frozenset[str]:
        provider_ids: set[str] = set()
        if self.jupiter_enabled:
            provider_ids.add(JUPITER_PROVIDER_ID)
        if self.okx_enabled:
            provider_ids.add(OKX_PROVIDER_ID)
        if self.openocean_enabled:
            provider_ids.add(OPENOCEAN_PROVIDER_ID)
        if self.odos_enabled:
            provider_ids.add(ODOS_PROVIDER_ID)
        return frozenset(provider_ids)

    def sanitized_environment(self) -> dict[str, str]:
        """Return only provider credentials admitted by typed configuration."""

        result: dict[str, str] = {}
        if self.jupiter_enabled and self.jupiter_api_key:
            result["JUPITER_API_KEY"] = self.jupiter_api_key
        if self.okx_enabled:
            if self.okx_api_key:
                result["OKX_API_KEY"] = self.okx_api_key
            if self.okx_passphrase:
                result["OKX_PASSPHRASE"] = self.okx_passphrase
            if self.okx_secret_key:
                result["OKX_SECRET_KEY"] = self.okx_secret_key
        if self.openocean_enabled and self.openocean_api_key:
            result["OPENOCEAN_API_KEY"] = self.openocean_api_key
        return result

    def redacted_dict(self) -> dict[str, Any]:
        return {
            "jupiter": {
                "enabled": self.jupiter_enabled,
                "api_key_reference": _redacted(self.jupiter_api_key_reference),
                "resolved": self.jupiter_api_key is not None,
            },
            "okx": {
                "enabled": self.okx_enabled,
                "api_key_reference": _redacted(self.okx_api_key_reference),
                "passphrase_reference": _redacted(self.okx_passphrase_reference),
                "secret_key_reference": _redacted(self.okx_secret_key_reference),
                "resolved": all(
                    (
                        self.okx_api_key,
                        self.okx_passphrase,
                        self.okx_secret_key,
                    )
                ),
            },
            "openocean": {
                "enabled": self.openocean_enabled,
                "api_key_reference": _redacted(self.openocean_api_key_reference),
                "resolved": self.openocean_api_key is not None,
            },
            "odos": {
                "enabled": self.odos_enabled,
            },
        }


def build_provider_registry_from_config(
    config: RuntimeConfig,
    environ: Mapping[str, str],
    *,
    transport: Transport | None = None,
    jupiter_quota: JupiterQuotaManager | None = None,
    contract_registry: Any = None,
) -> ProviderRegistry:
    """Build discovery providers from typed config, not broad process env."""

    provider_config = DiscoveryProviderRuntimeConfig.from_runtime(config, environ)
    registry_kwargs: dict[str, Any] = {
        "transport": transport,
        "jupiter_quota": jupiter_quota,
    }
    if contract_registry is not None:
        registry_kwargs["contract_registry"] = contract_registry
    registry = ProviderRegistry.from_env(
        provider_config.sanitized_environment(),
        **registry_kwargs,
    )
    return ProviderRegistry(
        tuple(
            adapter
            for adapter in registry.adapters
            if adapter.provider_id in provider_config.enabled_provider_ids
        )
    )
