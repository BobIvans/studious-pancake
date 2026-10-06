import sqlite3

import pytest

from src.durability import lifecycle


class BootstrapClock:
    def __init__(self):
        self.elapsed = 0.0
        self.delays = []

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.delays.append(seconds)
        self.elapsed += seconds


def inject_wal_error(monkeypatch, code, failures):
    execute = lifecycle._SerializedConnection.execute
    observed = {"calls": 0, "connection": None}

    def failing_execute(connection, query, *args, **kwargs):
        if query == "PRAGMA journal_mode=WAL":
            observed["connection"] = connection
            observed["calls"] += 1
            if failures is None or observed["calls"] <= failures:
                error = sqlite3.OperationalError("injected WAL bootstrap failure")
                error.sqlite_errorcode = code
                raise error
        return execute(connection, query, *args, **kwargs)

    monkeypatch.setattr(lifecycle._SerializedConnection, "execute", failing_execute)
    return observed


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_BUSY_RECOVERY])
def test_early_busy_wal_upgrade_retries_and_restores_timeout(
    tmp_path, monkeypatch, code
):
    clock = BootstrapClock()
    monkeypatch.setattr(lifecycle, "time", clock)
    observed = inject_wal_error(monkeypatch, code, 2)
    store = lifecycle.DurableLifecycleStore(tmp_path / "retry.db", busy_timeout_ms=100)
    try:
        assert observed["calls"] == 3
        assert clock.elapsed == pytest.approx(0.02)
        assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert store.db.execute("PRAGMA busy_timeout").fetchone()[0] == 100
        store.integrity_check()
    finally:
        store.close()


def test_wal_busy_timeout_remains_bounded_and_closes_connection(tmp_path, monkeypatch):
    clock = BootstrapClock()
    monkeypatch.setattr(lifecycle, "time", clock)
    observed = inject_wal_error(monkeypatch, sqlite3.SQLITE_BUSY, None)
    with pytest.raises(sqlite3.OperationalError):
        lifecycle.DurableLifecycleStore(tmp_path / "timeout.db", busy_timeout_ms=25)
    assert clock.elapsed == pytest.approx(0.025)
    assert observed["calls"] == 4
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        observed["connection"].execute("SELECT 1")


def test_non_busy_wal_error_is_not_retried(tmp_path, monkeypatch):
    clock = BootstrapClock()
    monkeypatch.setattr(lifecycle, "time", clock)
    observed = inject_wal_error(monkeypatch, sqlite3.SQLITE_READONLY, None)
    with pytest.raises(sqlite3.OperationalError):
        lifecycle.DurableLifecycleStore(tmp_path / "readonly.db", busy_timeout_ms=100)
    assert observed["calls"] == 1
    assert clock.delays == []
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        observed["connection"].execute("SELECT 1")
