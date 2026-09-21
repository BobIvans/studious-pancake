from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from scripts.verify_pr354_mechanism_discovery import verify
from src.mechanism_discovery.core import MechanismDiscoveryError
from src.mechanism_discovery.hook_native import ingest_v4_hook_registry
from src.mechanism_discovery.manifest import (
    FUNCTION_COUNT,
    NF_IDS,
    NF_TO_SYMBOL,
    PACKAGES,
)
from src.mechanism_discovery.operationalize import bind_concrete_source_to_evo

ROOT = Path(__file__).resolve().parents[2]


def _point_in_time() -> dict[str, object]:
    return {
        "event_time": 10,
        "received_at": 11,
        "available_at": 12,
        "finality": "FINALIZED",
        "source_licensed": True,
        "source_entitled": True,
        "value_atoms": 100,
    }


def test_exact_nf_surface_and_every_symbol_imports() -> None:
    assert FUNCTION_COUNT == 96
    assert NF_IDS == tuple(range(1089, 1185))
    assert tuple(PACKAGES) == tuple(f"RND-{index:02d}" for index in range(12))
    assert len({row[2] for row in NF_TO_SYMBOL.values()}) == 96
    for _nf, (_package, module_name, symbol) in NF_TO_SYMBOL.items():
        module = importlib.import_module(f"src.mechanism_discovery.{module_name}")
        assert callable(getattr(module, symbol))


def test_all_packages_default_off_and_effect_boundary_false() -> None:
    payload = json.loads(
        (ROOT / "config/mechanism_discovery.json").read_text(encoding="utf-8")
    )
    assert all(row["state"] == "DISABLED" for row in payload["packages"].values())
    assert all(row["live"] is False for row in payload["packages"].values())
    assert not any(payload["effect_boundary"].values())
    assert payload["source_copy_performed"] is False


def test_contract_identity_is_deterministic_across_mapping_order() -> None:
    left = bind_concrete_source_to_evo({"source_id": "s", "deployment": "d"})
    right = bind_concrete_source_to_evo({"deployment": "d", "source_id": "s"})
    assert left.evidence_hash == right.evidence_hash
    assert left.payload["execution_queue_allowed"] is False
    assert left.payload["live_authority"] is False
    assert left.payload["auto_promotion"] is False


def test_future_data_leakage_fails_closed() -> None:
    with pytest.raises(MechanismDiscoveryError, match="FUTURE_DATA_LEAKAGE"):
        ingest_v4_hook_registry(
            {
                **_point_in_time(),
                "event_time": 10,
                "received_at": 20,
                "available_at": 15,
            }
        )


def test_missing_point_in_time_fields_fail_closed() -> None:
    with pytest.raises(
        MechanismDiscoveryError, match="POINT_IN_TIME_FIELDS_REQUIRED"
    ):
        ingest_v4_hook_registry({"event_time": 1})


def test_secret_and_effect_material_are_rejected() -> None:
    with pytest.raises(MechanismDiscoveryError, match="SECRET_DETECTED"):
        bind_concrete_source_to_evo({"private_key": "x"})
    with pytest.raises(MechanismDiscoveryError, match="EFFECT_AUTHORITY_FORBIDDEN"):
        bind_concrete_source_to_evo({"live_enabled": True})


def test_non_exact_float_is_rejected() -> None:
    with pytest.raises(MechanismDiscoveryError, match="NON_EXACT_RESEARCH_VALUE"):
        bind_concrete_source_to_evo({"price": 1.5})


def test_unadmitted_or_stale_source_fails_closed() -> None:
    with pytest.raises(MechanismDiscoveryError, match="SOURCE_NOT_ADMITTED"):
        bind_concrete_source_to_evo({"source_licensed": False})
    with pytest.raises(
        MechanismDiscoveryError, match="STALE_OR_CONTRADICTED_STATE"
    ):
        bind_concrete_source_to_evo({"stale": True})


def test_each_package_representative_contract_is_sender_free() -> None:
    representatives: dict[str, tuple[str, str]] = {}
    for _nf, (package, module_name, symbol) in NF_TO_SYMBOL.items():
        representatives.setdefault(package, (module_name, symbol))
    for package, (module_name, symbol) in representatives.items():
        module = importlib.import_module(f"src.mechanism_discovery.{module_name}")
        function = getattr(module, symbol)
        payload = _point_in_time()
        report = function(payload)
        assert report.package == package
        assert report.payload["research_only"] is True
        assert report.payload["execution_queue_allowed"] is False
        assert report.payload["live_authority"] is False


def test_hypothesis_registry_is_exactly_36_preregistered_rows() -> None:
    payload = json.loads(
        (ROOT / "docs/mechanism_discovery/hypothesis_registry.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["preregistered"] is True
    assert len(payload["rows"]) == 36
    assert [row["id"] for row in payload["rows"]] == [
        f"H-{index:02d}" for index in range(1, 37)
    ]
    assert all(row["execution_right"] is False for row in payload["rows"])


def test_source_provenance_is_reference_only() -> None:
    payload = json.loads(
        (ROOT / "docs/mechanism_discovery/source_provenance.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["copy_or_port_performed"] is False
    assert all(row["reuse_mode"] == "REFERENCE_ONLY" for row in payload["rows"])
    assert all(row["source_copy_allowed"] is False for row in payload["rows"])


def test_structural_verifier_accepts_repository_tree() -> None:
    payload = verify()
    assert payload["accepted"] is True, payload["errors"]
    assert payload["function_count"] == 96
    assert payload["hypothesis_count"] == 36
    assert payload["live_enabled"] is False
