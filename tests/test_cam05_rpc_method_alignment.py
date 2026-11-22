"""CAM-05: sender-free RPC method alignment across the three registries.

Call-site proof (capture path, verified 2026-11-22):
- src/market/native_cpmm_capture.py:363  getGenesisHash
- src/market/native_cpmm_capture.py:368/390  getMultipleAccounts
- src/market/native_cpmm_capture.py:411  getBlock
- src/qualification_campaign/rpc.py:59  getVersion
- src/qualification_campaign/rpc.py:61/63  getSlot
The static scan below re-derives the set from the source bytes so any new
call site must be registered before CI can pass (no convenience expansion:
getBlock/getVersion are added to the MPR2602 enum BECAUSE they are really
called; getBlockHeight stays out while it has no call site).
"""

import json
import re
from pathlib import Path

import pytest

from src.qualification_campaign.profiles import READ_RPC_METHODS, ProviderProfile

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
CALL_SITES = (
    ROOT / "src/market/native_cpmm_capture.py",
    ROOT / "src/qualification_campaign/rpc.py",
)
_METHOD_RE = re.compile(r'"(get[A-Z][A-Za-z]*)"')


def registry_rpc_enum() -> set[str]:
    raw = json.loads((ROOT / "src/resources/schema_registry.json").read_bytes())
    schemas = raw.get("schemas", raw)
    for schema in (schemas.values() if isinstance(schemas, dict) else schemas):
        if not isinstance(schema, dict) or schema.get("schema_id") != (
            "mpr2602.connections.v1"
        ):
            continue

        def find_rpc_methods_enum(node):
            if isinstance(node, dict):
                if "rpc_methods" in node:
                    items = node["rpc_methods"].get("items", {})
                    if isinstance(items.get("enum"), list):
                        return items["enum"]
                for value in node.values():
                    found = find_rpc_methods_enum(value)
                    if found is not None:
                        return found
            elif isinstance(node, list):
                for item in node:
                    found = find_rpc_methods_enum(item)
                    if found is not None:
                        return found
            return None

        enum = find_rpc_methods_enum(schema.get("schema", schema))
        if enum:
            return set(enum)
    raise AssertionError("mpr2602.connections.v1 rpc_methods enum not found")


def governance_rpc_methods() -> set[str]:
    """The sender-free hard-coded set in provider_governance.runtime."""
    source = (ROOT / "src/provider_governance/runtime.py").read_text()
    marker = "sender-free"
    position = source.find(marker)
    block = source[position : position + 2000]
    return set(_METHOD_RE.findall(block))


def actual_capture_methods() -> set[str]:
    """Every RPC method string literally present at collector call sites."""

    methods: set[str] = set()
    for path in CALL_SITES:
        methods |= set(_METHOD_RE.findall(path.read_text()))
    return methods


def test_every_actual_rpc_method_is_registered_everywhere():
    actual = actual_capture_methods()
    assert (
        actual == READ_RPC_METHODS
    ), "capture call sites and ProviderProfile.READ_RPC_METHODS diverged"
    registry = registry_rpc_enum()
    missing_from_registry = actual - registry
    assert (
        not missing_from_registry
    ), f"MPR2602 enum is missing real capture methods: {sorted(missing_from_registry)}"
    governance = governance_rpc_methods()
    missing_from_governance = actual - governance
    assert (
        not missing_from_governance
    ), f"governance set is missing real capture methods: {sorted(missing_from_governance)}"


def test_no_convenience_expansion():
    """Methods with no real call site must not be in the capture allowlist."""

    assert "getBlockHeight" not in READ_RPC_METHODS
    actual = actual_capture_methods()
    extra = READ_RPC_METHODS - actual
    assert not extra, f"allowlist contains methods never called: {sorted(extra)}"


def test_unlisted_method_is_rejected_before_transport():
    """The collector's pre-transport guard rejects any method outside the
    read scope before a transport object or request can exist."""
    import asyncio

    from src.market.native_cpmm_capture import (
        GovernedNativeCpmmCollector,
        NativeCaptureError,
    )

    collector = GovernedNativeCpmmCollector.__new__(GovernedNativeCpmmCollector)
    for method in ("getBlockHeight", "submitTransaction", "sendTransaction"):
        with pytest.raises(NativeCaptureError, match="outside native read scope"):
            asyncio.run(collector._rpc(method, []))


def test_sender_and_submission_methods_impossible():
    forbidden = {
        "sendTransaction",
        "submitTransaction",
        "signTransaction",
        "requestAirdrop",
    }
    assert not (READ_RPC_METHODS & forbidden)
    # The MPR2602 enum is a reviewed paper-lane schema; the binding capture
    # allowlist is READ_RPC_METHODS, and neither contains sender methods.
    assert not (actual_capture_methods() & forbidden)


def test_registry_and_profile_enums_intersect_on_capture_set():
    actual = actual_capture_methods()
    registry = registry_rpc_enum()
    assert actual <= registry
    assert actual <= READ_RPC_METHODS
    # Nothing is removed from the reviewed registry by this alignment.
    assert "getBlockHeight" in registry  # paper-lane methods untouched
    assert {"getGenesisHash", "getMultipleAccounts", "getSlot"} <= registry
