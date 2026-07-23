# PR-199 — Economic execution vertical foundation

This PR makes the active shadow pre-trade gate fail closed unless a candidate is
bound to one mint-aware native/wSOL capital calculation. It does not enable
signing, submission, live trading, Jito sending or finalized PnL booking.

## Runtime correction

The previous `ConfiguredCapitalPrecheck` compared `gross_profit_base_units` with
lamport policy thresholds. That allowed different units to be compared as if
they were the same economic asset.

The new PR-199 gate preserves the historical weak-edge rejection code, but a
candidate whose gross edge is large enough must now provide complete integer
cost evidence before it can pass:

- projected final native/wSOL base units;
- flash-loan repayment;
- base network fee;
- priority fee;
- Jito tip;
- peak rent and rent loss;
- protocol fee;
- slippage and uncertainty buffers.

The gate then evaluates the existing `CapitalPolicy`, `CapitalCandidate` and
`AtomicCapitalLedger` rather than comparing raw integers directly.

## Immutable identity and reconciliation boundary

`src/economics/execution_vertical_pr199.py` adds sender-free contracts for:

- deterministic economic attempt identity;
- final-message binding across plan, blockhash context, ALTs, account metas,
  instruction order, exact simulation and final fee hash;
- permit invalidation if the message changes after exact simulation;
- paper reconciliation that keeps quoted/planned/simulated/finalized evidence
  separated and refuses finalized live hashes in paper accounting.

## Safety boundaries

- No signer implementation.
- No transaction submission.
- No Jito/RPC send path.
- No private-key or `Keypair` import.
- No live/canary enablement.
- No finalized/live PnL booking from shadow or paper evidence.

## Focused verification

```bash
python -m pytest \
  tests/test_pr033_snapshot_detectors.py \
  tests/test_pr199_economic_execution_vertical.py \
  -q --disable-socket --allow-unix-socket
```
