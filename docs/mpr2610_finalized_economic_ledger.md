# MPR-2610 — Finalized Economic Ledger

Base: `main@68788d7f7f7da8a2e03b170f93c48af7421ee805`.

## Ownership and anti-duplication

- MPR-2601 remains canonical lifecycle/capital/durable-state authority.
- MPR-2608 draft PR #479 owns isolated signer/submission and the minimum 2610A finality/unknown-capital boundary.
- MPR-2609 canary admission/budget/arming remains a predecessor consumer/producer boundary and is not duplicated here.
- PR138 remains a compatibility finalized-settlement classifier; MPR-2610 fixes its false-positive economic-success regression but does not make `SettlementComparison` the canonical economic source.
- `src/execution/economic_reconciliation/` remains a reusable raw-state/economic evidence producer.
- MPR26/PR196/treasury stores remain policy/projection/risk surfaces unless separately accepted as the durable owner.
- MPR-2610 adds no SQLite database and no second submission/finality FSM.

## Implemented checkpoint

`src/execution/finalized_economic_ledger.py` is a pure, sender-free consumer that binds finalized attempt lineage to immutable economic postings in exact integer base units. It:

- preserves per-asset deltas instead of adding unlike units;
- excludes funding and sweep movements from strategy PnL;
- distinguishes finalized failure, pending economics, loss, break-even, profit, partial and quarantined outcomes;
- requires positive complete single-asset realized economics before setting `economically_successful=true`;
- requires cross-asset valuation before a multi-asset result may become a total-profit claim;
- validates payer SOL conservation when pre/post balances are supplied;
- treats `meta.fee` as the total Solana fee and reconciles it against the network-fee posting instead of subtracting priority fee twice;
- keeps MarginFi repayment as a required finalized proof input for a successful transaction;
- hashes deterministic lineage + postings into a replayable ledger result.

PR138 now fails closed when finalized actual net is missing, zero or negative. This closes the supplied MPR-2610 regression where finalized + repayment could previously become `RECONCILED_SUCCESS` regardless of `actual_net_lamports`.

## Explicit residual scope

This checkpoint does not yet claim complete E01-E72 closure. Raw `getTransaction` bounded decoder retention, exact token-account lifecycle/Token-2022 decoding, decoded MarginFi liability/vault proof, Jito instruction-level tip proof, WSOL lifecycle proof, durable caller-owned atomic posting/outbox integration, derived valuation authority, restart/crash campaign, installed wheel/image qualification and real finalized canary evidence remain follow-on integration/qualification work.

No real key was loaded, no transaction was signed/submitted, no RPC/Jito live call was made, no canary was activated, no money moved and no profitability was inferred from synthetic fixtures.
