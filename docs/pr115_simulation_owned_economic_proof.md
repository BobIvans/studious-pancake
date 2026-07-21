# PR-115 — Simulation-owned pre/post state decoding and economic proof

PR-115 starts the P0 boundary that prevents reconciliation callers from
inventing economic observations independently of raw RPC state evidence.

## Scope of this slice

This patch introduces a sender-free, offline evidence boundary:

- raw pre-state and post-state account objects are decoded by the PR-115 module;
- every decoded account is bound to monitored address, array index, owner,
  executable flag, lamports, data bytes, raw hash and decoded hash;
- native lamport deltas and legacy SPL token amount deltas are derived internally;
- copied post-account hashes cannot authorize a different raw account body;
- Token-2022 remains fail-closed by default;
- duplicate, missing, extra, executable, stale-slot and malformed accounts are rejected;
- the report links message hash, simulation response hash, pre/post state hashes,
  raw evidence hash, decoder version and slot/root metadata.

## Non-goals

This PR does not submit transactions, sign messages, contact RPC, enable live
mode, or complete MarginFi/Token-2022 decoding. It intentionally keeps those
higher-risk decoders behind explicit future evidence work.

## Current integration boundary

`build_pr115_proof_from_report()` consumes an `ExactSimulationReport` only when
its final simulation evidence preserves raw returned account objects. If a report
only has returned account hashes, the function fails closed with:

```text
final simulation did not preserve raw accounts
```

This prevents old hash-only simulation reports from being promoted into economic
proof. A follow-up patch can wire exact simulation to persist bounded raw account
objects directly in `RpcSimulationEvidence` once that storage format is reviewed.

## Suggested verification

```bash
python -m pytest tests/test_pr115_simulation_owned_economic_proof.py -q
python scripts/verify_repo.py --skip-dependency-audit
```
