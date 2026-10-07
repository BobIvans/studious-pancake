"""Consistent SQLite backup to a new copy, never overwrite an existing index."""

from pathlib import Path
import sqlite3
from .common import file_hash


def verify_backup(path: str | Path, expected_sha256: str | None = None) -> dict:
    path = Path(path)
    if expected_sha256 is not None and file_hash(path) != expected_sha256:
        raise ValueError("backup checksum mismatch")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("index integrity failure")
    return {"sha256": file_hash(path), "integrity": "ok", "bytes": path.stat().st_size}


def backup_index(source: str | Path, destination: str | Path) -> dict:
    out = Path(destination)
    if out.exists():
        raise ValueError("backup destination exists")
    out.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(out) as dst:
            src.backup(dst)
    return verify_backup(out)


def restore_to_copy(
    backup: str | Path, destination: str | Path, *, expected_sha256: str
) -> dict:
    verify_backup(backup, expected_sha256)
    return backup_index(backup, destination)
