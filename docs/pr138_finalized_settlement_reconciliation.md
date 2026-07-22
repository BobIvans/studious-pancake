# PR-138 — Finalized post-landing settlement and actual economic reconciliation

## Goal

PR-138 prevents confirmation, bundle status, transport ACKs, or simulation from
being treated as economic success. A transaction can only become economically
successful after finalized actual settlement evidence has been fetched, identity
checked, and reconciled.

## Boundary added in this slice

This PR adds an offline, side-effect-free boundary in
`src/execution/finalized_settlement_pr138.py`. It does not poll RPC, send
transactions, sign payloads, or enable live trading. It consumes already-fetched
status/finalized evidence and returns a typed durable settlement decision.

## Safety properties

- `processed`, `confirmed`, and `finalized` status observations are pending
  observations, not economic outcomes.
- Jito or transport status is recorded only as transport evidence and never as
  settlement proof.
- Finalized actual evidence must match the exact expected message hash.
- Optional expected signature binding rejects mismatched finalized transactions.
- `meta.err` produces a reconciled failure, not success.
- Missing MarginFi repayment proof latches to manual review instead of success.
- Missing or conflicting finalized evidence produces an
  `indeterminate_manual_review` outcome with a durable manual-review state.
- The decision stores a complete redacted evidence hash so later reports can
  distinguish predicted, simulated, confirmed, and finalized-actual layers.

## Non-goals

- No live sender.
- No RPC polling loop.
- No `getTransaction` client implementation.
- No Jito bundle API integration.
- No full account parser. Later PRs can feed this boundary with richer finalized
  account-state and CPI call-graph evidence.

## Suggested verification

```bash
python -m pytest tests/execution/test_pr138_finalized_settlement.py -q
python scripts/verify_repo.py --skip-dependency-audit
```
