from __future__ import annotations

from pathlib import Path

import pytest

from src.config.runtime import (
    ConfigurationLoadError,
    JitoAuthMode,
    RuntimeMode,
    SecretReference,
    load_runtime_config,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_are_immutable_fail_closed_and_have_no_external_addresses() -> None:
    config = load_runtime_config(environ={})

    assert config.runtime.mode is RuntimeMode.DISABLED
    assert config.providers.jupiter.enabled is False
    assert config.providers.jito.enabled is False
    assert config.providers.jito.auth_mode is JitoAuthMode.NONE
    assert config.providers.marginfi.enabled is False
    assert config.providers.marginfi.program_id is None
    assert config.providers.marginfi.group is None
    assert config.providers.marginfi.margin_account is None
    assert config.providers.marginfi.banks == ()

    with pytest.raises(Exception):
        config.runtime.mode = RuntimeMode.LIVE  # type: ignore[misc]
    with pytest.raises(TypeError):
        config.strategy_modes["lst_depeg"] = "live"  # type: ignore[index]


def test_precedence_is_file_then_environment_then_cli(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "runtime.yaml",
        """
runtime:
  opportunity_queue_size: 111
  shutdown_drain_timeout_ms: 900
monetary:
  protected_reserve_lamports: 20000000
""",
    )
    config = load_runtime_config(
        path,
        environ={
            "FLASHLOAN_OPPORTUNITY_QUEUE_SIZE": "222",
            "FLASHLOAN_PROTECTED_RESERVE_LAMPORTS": "21000000",
        },
        cli_overrides={
            "runtime.opportunity_queue_size": 333,
            "monetary.protected_reserve_lamports": 22_000_000,
        },
    )

    assert config.opportunity_queue_size == 333
    assert config.runtime.shutdown_drain_timeout_ms == 900
    assert config.monetary.protected_reserve_lamports == 22_000_000


def test_unknown_fields_and_float_money_fail_closed(tmp_path: Path) -> None:
    unknown = _write(tmp_path / "unknown.yaml", "runtime:\n  surprise: true\n")
    with pytest.raises(ConfigurationLoadError, match="surprise"):
        load_runtime_config(unknown, environ={})

    floating = _write(
        tmp_path / "float.yaml",
        "monetary:\n  protected_reserve_lamports: 1.0\n",
    )
    with pytest.raises(ConfigurationLoadError, match="integer"):
        load_runtime_config(floating, environ={})


def test_environment_integer_parser_rejects_decimal_money() -> None:
    with pytest.raises(ConfigurationLoadError, match="must be an integer"):
        load_runtime_config(environ={"FLASHLOAN_PROTECTED_RESERVE_LAMPORTS": "0.015"})


def test_secret_references_are_structural_and_redacted(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "secrets.yaml",
        """
wallet:
  signer_reference: env:SOLANA_SIGNER_REF
providers:
  jupiter:
    api_key_reference: keychain:jupiter/api
  jito:
    enabled: true
    auth_mode: uuid
    auth_reference: env:JITO_AUTH_UUID
""",
    )
    config = load_runtime_config(path, environ={})
    payload = config.redacted_dict()

    assert isinstance(config.wallet.signer_reference, SecretReference)
    assert payload["wallet"]["signer_reference"] == "env:<redacted>"
    assert payload["providers"]["jupiter"]["api_key_reference"] == "keychain:<redacted>"
    assert payload["providers"]["jito"]["auth_reference"] == "env:<redacted>"
    assert "SOLANA_SIGNER_REF" not in str(payload)
    assert "JITO_AUTH_UUID" not in str(payload)


def test_inline_secret_and_endpoint_shaped_jito_url_are_rejected(
    tmp_path: Path,
) -> None:
    inline = _write(
        tmp_path / "inline.yaml",
        "wallet:\n  signer_reference: this-is-private-key-material\n",
    )
    with pytest.raises(ConfigurationLoadError, match="inline secrets are forbidden"):
        load_runtime_config(inline, environ={})

    endpoint = _write(
        tmp_path / "endpoint.yaml",
        (
            "providers:\n  jito:\n    base_url: "
            "https://mainnet.block-engine.jito.wtf/api/v1/bundles\n"
        ),
    )
    with pytest.raises(ConfigurationLoadError, match="must not include"):
        load_runtime_config(endpoint, environ={})


def test_legacy_activation_flags_cannot_promote_runtime() -> None:
    for name in (
        "LIVE_TRADING_ENABLED",
        "JITO_ENABLED",
        "KAMINO_LIQUIDATION_ENABLED",
        "OKX_EXECUTION_PROMOTION_ENABLED",
    ):
        with pytest.raises(ConfigurationLoadError, match=name):
            load_runtime_config(environ={name: "true"})


def test_marginfi_requires_all_addresses_when_enabled(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "marginfi.yaml",
        "providers:\n  marginfi:\n    enabled: true\n",
    )
    with pytest.raises(ConfigurationLoadError, match="enabled MarginFi requires"):
        load_runtime_config(path, environ={})


def test_live_config_requires_signer_and_rpc_attestation(tmp_path: Path) -> None:
    path = _write(tmp_path / "live.yaml", "runtime:\n  mode: live\n")
    with pytest.raises(ConfigurationLoadError, match="isolated signer reference"):
        load_runtime_config(path, environ={})
