"""Typed provider adapters for the R13 multi-provider quote/build race.

This package hosts NEW per-provider quote adapters that normalize provider
responses into the FROZEN kernel contract
(``src.execution.quote_build_kernel.NormalizedProviderQuote``). Adapters here
are sender-free, fail-closed and DISABLED by default: no network transport is
shipped, live capture is refused with a typed ``*_LIVE_CAPTURE_NOT_AUTHORIZED``
gate until a human operator authorizes it, and nothing in this package edits
the existing P0-2 quote owners (``probes.py`` / ``funnel.py``).

Current adapters:

- :mod:`.titan` — Titan (Solana swap meta-aggregator) quote adapter,
  ``ADAPTER_BUILT_OFFLINE_UNQUALIFIED``.
"""
