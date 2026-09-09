# MPR-2609 — limited live canary implementation checkpoint

## Base / predecessor state

This branch is stacked from `codex/mpr-2608-isolated-signer-submission` at
`aaedbc3dfaaa640317b5f746b7711b7649f5f6f9`, whose merge base with `main` is
`68788d7f7f7da8a2e03b170f93c48af7421ee805` (merged MPR-2601).

Observed parallel work at creation time:

- MPR-2602: draft PR #473
- MPR-2603: draft PR #474
- MPR-2604: draft PR #475
- MPR-2605: draft PR #476
- MPR-2606: draft PR #478
- MPR-2607: PR #477
- MPR-2608: branch `codex/mpr-2608-isolated-signer-submission`

MPR-2609 therefore remains a stacked implementation checkpoint. It does not claim
that the predecessor evidence is accepted merely because a branch or PR exists.

## Canonical owner

`src.live_canary` remains the canary semantic package. MPR-2609 adds
`src.live_canary.mpr2609.DurableCanaryAuthority` as the durable one-shot authority
rather than creating another top-level canary controller.

The historical `LimitedLiveCanaryController` remains import-compatible while the
new authority owns durable MPR-2609 admission semantics. A later physical cutover
must make legacy process-local controllers verifier/alias-only before MPR-2609 can
claim complete canonical consolidation.

## Implemented in this checkpoint

- caller-owned SQLite state; no hidden commit/rollback and no second connection;
- default state is `shadow`;
- durable control generation, permit, admission-consumption and outstanding attempt;
- explicit predecessor identity bundle for MPR-2601/2603/2604/2605/2606/2607/2608;
- exact policy/budget digest binding;
- two distinct human principals required by the permit contract;
- one arm authorizes at most one admission bundle;
- exact immutable admission identity binds candidate, route, message, simulation,
  account metas, blockhash, wallet, market, reservation and transport;
- pre-handoff generation/expiry/blockheight/outstanding checks;
- UNKNOWN/ambiguous outcome becomes a sticky durable latch and is not resendable;
- terminal reconciliation returns to shadow and does not auto-rearm;
- rollback increments generation and does not erase an outstanding attempt;
- exact integer realized PnL only; no caller float/bool economics;
- bounded machine-readable event rows with deterministic event hashes.

## Deliberately not implemented here

- private-key loading or signing;
- RPC/Jito transport clients;
- `sendTransaction`, `sendRawTransaction` or `sendBundle`;
- any automatic mainnet canary execution;
- automatic re-arm or scale-up;
- full MPR-2610 production economic ledger;
- fabricated external endpoint, installed-image, or real mainnet evidence.

MPR-2608 remains the signer/submission boundary. MPR-2609 produces only an exact,
permit-bound admission identity for that boundary to consume.

## Residual blockers before MPR-2609 completion

1. predecessor PRs 2602-2608 must reach accepted final interfaces/evidence;
2. durable MPR-2609 rows should be migrated into the accepted lifecycle schema
   owner rather than remain an additive table once that integration contract is final;
3. MPR-2603 permit verification must be wired to its accepted authenticated human
   principal/permit authority rather than supplied as a typed value;
4. MPR-2607 shadow evidence and MPR-2608 signer/transport qualification must be
   consumed from their final accepted evidence schemas;
5. legacy canary controllers must be physically quarantined/aliased so only one
   reachable authority can grant current canary admission;
6. complete cap enforcement (wallet reserve, fee/priority/Jito tip, exact program /
   writable-account allowlists, data freshness and RPC divergence) must be wired to
   accepted current-state evidence at the final integration head;
7. finalized Solana transaction metadata must feed the exact reconciliation decoder;
8. crash campaign, multi-writer race, wheel/image reachability and full repository
   verification must pass on the final stacked head.

## Safety truth

```text
canary_implementation_ready = false
mainnet_canary_executed = false
unrestricted_live_ready = false
automatic_scale_up = false
production_ready = false
```

No real transaction is authorized or executed by this branch.
