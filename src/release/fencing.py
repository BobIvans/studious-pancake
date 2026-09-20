"""Durable release-generation fencing over an injected SQLite connection."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3


class GenerationFenceError(RuntimeError):
    """Generation authority could not be established or verified."""


class StaleGenerationError(GenerationFenceError):
    """A worker belongs to a generation that no longer has write authority."""


@dataclass(frozen=True, slots=True)
class GenerationFence:
    generation_id: str
    epoch: int


class GenerationFenceStore:
    """Single-row durable generation authority.

    The connection is injected so this module does not create a competing
    SQLite connection authority.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS release_generation_authority(
              singleton INTEGER PRIMARY KEY CHECK(singleton=1),
              generation_id TEXT NOT NULL,
              epoch INTEGER NOT NULL CHECK(epoch>=1)
            )
            """
        )

    def active(self) -> GenerationFence | None:
        row = self._db.execute(
            "SELECT generation_id,epoch "
            "FROM release_generation_authority WHERE singleton=1"
        ).fetchone()
        if row is None:
            return None
        return GenerationFence(str(row[0]), int(row[1]))

    def activate(
        self,
        generation_id: str,
        *,
        expected_epoch: int | None = None,
    ) -> GenerationFence:
        if not generation_id or len(generation_id) > 128:
            raise GenerationFenceError("generation_id must be non-empty and bounded")
        with self._db:
            current = self.active()
            if expected_epoch is not None:
                current_epoch = current.epoch if current is not None else 0
                if current_epoch != expected_epoch:
                    raise GenerationFenceError("generation epoch changed")
            epoch = 1 if current is None else current.epoch + 1
            self._db.execute(
                """
                INSERT INTO release_generation_authority(singleton,generation_id,epoch)
                VALUES(1,?,?)
                ON CONFLICT(singleton) DO UPDATE SET
                  generation_id=excluded.generation_id,
                  epoch=excluded.epoch
                """,
                (generation_id, epoch),
            )
        return GenerationFence(generation_id, epoch)

    def assert_authorized(self, fence: GenerationFence) -> None:
        active = self.active()
        if active is None:
            raise StaleGenerationError("no release generation is active")
        if active != fence:
            raise StaleGenerationError("worker generation is stale")
