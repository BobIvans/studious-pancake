from __future__ import annotations

from scripts.verify_mpr_td_03_capacity_storage import build_evidence


def test_capacity_storage_smoke_uses_real_sqlite() -> None:
    evidence = build_evidence()
    assert evidence["accepted"] is True, evidence["errors"]
    assert evidence["indexed_plan"] is True
    assert evidence["backup_integrity"] == "ok"
    assert evidence["restored_rows"] == evidence["rows"]
    assert evidence["production_capacity_qualified"] is False
