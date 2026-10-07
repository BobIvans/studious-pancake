"""Measured disk budgets, pressure and forecasts; missing rates stay unknown."""

from pathlib import Path
import shutil
import sqlite3

GB = 1_000_000_000


def compute_dynamic_budget(
    total_bytes: int, free_bytes: int, *, configured_bytes: int | None = None
) -> dict:
    if not 0 <= free_bytes <= total_bytes:
        raise ValueError("invalid disk measurement")
    reserve = max(30 * GB, total_bytes // 4)
    spare = max(0, free_bytes - reserve)
    budget = min(30 * GB, max(8 * GB, spare // 2)) if spare >= 16 * GB else spare // 2
    if configured_bytes is not None:
        if configured_bytes < 0 or configured_bytes > spare // 2:
            raise ValueError("configured budget exceeds safe spare disk")
        budget = configured_bytes
    return {
        "total_disk_bytes": total_bytes,
        "free_disk_bytes": free_bytes,
        "reserve_bytes": reserve,
        "spare_bytes": spare,
        "intelligence_budget_bytes": budget,
        "storage_pressure_state": "STORAGE_PRESSURE" if budget < 8 * GB else "NORMAL",
    }


def storage_pressure_state(used_bytes: int, budget_bytes: int) -> str:
    if min(used_bytes, budget_bytes) < 0:
        raise ValueError("negative storage")
    return "STORAGE_PRESSURE" if used_bytes >= budget_bytes * 9 // 10 else "NORMAL"


def forecast_days_until_budget(
    used_bytes: int,
    budget_bytes: int,
    bytes_written: int | None,
    elapsed_seconds: int | None,
) -> dict:
    if min(used_bytes, budget_bytes) < 0:
        raise ValueError("negative storage")
    if bytes_written is None or elapsed_seconds is None:
        return {
            "projected_bytes_per_day": None,
            "projected_days_until_budget": None,
            "measurement_status": "NOT_OBSERVED",
        }
    if bytes_written < 0 or elapsed_seconds <= 0:
        raise ValueError("invalid write-rate measurement")
    daily = bytes_written * 86400 / elapsed_seconds
    return {
        "projected_bytes_per_day": daily,
        "projected_days_until_budget": (
            max(0, budget_bytes - used_bytes) / daily if daily else None
        ),
        "measurement_status": "MEASURED" if daily else "NO_GROWTH_OBSERVED",
    }


def read_disk_budget(root: str | Path, *, journal: str | Path | None = None) -> dict:
    root = Path(root)
    usage = shutil.disk_usage(root)
    result = compute_dynamic_budget(usage.total, usage.free)
    files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    result.update(
        {
            "measured_files_bytes": sum(p.stat().st_size for p in files),
            "parquet_bytes": sum(
                p.stat().st_size for p in files if p.suffix == ".parquet"
            ),
            "raw_events_seen": None,
            "raw_bytes_seen": None,
            "raw_events_retained": None,
            "raw_bytes_retained": None,
            "normalized_rows": None,
            "episode_count": None,
            "pinned_bytes": None,
            "rollup_rows": None,
            "bytes_written_last_hour": None,
            "compression_ratio_ppm": None,
            "dedupe_ratio_ppm": None,
            "retention_ratio_ppm": None,
            "measurement_status": "NOT_OBSERVED",
        }
    )
    if journal is not None:
        with sqlite3.connect(
            Path(journal).resolve().as_uri() + "?mode=ro", uri=True
        ) as db:
            count, size = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(LENGTH(payload)),0) FROM raw_events"
            ).fetchone()
            result.update(
                raw_events_retained=count,
                raw_bytes_retained=size,
                measurement_status="MEASURED_CURRENT_JOURNAL",
            )
            tables = {
                r[0]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "raw_payload_archives" in tables:
                archived_count, archived_bytes = db.execute(
                    "SELECT COUNT(*),COALESCE(SUM(original_bytes),0) FROM raw_payload_archives"
                ).fetchone()
                result.update(
                    raw_events_seen=count,
                    raw_bytes_seen=size + archived_bytes,
                    raw_events_retained=count - archived_count,
                    retention_ratio_ppm=(
                        size * 1_000_000 // (size + archived_bytes)
                        if size + archived_bytes
                        else None
                    ),
                )
            if "raw_retention_pins" in tables:
                result["pinned_bytes"] = db.execute(
                    "SELECT COALESCE(SUM(LENGTH(payload)),0) FROM raw_events WHERE event_id IN "
                    "(SELECT event_id FROM raw_retention_pins)"
                ).fetchone()[0]
    return result
