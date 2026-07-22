# PR-115 — Simulation-owned economic proof boundary

This PR introduces a fail-closed evidence boundary for simulation-owned pre/post
state decoding. It is a safety layer only; it does not enable live submission,
signers, RPC calls, Jito calls, transaction assembly, or MarginFi promotion.

## Problem

The deep architectural audit found that reconciliation observations can be
supplied by a caller independently of raw RPC simulation evidence. That is not a
valid economic proof boundary: a caller could provide profitable-looking native,
token, or MarginFi observations while only copying account hashes.

## Boundary added here

`src/execution/state_evidence_pr115.py` builds a
`PR115SimulationOwnedEconomicProof` from raw account objects only. The proof
binds:

- monitored account address and array index;
- owner and executable flag;
- lamports;
- raw account data bytes;
- raw account hash and decoded hash;
- message hash;
- simulation response hash;
- pre/post state hashes;
- min context slot and optional root slots;
- decoder version.

The proof derives native lamport deltas and legacy SPL Token account amount
deltas internally. It does not accept caller-supplied `native`, `tokens`,
`marginfi`, or `decoded_account_hashes` observations.

## Fail-closed checks

The boundary rejects missing accounts, duplicate monitored addresses, unrequested
extra accounts, executable accounts, stale slots, copied hashes, owner changes,
malformed account data, unsupported owners, and Token-2022 accounts by default.

## Current limitation

The current `ExactSimulationReport` preserves returned account hashes but not raw
returned account objects. Therefore `build_pr115_proof_from_report()` fails
closed when raw accounts are absent. A later integration PR can add reviewed,
bounded raw-account preservation to `RpcSimulationEvidence` and then call this
boundary directly.

## Non-goals

- No live/canary enablement.
- No signer import.
- No RPC/Jito network I/O.
- No transaction submission.
- No MarginFi decoder promotion.
- No Token-2022 execution support.
