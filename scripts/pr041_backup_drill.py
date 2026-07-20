#!/usr/bin/env python3
"""Reproducible PR-041 SQLite backup/restore integrity drill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from src.durability import DurableLifecycleStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument(
        "--backup",
        type=Path,
        help="Backup path. Defaults to a sibling .backup.db file.",
    )
    args = parser.parse_args()

    backup_path = args.backup or args.database.with_suffix(".backup.db")
    restore_parent = backup_path.parent
    restore_parent.mkdir(parents=True, exist_ok=True)

    with DurableLifecycleStore(args.database) as store:
        manifest = store.backup_to(backup_path)

    with tempfile.TemporaryDirectory(
        prefix="pr041-restore-",
        dir=restore_parent,
    ) as temp_dir:
        restored_path = Path(temp_dir) / "restored.db"
        restored = DurableLifecycleStore.restore_from(
            backup_path,
            restored_path,
            expected_sha256=manifest.sha256,
        )
        try:
            restored.integrity_check()
            counts = {
                table: restored.count_rows(table)
                for table in (
                    "durable_attempts",
                    "durable_reservations",
                    "durable_events",
                    "durable_outbox",
                    "durable_leases",
                    "retention_ledger",
                )
            }
        finally:
            restored.close()

    print(
        json.dumps(
            {
                "backup": manifest.database_path,
                "created_at_ns": manifest.created_at_ns,
                "migration_version": manifest.migration_version,
                "restore_integrity": "ok",
                "row_counts": counts,
                "schema": manifest.schema,
                "sha256": manifest.sha256,
                "size_bytes": manifest.size_bytes,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
