from __future__ import annotations

import json

from src.capabilities import CapabilityMatrix
from src.config.product_contract_pr195 import (
    ContractSeverity,
    ProductContract,
    validate_product_contract,
)
from src.config.runtime import load_runtime_config


def test_pr195_default_contract_binds_config_and_capability_graph() -> None:
    config = load_runtime_config(environ={})
    matrix = CapabilityMatrix.load_default()
    report = validate_product_contract(config, matrix, environ={})

    assert report.ok is True
    payload = report.to_dict()
    assert payload["schema_version"] == "pr195.product-contract.v1"
    assert payload["contract_hash"]
    assert payload["config_hash"] == config.fingerprint()
    assert "secret" not in json.dumps(config.redacted_dict()).lower()


def test_pr195_rejects_raw_legacy_secret_environment_aliases() -> None:
    config = load_runtime_config(environ={})
    matrix = CapabilityMatrix.load_default()

    report = validate_product_contract(
        config,
        matrix,
        environ={"OKX_PASSPHRASE": "raw-passphrase"},
    )

    assert report.ok is False
    assert any(
        item.code == "RAW_SECRET_ENV_REJECTED"
        and item.severity is ContractSeverity.ERROR
        and "FLASHLOAN_OKX_API_PASSPHRASE_REFERENCE" in item.message
        for item in report.diagnostics
    )


def test_pr195_capability_graph_requires_default_mode_on_active_runtime() -> None:
    contract = ProductContract.load_default()
    config = load_runtime_config(environ={})
    loaded = CapabilityMatrix.load_default()
    raw = loaded.to_dict()

    for component in raw["components"]:
        if component["id"] == "runtime.launcher":
            component["allowed_modes"] = ["disabled"]

    matrix = CapabilityMatrix._from_raw(  # intentional direct fixture construction
        raw,
        source_path=loaded.source_path,
        root_path=loaded.root_path,
        installed_package=False,
    )
    report = validate_product_contract(config, matrix, contract=contract, environ={})

    assert report.ok is False
    assert any(
        item.code == "DEFAULT_MODE_NOT_ALLOWED_BY_ACTIVE_COMPONENT"
        for item in report.diagnostics
    )


def test_pr195_endpoint_origin_drift_is_fail_closed(tmp_path) -> None:
    config_path = tmp_path / "runtime.yaml"
    config_path.write_text(
        "providers:\n  jito:\n    base_url: "
        "https://mainnet.block-engine.jito.wtf/api/v1/bundles\n",
        encoding="utf-8",
    )

    try:
        load_runtime_config(config_path, environ={})
    except Exception as exc:
        assert "must not include" in str(exc)
    else:  # pragma: no cover - runtime validator should reject first
        raise AssertionError("endpoint-shaped Jito URL must fail closed")
