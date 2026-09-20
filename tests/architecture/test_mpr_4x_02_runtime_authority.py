from __future__ import annotations

import copy

import pytest

import src.runtime_authority as canonical
import src.runtime_authority_pr01 as compatibility

pytestmark = pytest.mark.unit


def test_canonical_runtime_authority_is_accepted() -> None:
    report = canonical.evaluate_runtime_authority_map()

    assert report.accepted is True
    assert report.blockers == ()
    assert report.schema_version == "mpr-4x-02.runtime-authority.v1"
    assert report.active_composition_root == "src.cli_pr189:main"


def test_legacy_module_is_only_a_compatibility_alias() -> None:
    assert compatibility.evaluate_runtime_authority_map is canonical.evaluate_runtime_authority_map
    assert compatibility.SemanticCommandIdentity is canonical.SemanticCommandIdentity
    assert compatibility.TerminalTransitionTable is canonical.TerminalTransitionTable


def test_second_active_runtime_surface_fails_closed() -> None:
    payload = copy.deepcopy(canonical.load_default_authority_map())
    payload["alternate_runtime_surfaces"][0]["active"] = True

    report = canonical.evaluate_runtime_authority_map(payload)

    assert report.accepted is False
    assert any(item.startswith("ALTERNATE_RUNTIME_ACTIVE") for item in report.blockers)


def test_runtime_safety_boundary_cannot_enable_live() -> None:
    payload = copy.deepcopy(canonical.load_default_authority_map())
    payload["active_composition_root"]["live_enabled"] = True

    report = canonical.evaluate_runtime_authority_map(payload)

    assert report.accepted is False
    assert "RUNTIME_SAFETY_BOUNDARY_INVALID" in report.blockers


def test_capital_identity_requires_attempt_generation() -> None:
    payload = copy.deepcopy(canonical.load_default_authority_map())
    payload["capital_reservation_policy"]["reservation_id_bindings"].remove(
        "attempt_generation"
    )

    report = canonical.evaluate_runtime_authority_map(payload)

    assert report.accepted is False
    assert any(item.startswith("CAPITAL_BINDINGS_MISSING") for item in report.blockers)
