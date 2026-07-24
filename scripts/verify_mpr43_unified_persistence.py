#!/usr/bin/env python3
"""Verify the MPR-43 unified persistence foundation.

This verifier creates an isolated SQLite authority, applies migrations, performs
one fenced atomic inbox/outbox/audit transaction, writes an integer-only ledger
entry, closes the generation, creates a backup and validates restore integrity.
It is intentionally network-free and live-disabled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.durability.mpr43_unified_persistence import (  # noqa: E402
    AuditEvent,
    GenerationFence,
    InboxEvent,
    LedgerEntry,
    OutboxEvent,
    SCHEMA_VERSION,
    UnifiedPersistenceAuthority,
    validate_restore,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    owned_temp = None
    if args.work_dir is None:
        owned_temp = tempfile.TemporaryDirectory()
        work_dir = Path(owned_temp.name)
    else:
        work_dir = Path(args.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    authority = UnifiedPersistenceAuthority(work_dir / "mpr43.sqlite3")
    fence = GenerationFence("verify-generation", "verify-lease")
    digest = hashlib.sha256(b"mpr43-verifier-evidence").hexdigest()

    authority.start_generation(fence)
    authority.append_audit_event(
        fence,
        AuditEvent(
            "verify-audit-start",
            fence.generation_id,
            "verification-start",
            {"schema_version": SCHEMA_VERSION},
        ),
    )
    authority.record_inbox_outbox_atomic(
        fence,
        inbox=InboxEvent(
            "verify-inbox-1",
            "verifier",
            {"kind": "provider-event", "slot": 1},
            1,
        ),
        outbox=OutboxEvent(
            "verify-outbox-1",
            "projection",
            {"from": "verify-inbox-1"},
        ),
        audit_event_id="verify-audit-inbox-outbox",
    )
    authority.append_ledger_entry(
        fence,
        LedgerEntry(
            "verify-ledger-1",
            "verify-attempt-1",
            "SOL",
            -1,
            "verification-reservation",
            digest,
        ),
    )
    fingerprint = authority.schema_fingerprint()
    authority.close_generation(fence)
    manifest = authority.create_backup(work_dir / "mpr43-backup.sqlite3")
    restore = validate_restore(
        work_dir / "mpr43-backup.sqlite3",
        expected_schema_fingerprint=fingerprint,
    )

    report = {
        "schema_version": SCHEMA_VERSION,
        "accepted": restore.accepted,
        "schema_fingerprint": fingerprint,
        "backup_sha256": manifest.backup_sha256,
        "restore": restore.to_dict(),
        "live_trading_enabled": False,
        "signer_enabled": False,
        "jito_enabled": False,
    }
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "MPR43_PERSISTENCE_VERIFY:"
            f" accepted={report['accepted']}"
            f" schema={fingerprint}"
            f" backup={manifest.backup_sha256}"
        )
    if owned_temp is not None:
        owned_temp.cleanup()
    return 0 if restore.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
