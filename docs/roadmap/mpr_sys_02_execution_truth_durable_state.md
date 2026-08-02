# MPR-SYS-02 — Execution Truth and Durable State

## Dependency

MPR-SYS-02 starts from accepted MPR-SYS-01. MPR-SYS-01 owns rooted
candidate and admission truth. This PR does not duplicate that authority.

## Repository-internal contract

The new `src.execution_truth` authority binds one immutable chain:

```text
rooted candidate
  -> exact plan
  -> compiled message
  -> exact simulation
  -> conservative reconciliation
  -> durable terminal attempt
```

Every edge is content-addressed. A mutation of the candidate, plan, message,
simulation, reconciliation or durable record fails closed.

## Durable-state rules

- attempt generation, writer fence, reservation identity and candidate identity
  cannot change during one lifecycle;
- lifecycle revisions are contiguous and stages cannot regress;
- terminal state is immutable;
- successful terminal outcomes require successful exact simulation,
  reconciliation and positive conservative surplus;
- cancellation after message compilation cannot be recorded as a harmless
  cancellation when the side effect is unknown;
- unknown post-simulation effects become `ambiguous` and quarantine capital;
- bool values are not accepted as integers and all economic values use integer
  lamports.

MPR-SYS-02 consumes the accepted durable-state semantic owner
`src.pr206_durable_state.PR206DurableStateStore`. It does not open a second
SQLite authority or introduce an alternate lifecycle writer.

## Existing authorities consumed

- rooted candidate owner:
  `src.rooted_truth.CandidateTruthBinding`;
- durable state owner:
  `src.pr206_durable_state.PR206DurableStateStore`;
- exact economic evidence owner:
  `src.pr227_exact_money_atomic_evidence.PR227EvidenceBundle`.

## Safety boundary

This PR is sender-free and live-disabled. It does not:

- read a private key;
- initialize a signer;
- construct a sender transport;
- submit through RPC or Jito;
- enable live trading;
- claim production readiness.

## Verification

```bash
python -m compileall -q \
  src/execution_truth \
  scripts/verify_mpr_sys_02_execution_truth.py \
  tests/execution_truth

python -m pytest \
  tests/execution_truth \
  -q --disable-socket --allow-unix-socket

python scripts/verify_mpr_sys_02_execution_truth.py --json
```

The verifier deliberately reports external blockers. A repository-internal
passing contract is not evidence of active runtime cutover, credentialed rooted
providers, installed wheel/image execution, or a crash and multi-writer
campaign.
