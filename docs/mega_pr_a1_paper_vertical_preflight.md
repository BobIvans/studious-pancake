# MEGA-PR A1 — paper vertical preflight

A1 starts the canonical sender-free paper execution vertical by exposing the
required runtime dependency seam through the supported installed CLI.

The production-ready workplan says MEGA-PR A must connect discovery, provider
evidence, economics, planner, compiler, exact simulation, CPI proof,
reconciliation, durable lifecycle and observability into one supported
sender-free runtime. This PR does not claim that full vertical is complete. It
creates the first active operator/CI preflight for that integration.

## Active command

```bash
flashloan-bot paper-vertical-preflight --json
```

The command evaluates the default supported paper dependency surface without
network IO and reports:

- `atomic_stage_suite`;
- `exact_fee_workflow`;
- `verified_marginfi_provider`;
- `jupiter_v2_build`.

A missing or invalid surface returns the same blocked exit family as paper/shadow
runtime blocking. A complete surface would return ready, while still reporting
live, signer, sender, private-key loading, fake success and network IO as false.

## Why this is not another offline gate

The preflight is part of `src/cli.py`, so source checkout and installed console
usage can see the exact same canonical-paper dependency seam before a paper run.
It does not add another separate runtime truth store.

## Safety invariants

- No live trading.
- No signer or sender import.
- No RPC, Jito, Jupiter, Helius or MarginFi network call.
- No transaction build, compile, sign, simulate or submit.
- No fake signature, bundle ID, finalization or profit.

## Follow-up

Later A slices should feed reviewed dependencies into the same seam and then run
`flashloan-bot run --mode paper` repeatedly from captured provider/RPC fixtures
until one durable sender-free paper outcome is produced.
