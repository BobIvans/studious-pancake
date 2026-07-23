# MPR-01 — Canonical installed runtime and release-truth gate

This slice starts the V4 mega-roadmap **MPR-01** boundary.

The V4 audit says the repository is safer as a codebase, but still fails the
production-system test because safety modules are not authoritative in one
installed runtime. The first MPR-01 step is therefore not another isolated
evaluator. It wires a mandatory repository verification gate into the existing
production surface manifest and `scripts/verify_repo.py`.

## What this slice enforces

- The supported product stays explicitly `not-production-ready`.
- The MPR-01 runtime cutover contract is carried in the packaged production
  surface manifest.
- There is exactly one named canonical installed composition target:
  `flashloan-bot paper` through `src.cli_pr189`.
- Container paper mode is not allowed to claim workload readiness until it is
  cut over to the same composition.
- Liveness, safe-idle, data-ready, paper-ready and live-gate are distinct
  endpoint contracts.
- Release truth remains blocked until a single authoritative
  `release-qualification` check can reproduce from the signed artifact without
  ambient packages or network.
- Known proof-island modules must be integrated, quarantined, or converted to
  aliases before they can count as runtime authorities.

## What this slice does not claim

This PR does not make the bot paper-ready or live-ready. It does not wire
MarginFi/Jupiter/RPC dependencies, build a transaction, simulate, sign, submit,
or migrate runtime storage.

A passing MPR-01 gate means only that the repository now has a fail-closed
contract for the canonical runtime cutover and that `verify_repo.py` enforces
that contract.
