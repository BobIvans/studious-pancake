from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

class Clock:
    def now(self) -> datetime: return datetime.now(timezone.utc)

class FakeClock(Clock):
    def __init__(self, start: datetime): self._now=start
    def now(self): return self._now
    def advance(self, seconds: float): self._now += timedelta(seconds=seconds)

@dataclass
class FixedWindowLimiter:
    max_calls: int
    window_seconds: float
    clock: Clock
    _window_start: datetime | None = None
    _calls: int = 0
    def allow(self) -> bool:
        now = self.clock.now()
        if self._window_start is None or (now-self._window_start).total_seconds() >= self.window_seconds:
            self._window_start=now; self._calls=0
        if self._calls >= self.max_calls: return False
        self._calls += 1; return True
