"""Compatibility facade for verified Solana swap providers.

PR-006 removed the generic MultiAggregatorClient implementation because Solana
providers do not share endpoints, auth, request params, response schemas, token
semantics, instruction formats, or rate limits.  New code must use
``src.ingest.swap_providers`` adapters directly.
"""
from __future__ import annotations

from src.ingest.swap_providers import (
    JupiterSwapV2Adapter,
    OKXSolanaAdapter,
    OpenOceanSolanaAdapter,
    ZeroXSolanaAdapter,
    active_solana_providers,
    execution_shortlist,
    select_after_simulation,
)

class MultiAggregatorClient:
    """Deprecated shim that exposes the verified active Solana provider registry."""
    def __init__(self):
        self.providers = active_solana_providers()

    def get_stats(self):
        return {"providers": [p.name for p in self.providers], "odos_active": False}
