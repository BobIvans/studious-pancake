"""Disabled legacy BankHealthMonitor compatibility stub.

PR-019 forbids risk-critical liquidity defaults based on float UI amounts or RPC
failure-as-zero. Production candidate discovery must use src.lending_indexer.
"""
from __future__ import annotations

class BankHealthMonitor:
    disabled_reason = "DISABLED_UNVERIFIED_CONTRACT: legacy float/RPC-fallback monitor retired from candidate path"
    def __init__(self, *args, **kwargs):
        raise RuntimeError(self.disabled_reason)
