# PR-023 quarantine policy

Quarantined code is retained for migration, historical comparison, offline
fixtures, or future protocol work. It is not part of the supported runtime and
must not be activated by an environment variable alone.

## Current quarantine groups

- `src/legacy_arb_bot.py`: historical monolithic runtime.
- `src/ingest/tx_builder.py`, `src/ingest/execution_router.py`,
  `src/ingest/jito_executor.py`: legacy transaction/submission paths.
- `scripts/paper_trader.py` and root `paper_trader.py`: non-canonical paper
  implementations.
- `src/venues/pump/`: Pump fixtures/adapter pending official conformance.
- `src/providers/orderbook/`: Phoenix/OpenBook fixtures and planners pending
  protocol promotion.
- `src/liquidation/` and Kamino strategy shell: advanced lending/liquidation
  work that is not connected to the supported runtime.
- `src/providers/marginfi/`: provider foundation pending real binary account and
  instruction conformance.

The authoritative per-component state is `config/capabilities.json`.

## Enforcement

- `src/application.py` imports no legacy execution/sender modules.
- Advanced strategies are constructed disabled; environment flags are ignored
  by the supported composition root.
- The capability contract is validated against the strategy registry.
- Quarantined components may declare only `allowed_modes: ["disabled"]`.
- Tests fail if a quarantined strategy is enabled or a registered strategy is
  missing from the matrix.

## Removal/promotion

A later PR may move, delete, or promote a quarantine group. Promotion is not a
rename: it requires protocol pins, conformance fixtures, exact simulation,
economic reconciliation, and the roadmap acceptance evidence for that module.
