# MEGA-PR-02 — raw-state-owned economic proof qualification

## Status

This draft starts MEGA-PR-02 with an additive, live-disabled qualification
boundary for V4 findings `IMPL-58` and `IMPL-59`.

It does **not** enable signing, sending, RPC/Jito submission, capital release,
realized PnL booking or live trading. The existing PR-037 reconciler remains in
place; this checkpoint adds the proof layer that a reconciliation report must
pass before it can be considered production-qualified profit.

## Why this exists

The V4 audit showed that a caller-assembled repayment DTO and a positive delta
in one settlement asset can be mislabeled as profit even when native fees or
cross-asset value make the total result negative. It also showed that arbitrary
MarginFi program IDs can be treated as repayment proof.

MEGA-PR-02 changes the boundary from:

```text
caller DTO + settlement asset delta >= 0 => PROVEN_PROFIT
```

to:

```text
exact simulation report
  + raw monitored account bindings
  + decoded-state hashes
  + admitted MarginFi registry snapshot
  + conservative valuation snapshot for every asset delta
  + total quote value > policy threshold
  => QUALIFIED_PROFIT
```

## Added checkpoint

`src/execution/economic_reconciliation/mega_pr02_proof.py` introduces:

- `RawSimulationStateProof` and `RawAccountBinding` for raw account evidence;
- `MarginfiRegistrySnapshot` for admitted protocol identity;
- `ConservativeValuationSnapshot` and `ConservativeAssetQuote` for one quote
  currency;
- `RawStateEconomicProofAuthority.qualify(...)` as a fail-closed gate;
- `QualificationStatus.QUALIFIED_PROFIT` as a stricter state than the legacy
  `ReconciliationStatus.PROVEN_PROFIT`.

## Enforced invariants

The qualification gate rejects or downgrades profit when:

- report/evidence/raw state message, response, logs or slot identity diverges;
- any required account lacks raw simulation state;
- decoded state is not bound to the raw account binding hash;
- MarginFi program/bank/vault/account is outside the admitted registry;
- any asset in the reconciliation breakdown has no valuation quote;
- a valuation quote is stale relative to the simulation slot;
- total conservative cross-asset value is zero, below threshold or negative.

## Focused verification

The focused workflow compiles the proof boundary and runs:

```bash
python -m pytest -q tests/execution/test_mega_pr02_economic_proof.py
```

The suite covers:

1. positive settlement-token delta with negative native value is not qualified;
2. strictly positive conservative total can qualify;
3. zero total value is break-even, not profit;
4. unpriced residual assets are indeterminate;
5. attacker-controlled MarginFi program IDs are rejected by registry binding;
6. mutated decoded account hash fails closed;
7. stale valuation fails closed.

The clean-head focused gate has passed after dependency alignment with
`solders==0.28.0`, which is already part of the project dependency set.

## Remaining MEGA-PR-02 cutover

This is only the first reviewable vertical. Before operational paper or live use,
MEGA-PR-02 still needs to replace the caller-supplied DTO path with a trusted
simulation-owned decoder that:

1. preserves exact raw monitored account bytes;
2. decodes required accounts inside the exact-simulation boundary;
3. verifies owner/program/layout/discriminator/mint/authority;
4. binds every decoded value to raw account hashes;
5. uses the official MarginFi protocol registry and admitted plan;
6. requires conservative valuation for all assets, fees, rent and liabilities;
7. makes `net > minimum_profit_threshold` the only profit condition;
8. treats zero, stale, unpriced or residual assets as break-even/indeterminate.

## Review focus

- whether the new qualification status should become the only state allowed to
  unlock production paper PnL;
- whether decoded hashes should be replaced by direct decoder-owned raw byte
  parsing in the next cutover;
- valuation source freshness and quote unit policy;
- exact MarginFi registry shape for bank, vault and margin account admission.
