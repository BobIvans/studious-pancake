"""Per-file coverage inventory over a pinned snapshot (no silent omissions)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from .schema import (
    COVERAGE_EXCLUDED_WITH_REASON,
    COVERAGE_INDEXED,
    COVERAGE_UNCLASSIFIED,
    language_class,
)


def build_inventory(snapshot_root: str) -> list[dict[str, Any]]:
    """Build one coverage row per tracked file from a repo_snapshot manifest.

    Snapshot statuses map deterministically: EXACT -> parse-pending coverage,
    SECRET_METADATA_ONLY -> EXCLUDED_WITH_REASON (secret policy), OVERSIZED ->
    EXCLUDED_WITH_REASON, SUBMODULE/SYMLINK -> EXCLUDED_WITH_REASON. Non-code
    text/config files are covered as INDEXED (content available for packs);
    binaries and unknown kinds are UNCLASSIFIED with the reason recorded.
    """
    from ..common import load_json

    manifest = load_json(Path(snapshot_root) / "manifest.json")
    rows: list[dict[str, Any]] = []
    for entry in manifest["entries"]:
        path = entry["path"]
        status = entry["status"]
        row: dict[str, Any] = {
            "path": path,
            "git_oid": entry["git_oid"],
            "mode": entry["mode"],
            "bytes": entry.get("bytes"),
            "blob_sha256": entry.get("sha256"),
            "snapshot_status": status,
        }
        if status in {"SECRET_METADATA_ONLY", "OVERSIZED", "SUBMODULE", "SYMLINK"}:
            row["coverage"] = COVERAGE_EXCLUDED_WITH_REASON
            row["reason"] = status
        elif status == "EXACT":
            name = PurePosixPath(path).name.lower()
            if name.startswith("baseline_report_"):
                row["coverage"] = COVERAGE_EXCLUDED_WITH_REASON
                row["reason"] = "BENCHMARK_OUTPUT_ARTIFACT"
            else:
                row["coverage"] = COVERAGE_INDEXED
                row["reason"] = None
            row["language_class"] = language_class(path)
        else:
            row["coverage"] = COVERAGE_UNCLASSIFIED
            row["reason"] = f"SNAPSHOT_STATUS_{status}"
        rows.append(row)
    rows.sort(key=lambda item: item["path"])
    return rows
