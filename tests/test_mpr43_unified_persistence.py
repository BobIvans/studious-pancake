from __future__ import annotations

import hashlib
import sqlite3

import pytest

from src.durability.mpr43_unified_persistence import (
    AuditEvent,
    GenerationFence,
    InboxEvent,
    LedgerEntry,
    Mpr43PersistenceError,
    OutboxEvent,
    UnifiedPersistenceAuthority,
    scan_unapproved_sqlite_connects,
    validate_restore,
)

DIGEST = hashlib.sha256(b"evidence").hexdigest()


def _authority(tmp_path):
    return UnifiedPersistenceAuthority(tmp_path / "mpr43.sqlite3")


def _fence() -> GenerationFence:
    return GenerationFence("generation-1", "lease-1")


def test_mpr43_schema_fingerprint_is_stable_and_pragmas_enabled(tmp_path):
    authority = _authority(tmp_path)
    authority.initialize()

    first = authority.schema_fingerprint()
    second = authority.schema_fingerprint()

    assert first == second
    assert len(first) == 64
    assert authority.count_rows("mpr43_migration") == 5


def test_migration_checksum_mismatch_fails_closed(tmp_path):
    authority = _authority(tmp_path)
    authority.initialize()

    with sqlite3.connect(authority.path) as con:
        con.execute(
            "UPDATE mpr43_migration SET checksum = ? WHERE version = 1",
            ("a" * 64,),
        )

    with pytest.raises(Mpr43PersistenceError, match="MIGRATION_CHECKSUM_MISMATCH"):
        authority.initialize()


def test_generation_fencing_rejects_stale_writer(tmp_path):
    authority = _authority(tmp_path)
    fence = _fence()
    authority.start_generation(fence)

    stale = GenerationFence("generation-1", "lease-stale")
    with pytest.raises(Mpr43PersistenceError, match="STALE_OR_INACTIVE_WRITER"):
        authority.append_audit_event(
            stale,
            AuditEvent("audit-1", "generation-1", "startup", {"ok": True}),
        )

    authority.append_audit_event(
        fence,
        AuditEvent("audit-1", "generation-1", "startup", {"ok": True}),
    )
    assert authority.count_rows("mpr43_audit_event") == 1


def test_append_only_audit_rejects_replacement(tmp_path):
    authority = _authority(tmp_path)
    fence = _fence()
    authority.start_generation(fence)

    event = AuditEvent("audit-1", "generation-1", "startup", {"ok": True})
    authority.append_audit_event(fence, event)

    with pytest.raises(sqlite3.IntegrityError):
        authority.append_audit_event(fence, event)

    assert authority.count_rows("mpr43_audit_event") == 1


def test_inbox_outbox_and_audit_commit_atomically(tmp_path):
    authority = _authority(tmp_path)
    fence = _fence()
    authority.start_generation(fence)

    authority.record_inbox_outbox_atomic(
        fence,
        inbox=InboxEvent("inbox-1", "helius", {"signature": "sig-1"}, 1),
        outbox=OutboxEvent("outbox-1", "project-event", {"inbox": "inbox-1"}),
        audit_event_id="audit-1",
    )

    with pytest.raises(sqlite3.IntegrityError):
        authority.record_inbox_outbox_atomic(
            fence,
            inbox=InboxEvent("inbox-1", "helius", {"signature": "sig-1"}, 1),
            outbox=OutboxEvent("outbox-2", "project-event", {"inbox": "inbox-1"}),
            audit_event_id="audit-2",
        )

    assert authority.count_rows("mpr43_inbox_event") == 1
    assert authority.count_rows("mpr43_outbox_event") == 1
    assert authority.count_rows("mpr43_audit_event") == 1


@pytest.mark.parametrize("value", [1.25, float("nan"), True])
def test_ledger_rejects_float_nan_and_bool_money(tmp_path, value):
    with pytest.raises(Mpr43PersistenceError):
        LedgerEntry(
            "ledger-1",
            "attempt-1",
            "SOL",
            value,
            "reservation",
            DIGEST,
        )


def test_integer_ledger_entry_is_append_only_and_fenced(tmp_path):
    authority = _authority(tmp_path)
    fence = _fence()
    authority.start_generation(fence)

    authority.append_ledger_entry(
        fence,
        LedgerEntry("ledger-1", "attempt-1", "SOL", -5000, "reserve", DIGEST),
    )

    with pytest.raises(sqlite3.IntegrityError):
        authority.append_ledger_entry(
            fence,
            LedgerEntry("ledger-1", "attempt-1", "SOL", -5000, "reserve", DIGEST),
        )

    assert authority.count_rows("mpr43_economic_ledger") == 1


def test_backup_restore_validation_preserves_schema_and_rejects_active_writer(tmp_path):
    authority = _authority(tmp_path)
    fence = _fence()
    authority.start_generation(fence)
    authority.append_audit_event(
        fence,
        AuditEvent("audit-1", "generation-1", "startup", {"ok": True}),
    )

    active_backup = tmp_path / "active-backup.sqlite3"
    with authority._connect() as source, sqlite3.connect(str(active_backup)) as target:
        source.backup(target)

    active_report = validate_restore(
        active_backup,
        expected_schema_fingerprint=authority.schema_fingerprint(),
    )
    assert active_report.accepted is False
    assert "RESTORE_HAS_ACTIVE_WRITER_GENERATION" in active_report.blockers

    authority.close_generation(fence)
    backup = tmp_path / "clean-backup.sqlite3"
    manifest = authority.create_backup(backup)

    report = validate_restore(
        backup,
        expected_schema_fingerprint=manifest.source_schema_fingerprint,
    )
    assert report.accepted is True
    assert report.integrity_check == "ok"
    assert manifest.source_schema_fingerprint == manifest.backup_schema_fingerprint
    assert len(manifest.backup_sha256) == 64


def test_direct_sqlite_connect_scanner_is_allowlist_based(tmp_path):
    root = tmp_path / "repo"
    allowed_dir = root / "src" / "durability"
    blocked_dir = root / "src" / "feature"
    allowed_dir.mkdir(parents=True)
    blocked_dir.mkdir(parents=True)
    (allowed_dir / "authority.py").write_text("sqlite3.connect('ok.db')\n")
    (blocked_dir / "bad.py").write_text("import sqlite3\nsqlite3.connect('bad.db')\n")
    (blocked_dir / "also_bad.py").write_text("import aiosqlite\naiosqlite.connect('bad.db')\n")

    findings = scan_unapproved_sqlite_connects(
        root,
        allowed_paths=("src/durability/authority.py",),
    )

    assert [finding.path for finding in findings] == [
        "src/feature/also_bad.py",
        "src/feature/bad.py",
    ]
    assert all(finding.line > 0 for finding in findings)
