# MEGA-PR C — Permit-bound isolated submission and finalized settlement

This PR starts MEGA-PR C as a safe, reviewable contract layer for the future
isolated submission and finalized settlement vertical.

It does **not** wire the runtime to a signer, sender, RPC submit path, Jito send
path, live canary, private key, or operator command. The module is deliberately
side-effect free and is meant to be consumed only after the upstream paper and
provider workstreams have produced reviewed evidence.

## Why this starts C safely

The workplan says MEGA-PR C should turn one already proven final message into at
most one authorized submission and reconcile actual finalized effects without
duplicate-send risk. It also says the active submission wiring must wait until:

- MEGA-PR A is merged and stable;
- MEGA-PR B provider/protocol evidence is merged;
- real sender-free soak has demonstrated stable message/economic identity;
- the release candidate is pinned;
- live remains disabled by default.

This PR encodes those prerequisites as machine-readable blockers instead of
bypassing them.

## What changed

- `src/mega_pr_c_submission_settlement.py`
  - `UpstreamReadinessEvidence` for A/B/soak/release prerequisites;
  - `IsolatedSignerBoundary` for process/service isolation and no key access in
    the network runtime;
  - `ProvenMessageBundle` for one exact final message identity;
  - `OneTimeAuthorization` for nonce/expiry/hash-bound signer permits;
  - `DurableSubmissionIntent` for pre-I/O intent, idempotency and fencing;
  - `JitoRpcSubmissionPolicy` for first-live transport restrictions;
  - `TransportObservation` to keep ACK/status separate from settlement;
  - `FinalizedSettlementEvidence` for finalized `getTransaction` and actual
    economic reconciliation;
  - `evaluate_submission_settlement_package(...)` fail-closed readiness evaluator.

- `tests/test_mega_pr_c_submission_settlement.py`
  - upstream evidence missing blocks C;
  - runtime key access blocks;
  - standalone Jito tip and multi-region shotgun send block;
  - consumed/revoked/mismatched authorization blocks;
  - submission intent must be durable before external I/O;
  - duplicate send and blind resend are forbidden;
  - transport ACK/bundle status cannot be economic success;
  - PnL requires finalized actual reconciliation;
  - placeholder hashes fail closed.

## Safety invariants

```text
runtime_live_enabled = false
supported_command_can_submit = false
signer_reachable_from_network_runtime = false
```

## Non-goals

- No private-key import.
- No signer service implementation.
- No signature creation.
- No transaction submission.
- No Jito send/bundle API call.
- No RPC polling/finalized fetch implementation.
- No canary enablement.
- No live mode.
- No bypass of MEGA-PR A/B/D prerequisites.

## Suggested verification

```bash
python -m pytest tests/test_mega_pr_c_submission_settlement.py -q
python -m compileall -q src tests
```

## Follow-up integration owner

A later active integration PR should consume this contract only after the real
sender-free paper vertical, provider/protocol conformance and sender-free soak
evidence are reviewed. That later PR must wire the contract into the actual
submission lifecycle and keep all live/canary controls behind release and
operator gates.
