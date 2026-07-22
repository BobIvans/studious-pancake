"""PR-193 owned lifecycle for live-control SQLite resources."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.execution.journal import SQLiteAttemptJournal
from src.execution.live_control import LiveControlStore
from src.resource_ownership_pr193 import ResourceGraph, ResourceOwnership


class ClosableLiveControlStore(LiveControlStore):
    """LiveControlStore with an idempotent WAL checkpoint/close contract."""

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        self._pr193_closed = False

    @property
    def closed(self) -> bool:
        return self._pr193_closed

    @property
    def resource_id(self) -> str:
        return f"live-control-store:{self.path}"

    def close(self) -> None:
        if self._pr193_closed:
            return
        checkpoint_error: sqlite3.Error | None = None
        try:
            if self.db.in_transaction:
                self.db.rollback()
            if self.path != ":memory:":
                self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        except sqlite3.Error as exc:
            checkpoint_error = exc
        finally:
            self.db.close()
            self._pr193_closed = True
        if checkpoint_error is not None:
            raise RuntimeError("live-control WAL checkpoint failed during close") from checkpoint_error

    def __enter__(self) -> ClosableLiveControlStore:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    async def __aenter__(self) -> ClosableLiveControlStore:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


@dataclass(slots=True)
class LiveControlResources:
    """Composition-owned store/journal pair with deterministic reverse shutdown."""

    graph: ResourceGraph
    store: ClosableLiveControlStore
    journal: SQLiteAttemptJournal

    @classmethod
    def open(
        cls,
        state_path: str | Path,
        *,
        generation: int = 1,
    ) -> LiveControlResources:
        graph = ResourceGraph(generation=generation)
        try:
            journal = graph.register(
                SQLiteAttemptJournal(state_path),
                resource_id=f"attempt-journal:{state_path}",
                kind="sqlite_attempt_journal",
                ownership=ResourceOwnership.OWNED,
            )
            store = graph.register(
                ClosableLiveControlStore(state_path),
                resource_id=f"live-control-store:{state_path}",
                kind="sqlite_live_control_store",
                ownership=ResourceOwnership.OWNED,
            )
        except Exception as startup_error:
            try:
                graph.close()
            except Exception as cleanup_error:
                raise ExceptionGroup(
                    "resource startup and cleanup failed",
                    [startup_error, cleanup_error],
                ) from startup_error
            raise
        return cls(graph=graph, store=store, journal=journal)

    @classmethod
    def compose(
        cls,
        *,
        store: ClosableLiveControlStore,
        journal: SQLiteAttemptJournal,
        store_ownership: ResourceOwnership,
        journal_ownership: ResourceOwnership,
        generation: int = 1,
    ) -> LiveControlResources:
        graph = ResourceGraph(generation=generation)
        graph.register(
            journal,
            resource_id=getattr(journal, "resource_id", f"attempt-journal:{journal.path}"),
            kind="sqlite_attempt_journal",
            ownership=journal_ownership,
        )
        graph.register(
            store,
            resource_id=store.resource_id,
            kind="sqlite_live_control_store",
            ownership=store_ownership,
        )
        return cls(graph=graph, store=store, journal=journal)

    @property
    def closed(self) -> bool:
        return self.graph.closed

    def close(self) -> None:
        self.graph.close()

    async def aclose(self) -> None:
        await self.graph.aclose()

    def __enter__(self) -> LiveControlResources:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    async def __aenter__(self) -> LiveControlResources:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.aclose()
