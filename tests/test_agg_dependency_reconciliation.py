from __future__ import annotations

from src.release_gate.agg_debt_closure import (
    EXPECTED_DEPENDENCIES,
    audit_receipts,
)


def test_all_15_agg_packages_have_current_dependency_receipts() -> None:
    audit = audit_receipts("config/agg_merge_receipts.json")
    assert audit.package_count == 15
    assert audit.all_dependencies_present is True
    assert audit.unresolved_dependencies == ()
    assert len(audit.merge_commits) == 15


def test_historical_order_inversions_are_recorded_not_hidden() -> None:
    audit = audit_receipts("config/agg_merge_receipts.json")
    assert "AGG-02:before:AGG-01" in audit.historical_order_inversions
    assert "AGG-03:before:AGG-01" in audit.historical_order_inversions
    assert "AGG-03:before:AGG-02" in audit.historical_order_inversions
    assert "AGG-09:before:AGG-05" in audit.historical_order_inversions
    assert "AGG-09:before:AGG-08" in audit.historical_order_inversions
    assert "AGG-15:before:AGG-09" not in audit.historical_order_inversions
    assert set(EXPECTED_DEPENDENCIES) == {
        f"AGG-{index:02d}" for index in range(1, 16)
    }
