# MPR-2616 — executable single-active HA/DR + fenced failover

This slice implements the **fail-closed executable boundary** requested by the
MPR-2616 handoff without fabricating a distributed coordinator.

## Ownership / collision map

Observed at implementation start on 2026-09-09:

| Workstream | Observed state | Semantic owner | MPR-2616 treatment |
|---|---|---|---|
| MPR-2612 | branch exists, identical to current `main` | final release gate reserved | no release authority created |
| MPR-2613 | branch exists, one new `src/operations/mpr2613_guarded_operations.py` file | guarded production operations | no overlap; no operations controller copied |
| MPR-2614 | no public branch/PR observed | continuous conformance sentinel reserved | consumed only through optional conformance lease digest |
| MPR-2615 | no public branch/PR observed | **RESERVED unknown parallel scope** | no claim that 2615 is absent; re-check before merge |
| PR-165 | accepted main offline HA/DR evidence contract | shape/policy evidence | kept intact; cannot by itself qualify executable HA |
| MPR-RP-03 | accepted same-host local-resource lease | local resource ownership | explicitly rejected as cross-host fencing proof |
| MPR-2608 | signer/submission owner | signer/sender effect boundary | 2616 exposes fence assertions; does not implement signer API |
| MPR-2609 | canary authority | one-shot live/canary authorization | fresh authorization remains mandatory after takeover |
| MPR-2603 | human intervention owner | takeover/failback approval | 2616 consumes a canonical receipt digest; no second approval format |

## What this slice adds

`src/ha_dr/mpr2616.py` adds:

- an explicit leader/standby state vocabulary;
- a cross-host fencing backend protocol;
- a deterministic linearizable **sandbox-only** CAS backend for concurrency,
  pause/resume and stale-leader regressions;
- exact release/config/policy/runtime/genesis/wallet/boot identity binding;
- restore evidence that preserves WAL, consumed permits, UNKNOWN holds, risk
  counters, suspension and fencing generation;
- explicit human-authorized takeover that always returns `ACTIVE_DEFAULT_OFF`;
- effect-adjacent signer/sender checks that revalidate the current fence;
- non-negotiable UNKNOWN-dispatch recovery semantics with no blind resend;
- materialized campaign events with derived RPO/RTO and dual-active detection;
- strict JSON parsing (duplicate-key and NaN/Infinity rejection);
- a final qualification evaluator that cannot be made positive by legacy PR-165
  booleans/hash-shaped strings alone.

## External truth boundary

The repository currently does not expose an approved production
strongly-consistent cross-host coordinator backend to MPR-2616. Therefore the
provided in-memory coordinator is marked `sandbox_only=true`, `cross_host=false`,
and cannot satisfy production qualification. Real HA remains
`BLOCKED_EXTERNAL_INFRASTRUCTURE` until an approved backend (for example an
existing deployment-provided linearizable coordinator) supplies independently
verifiable CAS/lease receipts.

Likewise, real signer recovery, provider-region failover, object-store receipts,
and host-level DR campaigns remain external evidence. Tests exercise the state
machine and adversarial invariants without pretending that CI killed a real
host or moved real funds.

## Safety invariants

- no private-key handling;
- no signer implementation;
- no RPC/Jito submission;
- no automatic live enablement;
- no automatic canary rearm;
- no automatic capital scale-up;
- no blind resend after a durable dispatch marker;
- successful takeover is `ACTIVE_DEFAULT_OFF`;
- a stale fence is rejected again at every effect-adjacent boundary.

## Merge meaning

A green merge accepts the fail-closed state machine, coordinator contract,
integration harness and evidence evaluator. It **does not** assert that external
HA infrastructure has been qualified or that the bot is production/live ready.
