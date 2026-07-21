from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config.chain_registry import ChainRegistry
from src.config.doctor import run_config_doctor
from src.config.runtime import load_runtime_config


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_offline_doctor_passes_fail_closed_defaults() -> None:
    config = load_runtime_config(environ={})
    report = run_config_doctor(config, environ={})

    assert report.ok is True
    assert report.config_fingerprint == config.fingerprint()
    assert any(item.code == "CLUSTER_IDENTITY_VALID" for item in report.diagnostics)
    assert any(item.code == "PROGRAM_ALLOWLIST_VALID" for item in report.diagnostics)


def test_secret_check_requires_uuid_shaped_jito_credential(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "jito.yaml",
        (
            "providers:\n  jito:\n    enabled: true\n    auth_mode: uuid\n"
            "    auth_reference: env:JITO_AUTH_UUID\n"
        ),
    )
    config = load_runtime_config(path, environ={})

    missing = run_config_doctor(config, check_secrets=True, environ={})
    assert missing.ok is False
    assert any(item.code == "SECRET_RESOLUTION_FAILED" for item in missing.diagnostics)

    malformed = run_config_doctor(
        config,
        check_secrets=True,
        environ={"JITO_AUTH_UUID": "random-hex-is-not-a-uuid"},
    )
    assert malformed.ok is False
    assert any(item.code == "JITO_AUTH_NOT_UUID" for item in malformed.diagnostics)

    valid = run_config_doctor(
        config,
        check_secrets=True,
        environ={"JITO_AUTH_UUID": "123e4567-e89b-42d3-a456-426614174000"},
    )
    assert valid.ok is True


def test_online_doctor_attests_genesis_and_account_owners(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "rpc.yaml",
        "cluster:\n  rpc_http_url: https://rpc.example.invalid\n",
    )
    config = load_runtime_config(path, environ={})
    registry = ChainRegistry.load_default()

    def rpc_call(method: str, params: list[Any]) -> Any:
        if method == "getGenesisHash":
            return config.cluster.genesis_hash
        if method == "getMultipleAccounts":
            addresses = params[0]
            owners = {
                entry.address: entry.owner
                for entry in registry.entries
                if entry.owner is not None
            }
            return {"value": [{"owner": owners[address]} for address in addresses]}
        raise AssertionError(method)

    report = run_config_doctor(
        config,
        registry=registry,
        online=True,
        environ={},
        rpc_call=rpc_call,
    )
    assert report.ok is True
    assert any(item.code == "RPC_CLUSTER_MATCH" for item in report.diagnostics)
    assert sum(item.code == "ACCOUNT_OWNER_MATCH" for item in report.diagnostics) >= 1


def test_online_doctor_fails_on_cluster_or_owner_mismatch(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "rpc.yaml",
        "cluster:\n  rpc_http_url: https://rpc.example.invalid\n",
    )
    config = load_runtime_config(path, environ={})

    def wrong_cluster(method: str, params: list[Any]) -> Any:
        if method == "getGenesisHash":
            return "EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
        raise AssertionError(method)

    report = run_config_doctor(config, online=True, environ={}, rpc_call=wrong_cluster)
    assert report.ok is False
    assert any(item.code == "RPC_CLUSTER_MISMATCH" for item in report.diagnostics)
