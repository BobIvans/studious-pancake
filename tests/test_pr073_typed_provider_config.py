from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.config.runtime import ConfigurationLoadError, load_runtime_config
from src.runtime_discovery import RuntimeDiscoveryUniverse, build_runtime_discovery
from src.runtime_discovery_models import RuntimeDiscoveryPair
from src.routing.provider_config import (
    DiscoveryProviderRuntimeConfig,
    build_provider_registry_from_config,
)
from src.strategy.detectors import DetectorPair

pytestmark = pytest.mark.unit

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WALLET = "11111111111111111111111111111111"


def _empty_contract_registry() -> SimpleNamespace:
    return SimpleNamespace(provider=lambda _name: ())


def _config():
    return load_runtime_config(
        environ={
            "FLASHLOAN_WALLET_PUBLIC_KEY": WALLET,
        }
    )


def _universe() -> RuntimeDiscoveryUniverse:
    return RuntimeDiscoveryUniverse(
        schema_version="pr056.discovery-universe.v1",
        pairs=(
            RuntimeDiscoveryPair(
                pair=DetectorPair(
                    pair_id="sol-usdc-loop",
                    base_mint=SOL,
                    intermediate_mint=USDC,
                    probe_amount_base_units=100_000_000,
                    min_gross_profit_base_units=100_000,
                    max_snapshot_age_seconds=5.0,
                    ttl_seconds=2.0,
                    cooldown_seconds=0.0,
                    max_slot_skew=2,
                ),
                base_decimals=9,
                intermediate_decimals=6,
                required=True,
            ),
        ),
        cycle_timeout_seconds=1.0,
        provider_timeout_seconds=0.5,
        max_concurrent_pairs=1,
        max_candidates=64,
    )


def test_raw_legacy_credentials_do_not_enable_untyped_discovery_provider() -> None:
    registry = build_provider_registry_from_config(
        _config(),
        {
            "OKX_API_KEY": "raw-key",
            "OKX_PASSPHRASE": "raw-passphrase",
            "OKX_SECRET_KEY": "raw-secret",
            "OPENOCEAN_API_KEY": "raw-openocean-key",
        },
        contract_registry=_empty_contract_registry(),
    )

    assert registry.adapters == ()


def test_typed_okx_secret_references_enable_only_redacted_sanitized_env() -> None:
    environ = {
        "FLASHLOAN_OKX_ENABLED": "true",
        "FLASHLOAN_OKX_API_KEY_REFERENCE": "env:OKX_API_KEY",
        "FLASHLOAN_OKX_PASSPHRASE_REFERENCE": "env:OKX_PASSPHRASE",
        "FLASHLOAN_OKX_SECRET_KEY_REFERENCE": "env:OKX_SECRET_KEY",
        "OKX_API_KEY": "okx-api-key",
        "OKX_PASSPHRASE": "okx-passphrase",
        "OKX_SECRET_KEY": "okx-secret-key",
    }

    provider_config = DiscoveryProviderRuntimeConfig.from_runtime(_config(), environ)

    assert provider_config.enabled_provider_ids == frozenset({"okx_dex"})
    assert provider_config.sanitized_environment() == {
        "OKX_API_KEY": "okx-api-key",
        "OKX_PASSPHRASE": "okx-passphrase",
        "OKX_SECRET_KEY": "okx-secret-key",
    }
    assert "okx-secret-key" not in repr(provider_config)
    redacted = provider_config.redacted_dict()
    assert redacted["okx"]["api_key_reference"] == "env:<redacted>"
    assert redacted["okx"]["passphrase_reference"] == "env:<redacted>"
    assert redacted["okx"]["secret_key_reference"] == "env:<redacted>"


def test_invalid_typed_provider_enablement_fails_closed() -> None:
    with pytest.raises(ConfigurationLoadError, match="FLASHLOAN_ODOS_ENABLED"):
        DiscoveryProviderRuntimeConfig.from_runtime(
            _config(),
            {"FLASHLOAN_ODOS_ENABLED": "sometimes"},
        )


def test_runtime_discovery_uses_typed_provider_admission_boundary() -> None:
    coordinator = build_runtime_discovery(
        _config(),
        environ={
            "OKX_API_KEY": "raw-key",
            "OKX_PASSPHRASE": "raw-passphrase",
            "OKX_SECRET_KEY": "raw-secret",
        },
        universe=_universe(),
        contract_registry=_empty_contract_registry(),
    )

    assert coordinator.plane.registry.adapters == ()
