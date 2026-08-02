"""Role-based SQLite operational connection policy used by qualification tooling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3


class SQLiteOperationalError(RuntimeError):
    """Raised when SQLite does not honor the declared operational policy."""


@dataclass(frozen=True)
class SQLiteOperationalPolicy:
    journal_mode: str = "wal"
    synchronous: str = "full"
    busy_timeout_ms: int = 5_000
    foreign_keys: bool = True
    trusted_schema: bool = False


def connect_operational(
    path: Path,
    *,
    policy: SQLiteOperationalPolicy = SQLiteOperationalPolicy(),
) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=policy.busy_timeout_ms / 1_000)
    connection.execute(f"PRAGMA journal_mode={policy.journal_mode}")
    connection.execute(f"PRAGMA synchronous={policy.synchronous}")
    connection.execute(f"PRAGMA busy_timeout={policy.busy_timeout_ms}")
    connection.execute(f"PRAGMA foreign_keys={'ON' if policy.foreign_keys else 'OFF'}")
    connection.execute(
        f"PRAGMA trusted_schema={'ON' if policy.trusted_schema else 'OFF'}"
    )
    observed = {
        "journal_mode": str(
            connection.execute("PRAGMA journal_mode").fetchone()[0]
        ).lower(),
        "synchronous": int(connection.execute("PRAGMA synchronous").fetchone()[0]),
        "busy_timeout": int(connection.execute("PRAGMA busy_timeout").fetchone()[0]),
        "foreign_keys": int(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
        "trusted_schema": int(
            connection.execute("PRAGMA trusted_schema").fetchone()[0]
        ),
    }
    expected_sync = 2 if policy.synchronous.lower() == "full" else 1
    expected = {
        "journal_mode": policy.journal_mode.lower(),
        "synchronous": expected_sync,
        "busy_timeout": policy.busy_timeout_ms,
        "foreign_keys": int(policy.foreign_keys),
        "trusted_schema": int(policy.trusted_schema),
    }
    if observed != expected:
        connection.close()
        raise SQLiteOperationalError(
            f"SQLite policy mismatch: expected={expected!r} observed={observed!r}"
        )
    return connection
