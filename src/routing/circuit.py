from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from .limiter import Clock
from .models import ProviderHealth

@dataclass
class ProviderCircuit:
    clock: Clock
    failure_threshold: int = 2
    cooldown_seconds: int = 30
    failures: int = 0
    opened_at: datetime | None = None
    half_open_probe_used: bool = False
    health: ProviderHealth = ProviderHealth.READY
    def can_call(self) -> bool:
        if self.health not in (ProviderHealth.UNHEALTHY, ProviderHealth.RATE_LIMITED): return True
        if self.opened_at and (self.clock.now()-self.opened_at) >= timedelta(seconds=self.cooldown_seconds) and not self.half_open_probe_used:
            self.half_open_probe_used=True; return True
        return False
    def record_success(self):
        self.failures=0; self.opened_at=None; self.half_open_probe_used=False; self.health=ProviderHealth.READY
    def record_failure(self, health: ProviderHealth = ProviderHealth.UNHEALTHY):
        self.failures += 1
        if self.failures >= self.failure_threshold or health is ProviderHealth.RATE_LIMITED:
            self.health=health; self.opened_at=self.clock.now(); self.half_open_probe_used=False
