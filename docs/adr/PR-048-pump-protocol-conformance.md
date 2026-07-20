# PR-048 — Pump protocol conformance and shadow-only promotion

## Context

Roadmap PR-048 promotes Pump only after official artifacts replace local
hypotheses.  The existing repository already had a quarantined
`src.venues.pump` adapter, but its manifest mixed real-looking program IDs with
fixture placeholders such as `fixture-pinned-...` hashes.  That is unsafe because
a shadow adapter can start producing evidence that looks official while being
derived from stale local assumptions.

## Decision

This PR introduces an official-provenance boundary for Pump and PumpSwap:

- the manifest pins `pump-fun/pump-public-docs` commit
  `9c82f61cb711b044a17f770ab8ce9f9bdf78f333`;
- `idl/pump.json` is pinned by Git blob SHA
  `062e66f032bb9f295353b573be3400070bd55e5b`;
- `idl/pump_amm.json` is pinned by Git blob SHA
  `a654b6f924c8e5458ba9b38c9e13a3980f5e9518`;
- shadow eligibility requires `OFFICIAL_PINNED_SHADOW`;
- legacy `ENABLED_SHADOW` or placeholder hashes fail closed before decode;
- instruction discriminators come from the pinned manifest rather than a local
  hash of `contract_version:name`;
- live remains denied.

## Supported scope

The PR is a shadow-only protocol boundary.  It allows read-only account layout
checks and deterministic shadow instruction byte construction from pinned IDL
metadata.  It does not wire Pump into the active runtime by default and does not
submit, sign, bundle or claim landed outcomes.

## Non-goals

- no live sender;
- no canary activation;
- no fake Raydium migration heuristic;
- no synthetic PumpSwap vault balances;
- no replacement for exact simulation/reconciliation evidence;
- no claim that Pump is production-ready.

## Follow-up

A later PR may connect a dedicated Pump detector to `PaperShadowRunner` once
real RPC golden bytes, exact simulation and soak evidence are present.  Until
then, `pump_fun_migration` is at most `shadow-ready` and disabled by default.
