# MEGA-PR A2 — Exact attempt runtime bridge

This PR starts the next practical MEGA-PR A continuation after the merged
exact sender-free attempt vertical.  It does not complete MEGA-PR A by itself;
it creates the repeatable runtime projection that a supported paper runner can
consume without inventing signatures, live sends, or fake settlement.

## What this slice does

- consumes `ExactPaperAttemptOrchestrator` results from
  `src/paper_shadow/exact_attempt_pr152.py`;
- maps exact-attempt outcomes into the workplan terminal states:
  `NO_TRADE`, `BLOCKED`, `SIMULATION_FAILED`, `RECONCILED_PAPER_SUCCESS`,
  `RECONCILED_PAPER_FAILURE`, and `INDETERMINATE`;
- preserves attempt generation, provider evidence hash, message hash and
  reconciliation hash;
- stops immediately if any result exposes sender or submission reachability;
- exposes deterministic JSON and report hashing for durable lifecycle storage;
- remains package-visible from `src.paper_shadow`.

## Why this is not another isolated gate

The workplan says the next work must wire existing contracts into the active
runtime, not add more disconnected evaluators.  This slice uses the already
merged exact attempt orchestrator as the input authority and creates a reusable
runtime cycle report that later CLI/composition cutover can persist in the
single durable lifecycle store.

## Safety invariants

- live enabled: false;
- sender reachable: false;
- signer reachable: false;
- fake signature or bundle success: false;
- submission allowed: false;
- unfinalized PnL booking: false.

## Remaining MEGA-PR A work

Follow-up work still needs to connect this runtime bridge to the supported
`flashloan-bot run --mode paper` path, real provider/RPC fixtures, the selected
durable lifecycle authority, wheel/source parity checks and restart/replay
coverage.
