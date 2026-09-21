# AGG-06 — Solana venue and arbitrage-family expansion

Status: **IMPLEMENTED_OFFLINE / operationally UNQUALIFIED / live disabled**.

This change implements the sender-free AGG-06 conformance/strategy seam for the 15 primary NF requirements. It extends existing repository owners instead of creating a second runtime, market graph, capital/quota authority, compiler, signer, sender, or live OMS.

## Scope

Work packages represented here:

- VENUE-02 — Raydium CLMM decoded tick-array traversal and account closure;
- VENUE-03 — Orca Whirlpool reuse remains license-gated; no Orca source is copied;
- BOOK-01/02 — Phoenix/OpenBook exact integer-lot quoting through the existing orderbook owner, with explicit account/settlement gates;
- BOOK-03 — conservative CLOB↔AMM atomic strategy admission;
- LST-01 — immediate-exit capacity layered on the accepted MPR-2621 LST authority;
- DYNAMIC-01 — DLMM dynamic-fee, Token-2022, and time-fee research signals;
- DYNAMIC-02 — DAMM/DBC/Pump lifecycle, migration, and post-swap residual state.

Primary coverage is exactly `NF-070, NF-073, NF-117, NF-119, NF-120, NF-121, NF-122, NF-138, NF-139, NF-140, NF-141, NF-142, NF-143, NF-151, NF-153`.

## Existing owners reused

`src/agg06_solana_venues.py` directly reuses:

- `src.providers.orderbook.quote.OrderbookQuoteEngine` for exact integer-lot CLOB quotes;
- `src.mpr2621_lst_atomic_exit` for LST NAV/immediate-exit qualification;
- `src.strategies.stable_peg.math` for integer decoded CLMM/DLMM band traversal.

It preserves the fail-closed direct-venue policy already established by MPR-2617: exact family/deployment evidence, no wildcard promotion, and Orca reuse blocked until the exact artifact/license decision is approved.

## Fail-closed behavior

- Missing CLMM tick arrays reject instead of falling back to CPMM/linear math.
- Orca cannot reach verified reuse without an approved license decision for the exact evidence generation.
- CLMM/CLOB verification needs an amount-bound independent reference result.
- CLOB account readiness and settlement are explicit; residual input is not profit.
- Delayed/queued LST exit is not same-transaction repayment liquidity.
- Unknown Token-2022 hooks and default-frozen behavior fail closed.
- Dynamic-fee evidence expires on its own clock; a time-fee signal never authorizes holding flash liquidity across a wait.
- Migration requires finalized generation change with only the new state trading.
- Post-large-swap residual evidence binds to complete post-event state.

## Operational truth

The branch was historically cut from `main@693afe31c4cb5d2aa63b84c7aa40c88b115e3c0b`.
Post-AGG reconciliation confirms canonical merge receipts for AGG-01, AGG-02,
AGG-04 and AGG-05. Missing package prerequisites are therefore no longer current
blockers and implementation status is `MERGED_CODE`.

Operational status remains `UNQUALIFIED` per venue/family until a campaign
provides current program/deployment identity, exact upstream artifact/license
decision, independent conformance vectors, recorded/loaded-state evidence and a
family-specific qualification verdict. Merge does not enable signing, submission,
remote mutation, live trading or a profitability claim.

## Verification

`.github/workflows/agg06.yml` uses Python 3.13 with the repository hash-locked dev environment and checks compile/format, the AGG-06 regression matrix, existing direct-venue/orderbook/LST/stable-peg regressions, sender-free source constraints, and installed-wheel import outside the checkout. Repository-wide required checks remain authoritative for merge.

## Rollback

Revert this PR. It adds no persisted financial state, schema migration, remote resource, signer/sender authority, or live capability. Existing venue/LST/orderbook/stable-peg owners remain intact.
