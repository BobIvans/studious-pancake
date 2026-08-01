from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.durability.lifecycle import DurableLifecycleStore, UnsupportedTopologyError


def test_database_permissions_pragmas_and_fingerprint(tmp_path: Path) -> None:
    state = tmp_path / "private-state"
    with DurableLifecycleStore(state / "authority.sqlite3") as store:
        first = store.schema_fingerprint()
        second = store.schema_fingerprint()
        assert first == second
        assert len(first) == 64
        assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert store.db.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.db.execute("PRAGMA trusted_schema").fetchone()[0] == 0

    assert state.stat().st_mode & 0o777 == 0o700
    assert (state / "authority.sqlite3").stat().st_mode & 0o777 == 0o600


def test_symlink_database_path_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.sqlite3"
    target.touch(mode=0o600)
    alias = tmp_path / "authority.sqlite3"
    alias.symlink_to(target)
    with pytest.raises(UnsupportedTopologyError, match="symlink"):
        DurableLifecycleStore(alias)


def test_hardlink_database_path_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.sqlite3"
    target.touch(mode=0o600)
    alias = tmp_path / "authority.sqlite3"
    os.link(target, alias)
    with pytest.raises(UnsupportedTopologyError, match="hard-linked"):
        DurableLifecycleStore(alias)


def test_existing_database_in_writable_parent_is_rejected(tmp_path: Path) -> None:
    state = tmp_path / "unsafe-state"
    state.mkdir(mode=0o700)
    database = state / "authority.sqlite3"
    database.touch(mode=0o600)
    state.chmod(0o770)

    with pytest.raises(UnsupportedTopologyError, match="group/world writable"):
        DurableLifecycleStore(database)


def test_sqlite_sidecars_are_owner_only(tmp_path: Path) -> None:
    database = tmp_path / "private-state" / "authority.sqlite3"
    with DurableLifecycleStore(database):
        sidecars = [Path(f"{database}{suffix}") for suffix in ("-wal", "-shm")]
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in sidecars)


def test_restore_validates_staged_copy_without_destroying_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    destination = tmp_path / "destination.sqlite3"
    destination.write_bytes(b"previous-generation")
    with DurableLifecycleStore(source) as store:
        manifest = store.backup_to(backup)

    damaged = tmp_path / "damaged.sqlite3"
    damaged.write_bytes(backup.read_bytes()[:100])
    with pytest.raises(Exception):
        DurableLifecycleStore.restore_from(damaged, destination)
    assert destination.read_bytes() == b"previous-generation"

    restored = DurableLifecycleStore.restore_from(
        backup, destination, expected_sha256=manifest.sha256
    )
    restored.close()
    assert destination.stat().st_mode & 0o777 == 0o600
