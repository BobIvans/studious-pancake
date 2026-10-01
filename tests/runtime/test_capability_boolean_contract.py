"""Reject ambiguous generated JSON before any capability is interpreted."""
from copy import deepcopy
from pathlib import Path

import pytest

from src.capabilities import (
    CapabilityContractError,
    CapabilityMatrix,
    ComponentCapability,
)


def component():
    return {
        "id": "runtime.test", "kind": "runtime", "path": "src/cli.py",
        "capability": "implemented", "active_in_supported_entrypoint": False,
        "quarantined": False, "allowed_modes": ["disabled"],
        "reason": "synthetic contract fixture", "registry_name": None,
    }


def matrix():
    return {
        "schema_version": "pr023.capabilities.v1",
        "product_state": "not-production-ready",
        "supported_entrypoint": "flashloan-bot",
        "default_command": "run --mode shadow",
        "components": [component()],
        "runtime_modes": {
            mode: {"available": mode != "live", "description": "fixture"}
            for mode in ("disabled", "paper", "shadow", "live")
        },
    }


def parse(raw):
    return CapabilityMatrix._from_raw(
        raw, source_path=Path("fixture.json"), root_path=Path("."),
        installed_package=False,
    )


INVALID_BOOLEANS = ["false", "true", "", 0, 1, None, [], {}]


@pytest.mark.parametrize("field", [
    "active_in_supported_entrypoint", "quarantined", "required_in_installed_package"
])
@pytest.mark.parametrize("value", INVALID_BOOLEANS)
def test_component_flags_require_json_booleans(field, value):
    raw = component()
    raw[field] = value
    with pytest.raises(CapabilityContractError, match=field):
        ComponentCapability.from_dict(raw)


@pytest.mark.parametrize("mode", ["disabled", "paper", "shadow", "live"])
@pytest.mark.parametrize("value", INVALID_BOOLEANS)
def test_mode_availability_requires_json_boolean(mode, value):
    raw = matrix()
    raw["runtime_modes"][mode]["available"] = value
    with pytest.raises(CapabilityContractError, match="available"):
        parse(raw)


@pytest.mark.parametrize("value", [None, [], "false", 0])
def test_component_shape_fails_with_contract_error(value):
    with pytest.raises(CapabilityContractError):
        ComponentCapability.from_dict(value)


@pytest.mark.parametrize("value", [None, [], "false", 0])
def test_mode_shape_fails_with_contract_error(value):
    raw = matrix()
    raw["runtime_modes"]["live"] = value
    with pytest.raises(CapabilityContractError):
        parse(raw)


def test_missing_mode_availability_fails_closed():
    raw = matrix()
    del raw["runtime_modes"]["live"]["available"]
    with pytest.raises(CapabilityContractError, match="available"):
        parse(raw)


@pytest.mark.parametrize("value", [False, True])
def test_valid_booleans_round_trip_without_mutation(value):
    raw = matrix()
    raw["components"][0].update(
        active_in_supported_entrypoint=value, quarantined=value,
        required_in_installed_package=value,
    )
    before = deepcopy(raw)
    parsed = parse(raw)
    assert parsed.to_dict() == raw
    assert raw == before
    assert parsed.runtime_modes["live"]["available"] is False


def test_optional_required_flag_preserves_true_default():
    assert ComponentCapability.from_dict(component()).required_in_installed_package is True


def test_quarantine_rule_remains_enforced():
    raw = component()
    raw.update(quarantined=True, allowed_modes=["shadow"])
    with pytest.raises(CapabilityContractError, match="quarantined"):
        ComponentCapability.from_dict(raw)
