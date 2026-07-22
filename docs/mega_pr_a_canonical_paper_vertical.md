# MEGA-PR A — canonical paper vertical startup cutover

This PR starts the **Canonical sender-free paper execution vertical** workstream.

It does not claim the full MEGA-PR A acceptance is complete. The workplan says
new work must wire existing contracts into the active runtime and must not add
another isolated evaluator. This slice therefore changes the supported
`paper_shadow` composition root used by the installed CLI.

## What changes

- Adds `src/paper_shadow/canonical_paper_vertical.py`.
- Updates `src/paper_shadow/composition.py` so `build_paper_shadow_runtime(...)`
  creates a deterministic canonical-paper-vertical startup record for the active
  paper path.
- The runner evidence now includes `canonical_paper_vertical` startup evidence.
- Dependency blocks now use MEGA-PR-A reason codes:
  - `blocked_pr_a_canonical_vertical_unwired`
  - `blocked_pr_a_canonical_vertical_invalid`
- Live, signer and sender remain structurally unavailable.

## Why this is active integration

Before this change, the default paper path constructed
`PaperShadowRuntimeDependencies()` and all runner stages were replaced by a
generic dependency gate. After this change, the same active composition root
evaluates and records the exact required runtime surfaces:

- `atomic_stage_suite`;
- `exact_fee_workflow`;
- `verified_marginfi_provider`;
- `jupiter_v2_build`.

That creates the named cutover seam for the rest of MEGA-PR A. Later commits in
this workstream must satisfy this seam with reviewed provider/RPC/economic
dependencies instead of adding duplicate gates.

## Safety invariants

- `live_allowed` is always false.
- `sender_reachable` is always false.
- `signer_reachable` is always false.
- fake success is not permitted.
- no provider, RPC, Jito, signer, sender or private-key code is imported.

## Non-goals

- No trading logic change.
- No transaction compilation.
- No simulation/network calls.
- No signing or submission.
- No live/canary activation.

## Follow-up required for full MEGA-PR A

The remaining MEGA-PR A work must wire real reviewed dependencies into the
startup seam so `flashloan-bot run --mode paper` can repeatedly reach durable
sender-free paper outcomes from captured provider/RPC fixtures.
