"""Post-merge AGG dependency reconciliation.

The master plan allowed independently mergeable default-off slices, so historical
merge order is evidence, not a reason to rewrite accepted code.  This registry
verifies that every aggregate package now has a canonical merge receipt and that
all declared package dependencies are present on the reconciliation baseline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping

SCHEMA = "agg.dependency-reconciliation.v1"
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "AGG-01": (),
    "AGG-02": ("AGG-01",),
    "AGG-03": ("AGG-01", "AGG-02"),
    "AGG-04": ("AGG-01", "AGG-02", "AGG-03"),
    "AGG-05": ("AGG-02", "AGG-04"),
    "AGG-06": ("AGG-01", "AGG-02", "AGG-04", "AGG-05"),
    "AGG-07": ("AGG-01", "AGG-02", "AGG-03", "AGG-04", "AGG-05"),
    "AGG-08": ("AGG-02", "AGG-03", "AGG-04"),
    "AGG-09": ("AGG-04", "AGG-05", "AGG-08"),
    "AGG-10": ("AGG-02", "AGG-04", "AGG-05"),
    "AGG-11": ("AGG-01", "AGG-04"),
    "AGG-12": ("AGG-07", "AGG-11"),
    "AGG-13": ("AGG-02", "AGG-04"),
    "AGG-14": ("AGG-01", "AGG-04", "AGG-09", "AGG-10"),
    "AGG-15": ("AGG-09", "AGG-14"),
}


@dataclass(frozen=True, slots=True)
class MergeReceipt:
    agg_id: str
    pr: int
    merge_commit: str
    merged_at: str
    dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DependencyAudit:
    schema: str
    reconciliation_input_main: str
    package_count: int
    all_dependencies_present: bool
    unresolved_dependencies: tuple[str, ...]
    historical_order_inversions: tuple[str, ...]
    merge_commits: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_receipts(path: str | Path) -> tuple[str, tuple[MergeReceipt, ...]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or raw.get("schema") != SCHEMA:
        raise ValueError("AGG_DEBT_SCHEMA_MISMATCH")
    base = str(raw.get("reconciliation_input_main", ""))
    if not _GIT_SHA.fullmatch(base):
        raise ValueError("AGG_DEBT_BASE_SHA_INVALID")
    packages = raw.get("packages")
    if not isinstance(packages, list):
        raise ValueError("AGG_DEBT_PACKAGES_REQUIRED")
    receipts: list[MergeReceipt] = []
    for item in packages:
        if not isinstance(item, Mapping):
            raise ValueError("AGG_DEBT_RECEIPT_OBJECT_REQUIRED")
        deps = item.get("dependencies")
        if not isinstance(deps, list) or any(not isinstance(x, str) for x in deps):
            raise ValueError("AGG_DEBT_DEPENDENCIES_INVALID")
        receipt = MergeReceipt(
            agg_id=str(item.get("agg_id", "")),
            pr=int(item.get("pr", 0)),
            merge_commit=str(item.get("merge_commit", "")),
            merged_at=str(item.get("merged_at", "")),
            dependencies=tuple(deps),
        )
        if receipt.agg_id not in EXPECTED_DEPENDENCIES:
            raise ValueError("AGG_DEBT_UNKNOWN_PACKAGE")
        if receipt.pr <= 0 or not _GIT_SHA.fullmatch(receipt.merge_commit):
            raise ValueError("AGG_DEBT_MERGE_IDENTITY_INVALID")
        datetime.fromisoformat(receipt.merged_at.replace("Z", "+00:00"))
        receipts.append(receipt)
    return base, tuple(receipts)


def audit_receipts(path: str | Path) -> DependencyAudit:
    base, receipts = load_receipts(path)
    by_id: dict[str, MergeReceipt] = {}
    for item in receipts:
        if item.agg_id in by_id:
            raise ValueError("AGG_DEBT_DUPLICATE_PACKAGE")
        by_id[item.agg_id] = item
    missing_packages = sorted(set(EXPECTED_DEPENDENCIES).difference(by_id))
    if missing_packages:
        raise ValueError("AGG_DEBT_MISSING_PACKAGES:" + ",".join(missing_packages))

    unresolved: list[str] = []
    inversions: list[str] = []
    for agg_id, expected in EXPECTED_DEPENDENCIES.items():
        receipt = by_id[agg_id]
        if receipt.dependencies != expected:
            raise ValueError(f"AGG_DEBT_DEPENDENCY_MAP_MISMATCH:{agg_id}")
        current_time = datetime.fromisoformat(receipt.merged_at.replace("Z", "+00:00"))
        for dependency in expected:
            parent = by_id.get(dependency)
            if parent is None:
                unresolved.append(f"{agg_id}:{dependency}")
                continue
            parent_time = datetime.fromisoformat(
                parent.merged_at.replace("Z", "+00:00")
            )
            if parent_time > current_time:
                inversions.append(f"{agg_id}:before:{dependency}")

    return DependencyAudit(
        schema=SCHEMA,
        reconciliation_input_main=base,
        package_count=len(by_id),
        all_dependencies_present=not unresolved,
        unresolved_dependencies=tuple(unresolved),
        historical_order_inversions=tuple(inversions),
        merge_commits=tuple(by_id[key].merge_commit for key in sorted(by_id)),
    )


__all__ = [
    "DependencyAudit",
    "EXPECTED_DEPENDENCIES",
    "MergeReceipt",
    "SCHEMA",
    "audit_receipts",
    "load_receipts",
]
