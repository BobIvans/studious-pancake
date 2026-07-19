"""Disabled legacy liquidation scanner compatibility stub.

PR-019 retires guessed account offsets, jsonParsed protocol inputs, hard-coded
bonuses, and callable liquidation execution from production paths. Use the
read-only src.lending_indexer package for auditable candidate observations.
"""
from __future__ import annotations

class LiquidationEngine:
    disabled_reason = "DISABLED_UNVERIFIED_CONTRACT: legacy execution-capable liquidation engine retired"
    def __init__(self, *args, **kwargs):
        raise RuntimeError(self.disabled_reason)

class LiquidationOpportunity:
    disabled_reason = LiquidationEngine.disabled_reason
