"""Compatibility adapter to the PR-013 canonical simulator.

This module no longer implements separate simulateTransaction semantics and never
marks paper trades as executed. Active shadow code must use src.execution.shadow.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from src.execution.shadow import CanonicalSimulator, SimulationRequest

@dataclass(frozen=True)
class SimulationResult:
    success: bool
    error: Optional[str] = None
    units_consumed: int = 0
    pre_balances: tuple[int, ...] = ()
    post_balances: tuple[int, ...] = ()
    balance_delta_lamports: int = 0
    logs: tuple[str, ...] = ()
    simulation_time_ms: int = 0

class FlashSimulator:
    def __init__(self, rpc, rpc_url: str = "replay://local", **_: object):
        self._canonical = CanonicalSimulator(rpc, rpc_url)
    async def simulate_request(self, request: SimulationRequest) -> SimulationResult:
        report = await self._canonical.simulate(request)
        delta = sum(report.post_balances) - sum(report.pre_balances) if report.post_balances and report.pre_balances else 0
        return SimulationResult(report.success, None if report.success else (report.reason.value if report.reason else str(report.err)), report.units_consumed or 0, report.pre_balances, report.post_balances, delta, report.logs)
