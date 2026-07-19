from __future__ import annotations
import asyncio
from .models import ExecutionJournalEntry

class InMemoryExecutionJournal:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._entries: dict[tuple[str, str], ExecutionJournalEntry] = {}

    async def reserve_submission(self, opportunity_id: str, message_hash: str, *, attempt_number: int = 1) -> bool:
        async with self._lock:
            key = (opportunity_id, message_hash)
            if key in self._entries and self._entries[key].submitted:
                return False
            self._entries[key] = ExecutionJournalEntry(opportunity_id, attempt_number, message_hash, submitted=True)
            return True

    def get(self, opportunity_id: str, message_hash: str) -> ExecutionJournalEntry | None:
        return self._entries.get((opportunity_id, message_hash))
