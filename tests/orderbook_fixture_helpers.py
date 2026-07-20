from __future__ import annotations

from pathlib import Path
import struct

from src.execution.models import FlashLoanPlan, Instruction
from src.providers.orderbook import (
    OpenBookV2VenueAdapter,
    PhoenixLegacyVenueAdapter,
    VenueKind,
    VenueRegistry,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REGISTRY_PATH = ROOT / "tests" / "fixtures" / "orderbook_venues_fixture.json"


def fixture_registry() -> VenueRegistry:
    return VenueRegistry.load(FIXTURE_REGISTRY_PATH)


def fixture_blob(discriminator: bytes) -> tuple[bytes, bytes]:
    market = discriminator + struct.pack("<QQQIIHHHH", 100, 1, 1, 22, 10000, 9, 6, 2, 2)
    book = struct.pack("<QQQQQQQQ", 99, 10, 98, 20, 101, 10, 102, 30)
    return market, book


def fixture_snapshot(kind: VenueKind):
    registry = fixture_registry()
    market = (
        "PHX_FIXTURE_SOL_USDC"
        if kind is VenueKind.PHOENIX_LEGACY_SPOT
        else "OBV2_FIXTURE_SOL_USDC"
    )
    spec = registry.require_supported(kind, market)
    adapter = (
        PhoenixLegacyVenueAdapter(spec)
        if kind is VenueKind.PHOENIX_LEGACY_SPOT
        else OpenBookV2VenueAdapter(spec)
    )
    market_data, book_data = fixture_blob(spec.layout_discriminator)
    return adapter, adapter.decode_snapshot(
        market=spec.markets[0],
        owner=spec.expected_owner,
        market_data=market_data,
        book_data=book_data,
        context_slot=10,
        source_slot=10,
    )


def fixture_flash_loan_plan() -> FlashLoanPlan:
    return FlashLoanPlan(
        "margin",
        "auth",
        "group",
        Instruction("marginfi", ("margin", "auth"), b"b", "borrow", "marginfi_borrow"),
        Instruction("marginfi", ("margin", "auth"), b"r", "repay", "marginfi_repay"),
        Instruction("marginfi", (), b"e", "end", "marginfi_end"),
        ("bal",),
        ("risk",),
        10,
    )
