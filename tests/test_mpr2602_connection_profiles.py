"""Synthetic offline profile vectors; no external credentials or permissions."""

import json
from pathlib import Path
import pytest
from src.provider_governance.profile import (
    load_connection_profile,
    ConnectionProfileError,
)
from src.provider_governance.runtime import ProviderGovernance


def payload():
    return {
        "schema_version": "mpr2602.connections.v1",
        "connections": [
            {
                "provider_id": "solana_rpc",
                "kind": "outbound_rpc",
                "enabled": True,
                "reviewed": True,
                "review_ref": "synthetic-review",
                "endpoint": "https://rpc.example/",
                "credential": {
                    "ref": "synthetic-rpc",
                    "generation": "g1",
                    "env_name": "TEST_RPC_API_KEY",
                },
                "entitlement": {
                    "generation": "g1",
                    "operations": ["discovery"],
                    "window_seconds": 60,
                    "request_limit": 10,
                    "cost_unit_limit": 10,
                    "spend_limit_micros": 0,
                    "max_concurrency": 1,
                    "expires_at_epoch_seconds": 2000000000,
                    "spend_window_seconds": 86400,
                },
                "http_methods": ["POST"],
                "rpc_methods": ["getSlot"],
                "query_parameters": [],
                "quota_pool_ref": "synthetic-test-pool",
            }
        ],
    }


def write(tmp_path, value):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(value), encoding="utf8")
    return path


def test_all_shipped_examples_disabled_and_no_network(tmp_path):
    root = Path(__file__).parents[1] / "config/external_connections/profiles"
    paths = list(root.glob("*.example.json"))
    assert len(paths) >= 5
    for path in paths:
        profile = load_connection_profile(path)
        assert not profile.entitlements
        assert not profile.credential_bindings
        assert not profile.credential_env_names
        assert all(status.startswith("disabled") for _, status in profile.statuses)


def test_approved_profile_reuses_runtime_loader_without_loading_env(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TEST_RPC_API_KEY", "sentinel-not-to-be-read-or-emitted")
    path = write(tmp_path, payload())
    profile = load_connection_profile(path)
    assert profile.credential_bindings["solana_rpc"] == ("synthetic-rpc", "g1")
    assert profile.credential_env_names["solana_rpc"] == "TEST_RPC_API_KEY"
    assert "sentinel-not-to-be-read-or-emitted" not in repr(profile)
    runtime = ProviderGovernance.from_profile(path)
    assert runtime.entitlement("solana_rpc") == profile.entitlements["solana_rpc"]
    assert runtime.connection_profile.profile_sha256 == profile.profile_sha256
    with pytest.raises(TypeError):
        profile.credential_bindings["solana_rpc"] = ("x", "y")


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "boolnumeric",
        "secreturl",
        "send",
        "fraction",
        "signing",
        "querysecret",
        "unknownnested",
        "malformedkind",
        "timestamp_ms",
    ],
)
def test_unsafe_profiles_rejected_with_safe_reason(tmp_path, mutation):
    value = payload()
    item = value["connections"][0]
    if mutation == "unknown":
        item["api_key"] = "sentinel-secret"
    if mutation == "boolnumeric":
        item["entitlement"]["request_limit"] = True
    if mutation == "secreturl":
        item["endpoint"] = "https://user:sentinel-secret@rpc.example/"
    if mutation == "send":
        item["rpc_methods"] = ["sendTransaction"]
    if mutation == "fraction":
        item["entitlement"]["request_limit"] = 1.5
    if mutation == "signing":
        item["credential"]["env_name"] = "SOLANA_PRIVATE_KEY"
    if mutation == "querysecret":
        item["query_parameters"] = ["api-key"]
    if mutation == "unknownnested":
        item["credential"]["value"] = "sentinel-secret"
    if mutation == "timestamp_ms":
        item["entitlement"]["expires_at_epoch_seconds"] = 2000000000000
    if mutation == "malformedkind":
        item["kind"] = {}
    with pytest.raises(ConnectionProfileError) as caught:
        load_connection_profile(write(tmp_path, value))
    assert "sentinel-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"x","schema_version":"x","connections":[]}',
        b"[" * 100 + b"]" * 100,
        b" " * 65537,
        b'{"x":NaN}',
        b"\xff",
    ],
    ids=["duplicate", "depth", "bytes", "nonfinite", "utf8"],
)
def test_json_boundary_limits(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    with pytest.raises(ConnectionProfileError):
        load_connection_profile(path)


@pytest.mark.parametrize(
    "kind,provider,status",
    [
        ("outbound_rpc", "unknown_provider", "disabled_unknown_provider"),
        ("inbound_webhook", "solana_rpc", "disabled_inbound_unimplemented"),
    ],
)
def test_unknown_and_inbound_never_emit_permission(tmp_path, kind, provider, status):
    value = payload()
    value["connections"][0]["kind"] = kind
    value["connections"][0]["provider_id"] = provider
    profile = load_connection_profile(write(tmp_path, value))
    assert not profile.entitlements
    assert profile.statuses == ((provider, status),)


def test_unreviewed_enabled_profile_remains_disabled(tmp_path):
    value = payload()
    value["connections"][0]["reviewed"] = False
    profile = load_connection_profile(write(tmp_path, value))
    assert not profile.entitlements
    assert profile.statuses[0][1] == "disabled_unreviewed"


def test_installed_cli_target_and_combined_starter(capsys):
    import tomllib
    from src.provider_governance.cli import main

    root = Path(__file__).parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf8"))
    assert (
        metadata["project"]["scripts"]["flashloan-connections"]
        == "src.provider_governance.cli:main"
    )
    starter = root / "config/external_connections/profile.example.json"
    assert main([str(starter)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["reviewed_outbound_profiles"] == 0
    assert report["network_effects"] == 0
    assert report["secrets_loaded"] == 0
    assert len(report["statuses"]) == 5
    assert "/profile.local.json" in (starter.parent / ".gitignore").read_text(
        encoding="utf8"
    )


def test_cli_schema_failure_never_prints_payload(tmp_path, capsys):
    from src.provider_governance.cli import main

    value = payload()
    value["connections"][0]["secret"] = "must-never-be-printed"
    assert main([str(write(tmp_path, value))]) == 1
    output = capsys.readouterr().out
    assert "must-never-be-printed" not in output
    assert json.loads(output) == {"valid": False, "reason": "registered_schema_invalid"}


def test_profile_uses_installed_canonical_schema_resource(tmp_path, monkeypatch):
    from src.contracts.registry import get_schema_registry, SchemaRegistry

    registry = get_schema_registry()
    record = registry.require("mpr2602.connections.v1")
    assert record.owner_module == "src.provider_governance.profile"
    assert record.validation_mode == "json-schema"
    assert record.limits.max_bytes == 65536
    calls = []
    original = SchemaRegistry.validate_payload

    def observed(self, schema_id, value):
        calls.append(schema_id)
        return original(self, schema_id, value)

    monkeypatch.setattr(SchemaRegistry, "validate_payload", observed)
    load_connection_profile(write(tmp_path, payload()))
    assert calls == ["mpr2602.connections.v1"]
