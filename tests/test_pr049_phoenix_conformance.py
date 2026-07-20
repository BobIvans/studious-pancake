from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.providers.orderbook import (
    OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID,
    OFFICIAL_PHOENIX_VERIFY_COMMAND,
    OrderbookReject,
    OrderbookRejectCode,
    VenueKind,
    VenueRegistry,
)
from src.providers.orderbook.conformance import ensure_pr049_default_conformance

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "docs" / "registry" / "orderbook_venues.json"


def test_default_registry_pins_official_phoenix_and_is_fail_closed() -> None:
    registry = VenueRegistry.load(DEFAULT_REGISTRY)
    phoenix = registry.specs[VenueKind.PHOENIX_LEGACY_SPOT]

    assert phoenix.program_id == OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID
    assert phoenix.expected_owner == OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID
    assert phoenix.enabled_shadow is False
    assert phoenix.enabled_live is False
    assert phoenix.markets == ()
    assert "solana-verify verify-from-repo" in OFFICIAL_PHOENIX_VERIFY_COMMAND
    assert OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID in OFFICIAL_PHOENIX_VERIFY_COMMAND
    with pytest.raises(OrderbookReject) as exc:
        registry.require_supported(VenueKind.PHOENIX_LEGACY_SPOT, "PHX_FIXTURE_SOL_USDC")
    assert exc.value.code is OrderbookRejectCode.MARKET_UNSUPPORTED


def test_default_registry_contains_no_synthetic_orderbook_ids_or_magic_bytes() -> None:
    registry_text = DEFAULT_REGISTRY.read_text(encoding="utf-8")
    adapter_text = (ROOT / "src" / "providers" / "orderbook" / "adapters.py").read_text(
        encoding="utf-8"
    )

    forbidden = (
        "PhoenixLegacyProgramFromPinnedRegistry111111",
        "OpenBookV2ProgramFromPinnedIDL1111111111111",
        "PHXLEG16",
        "OBV2LEG!",
    )
    for marker in forbidden:
        assert marker not in registry_text
        assert marker not in adapter_text


def test_pr049_conformance_rejects_fake_default_phoenix_program(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    raw["venues"][0]["program_id"] = "PhoenixLegacyProgramFromPinnedRegistry111111"
    raw["venues"][0]["expected_owner"] = "PhoenixLegacyProgramFromPinnedRegistry111111"
    bad_registry = tmp_path / "bad_orderbook_venues.json"
    bad_registry.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(OrderbookReject) as exc:
        specs = tuple(VenueRegistry.load(bad_registry).specs.values())
        ensure_pr049_default_conformance(specs)
    assert exc.value.code is OrderbookRejectCode.VENUE_PROGRAM_MISMATCH


def test_openbook_v2_is_not_in_default_pr049_scope() -> None:
    registry = VenueRegistry.load(DEFAULT_REGISTRY)

    assert VenueKind.OPENBOOK_V2 not in registry.specs
    with pytest.raises(OrderbookReject) as exc:
        registry.require_supported(VenueKind.OPENBOOK_V2, "OBV2_FIXTURE_SOL_USDC")
    assert exc.value.code is OrderbookRejectCode.UNKNOWN_VENUE_OR_POOL
