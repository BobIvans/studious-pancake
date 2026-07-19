# PR-020 shadow liquidation planner

PR-020 adds a shadow-only liquidation planning boundary. It does not sign, send,
bundle, retry, or request a live permit. PR-018 limited-live readiness does not
authorize liquidation; liquidation remains analysis-only.

## Compatibility matrix

No mainnet deployment is enabled by default in this repository fixture. Kamino
Lend and MarginFi v2/Project Zero adapters exist, but a market/pair is planned
only after binary PR-019 snapshots supply a matching program id, owner/layout,
IDL digest, oracle/risk config, close factor, bonus, fees, caps, liquidity and
route evidence. Missing verification is a typed disabled/reject status.

## Lifecycle

1. PR-019 indexer emits a coherent binary target snapshot.
2. The protocol adapter validates deployment, layout, oracle freshness/confidence
   and weighted health evidence. This is only `POTENTIALLY_LIQUIDATABLE`.
3. The sizer caps integer repay by liability, close factor/max value, target and
   flash liquidity, executable route depth, strategy cap and wallet operating
   reserve policy.
4. The planner builds one atomic instruction plan: compute/tip policy outside
   this package, MarginFi flash start, borrow, target liquidation, unwind, repay
   and end.
5. PR-013-style reconciliation must prove flash repayment, target/liquidator
   deltas, postconditions and simulated PnL. Program success alone is rejected.

## Accounting boundary

Flash principal is not wallet capital. The wallet pays only native operational
costs, rent/failure budget and exactly-one tip policy through the existing
PR-010 boundary. Token-2022 transfer fees, protocol/insurance fees and unwind
min-out are counted once as integer base units.

## Rejection reasons

The stable PR-020 reason codes are defined in `src/liquidation/models.py` and
include unsupported protocol/deployment/IDL/layout, stale oracles, health model
mismatch, unknown close factor/bonus, insufficient target/flash/route liquidity,
non-composable plans, unproven postconditions and simulated repayment failure.

## Legacy isolation

`src/ingest/liquidator_engine.py` is quarantined and raises before the legacy
execute path. The conflict-prone legacy placeholder builder/send body was removed
from that method; the remaining method is an import-compatible hard stop for
historical callers. The active PR-020 shadow strategy imports no sender, signer,
Jito, keypair transport or live permit modules.
