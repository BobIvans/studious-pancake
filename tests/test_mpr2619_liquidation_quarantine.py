from __future__ import annotations

import src.liquidation as liquidation


def test_mpr2619_existing_liquidation_package_remains_fixture_only_quarantined() -> None:
    assert liquidation.__runtime_capability__ == "fixture-only"
    assert liquidation.__quarantined__ is True
