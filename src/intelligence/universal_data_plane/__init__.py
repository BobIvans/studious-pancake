"""Unified read-only data plane (OCA-W11).

A bounded, stable-ID, cross-store query facade over the single OCA-W0B/W4
retrieval backend plus the canonical owners' existing read surfaces. This is
never a second canonical store: every payload resolves through its canonical
owner, and unknown/unavailable dimensions are reported as such.

Read-only by construction: no signing, sending, borrowing, spending,
deployment, provider enablement, shell, file mutation, or admin capability is
reachable from this package.
"""

from __future__ import annotations

SCHEMA_ID = "studious.universal-data-plane.v1"

# Canonical stores the facade can resolve IDs against, with their read status.
# Runtime observation remains UNAVAILABLE until OCA-W10 wires real producers
# (OCA-W0 trace, PR #680): no producer callsites exist on any audited main.
STORES: dict[str, dict[str, str]] = {
    "repo_graph": {
        "owner": "src/intelligence/repo_graph (derived read-only view)",
        "status": "AVAILABLE",
    },
    "observability": {
        "owner": "src/observability/store.py (ObservabilityStore)",
        "status": "READ_READY_NO_PRODUCERS",
    },
    "market_observation": {
        "owner": "src/market/observations.py (MarketObservationV2)",
        "status": "AVAILABLE",
    },
    "agg02": {
        "owner": "src/agg02/storage.py (DurableRawJournal)",
        "status": "AVAILABLE",
    },
    "flash_capital": {
        "owner": "src/economics/flash_capital_graph/graph.py (FlashCapitalGraph)",
        "status": "AVAILABLE",
    },
}
