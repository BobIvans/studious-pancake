"""Registry enforcement and admission before runtime resource acquisition."""

import json

import pytest

from src.contracts.registry import SchemaRegistryError, get_schema_registry, _load_json
from src.runtime_authority import (
    RuntimeAuthorityError,
    SemanticCommandIdentity,
    evaluate_runtime_authority_map,
    load_default_authority_map,
)


@pytest.mark.parametrize("nested", [False, True])
def test_unregistered_control_override_rejected(nested):
    payload = load_default_authority_map()
    target = payload["active_composition_root"] if nested else payload
    target["unregistered_control_override"] = True
    assert not evaluate_runtime_authority_map(payload).accepted


@pytest.mark.parametrize(
    "bad_hash", ["short", "A" * 64, "g" * 64, "a" * 65, "a" * 63, "a" * 63 + "\n"]
)
def test_hash_format_is_enforced_by_registered_contract(bad_hash):
    with pytest.raises(RuntimeAuthorityError):
        SemanticCommandIdentity(
            "attempt", 1, "candidate", "reservation", bad_hash, "b" * 64
        )


def test_duplicate_json_key_rejected():
    with pytest.raises(SchemaRegistryError, match="duplicate JSON key"):
        _load_json('{"schema_version":"first","schema_version":"second"}')


def test_generation_bound_is_enforced():
    with pytest.raises(RuntimeAuthorityError):
        SemanticCommandIdentity(
            "attempt", 2**63, "candidate", "reservation", "a" * 64, "b" * 64
        )


def test_registered_resource_round_trip():
    payload = json.loads(json.dumps(load_default_authority_map()))
    encoded = get_schema_registry().validate_payload(payload["schema_version"], payload)
    assert json.loads(encoded) == payload


def test_invalid_resource_closes_runtime_before_service_build(monkeypatch, capsys):
    import src.runtime_authority as authority
    import src.runtime.runtime_entrypoint as runtime

    def invalid():
        raise RuntimeAuthorityError("tampered resource")

    def forbidden(*args, **kwargs):
        pytest.fail("service must not be built after failed authority admission")

    monkeypatch.setattr(authority, "load_default_authority_map", invalid)
    monkeypatch.setattr(runtime, "build_installed_durable_paper_service", forbidden)
    assert runtime.main(["run", "--mode", "paper"]) == runtime.EXIT_ADMISSION_BLOCKED
    assert "RUNTIME_AUTHORITY_INVALID" in capsys.readouterr().err
