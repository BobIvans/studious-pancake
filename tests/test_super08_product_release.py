from __future__ import annotations

from scripts.verify_super08_product_release import verify_super08
from src.release_gate.agg15_release_handoff import (
    AGG15_SCHEMA_VERSION,
    EXPECTED_NF_COUNT,
    EXTENSION_NF_OWNERS,
    EXTENSION_SOURCE_PRS,
)
from src.research.product import RevenueAttributionLedger


def test_super08_structural_verifier_closes_352_nf_target() -> None:
    report = verify_super08()

    assert report["ok"] is True
    assert report["release_handoff_schema"] == "agg15.release-handoff.v2"
    assert report["expected_nf_count"] == 352
    assert report["extension_nf_count"] == 24
    assert report["unsafe_effects_enabled"] is False
    assert report["operational_qualification_claimed"] is False


def test_super08_extension_crosswalk_is_exact_and_nonduplicated() -> None:
    assert AGG15_SCHEMA_VERSION == "agg15.release-handoff.v2"
    assert EXPECTED_NF_COUNT == 352
    assert len(EXTENSION_NF_OWNERS) == 24
    assert len(EXTENSION_SOURCE_PRS) == 24
    assert EXTENSION_SOURCE_PRS["NF-329"] == "PR-073"
    assert EXTENSION_NF_OWNERS["NF-329"] == "TREASURY-01"
    assert EXTENSION_SOURCE_PRS["NF-352"] == "PR-078"
    assert EXTENSION_NF_OWNERS["NF-352"] == "FORMAT-02"


def test_product_attribution_never_becomes_trading_capital_authority() -> None:
    projection = RevenueAttributionLedger().export()

    assert projection["trading_capital_authority"] is False
