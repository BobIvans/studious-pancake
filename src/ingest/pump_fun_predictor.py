"""Disabled compatibility shell for removed Pump.fun legacy heuristics."""
from __future__ import annotations

PUMP_LEGACY_HEURISTIC_DISABLED = "PUMP_LEGACY_HEURISTIC_DISABLED"


class PumpLegacyHeuristicDisabled(RuntimeError):
    pass


class PumpFunBondingCurve:
    def __init__(self, address: str):
        self.address = address

    def parse_state(self, account_data_b64: str) -> bool:
        raise PumpLegacyHeuristicDisabled(PUMP_LEGACY_HEURISTIC_DISABLED)


class RaydiumPDAPrecomputer:
    @classmethod
    def precompute_pool_addresses(cls, token_mint: str) -> dict[str, str]:
        raise PumpLegacyHeuristicDisabled(PUMP_LEGACY_HEURISTIC_DISABLED)


class PumpFunMigrationPredictor:
    def __init__(self, *args, **kwargs):
        self.curves = {}

    async def start_monitoring(self, curve_addresses: list[str]):
        raise PumpLegacyHeuristicDisabled(PUMP_LEGACY_HEURISTIC_DISABLED)

    def get_migration_status(self) -> dict[str, object]:
        raise PumpLegacyHeuristicDisabled(PUMP_LEGACY_HEURISTIC_DISABLED)
