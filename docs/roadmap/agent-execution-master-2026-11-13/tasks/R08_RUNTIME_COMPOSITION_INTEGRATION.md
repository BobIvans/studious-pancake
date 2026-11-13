# Assignment — R-08 supported runtime composition integration

Copy-ready trigger: Audit the current supported entrypoint and composition root from README.md, config/capabilities.json, src/resources/runtime_authority.json, package scripts, current CLI and runtime tests. The current product truth is sender-free, live hard-denied and not production-ready. Map existing library owners that are not reachable from the installed paper/shadow composition root, including Dynamic Universe and current discovery/data owners. Propose the smallest composition-only integration that connects verified inputs to the existing paper lifecycle without creating new authorities or changing signer/sender boundaries.

## Required work
1. Record exact active entrypoint, runtime dependencies, strategy/capability states and package quarantine.
2. Draw current vs target runtime dependency graphs. Identify every missing injection/binding and which owner supplies it.
3. Reuse source governance, campaign readiness, AssetResolver, DynamicUniverse, ResearchEconomicGraph/UniversalArbitrageGraph, FlashCapitalGraph, PR118 sizing, planner, ExactSimulationFinalizer, lifecycle authority, durable reservations and paper service.
4. Keep modules that only perform diagnostics/research outside the supported application path until their evidence contract is accepted.
5. Build fail-closed composition tests for missing source, stale identity, unsupported provider, missing capacity, no route, exact quote failure, financing evidence mismatch, stale state and storage pressure.
6. Keep strategy registry/capability manifest/package quarantine in lockstep; never make a strategy ready only by editing config or env.
7. Separate paper candidate creation from exact simulation and paper qualification; do not make synthetic fills.

## Acceptance
- An explicit owner/injection matrix and composition graph.
- A minimal PR with no duplicate engine, lifecycle authority, journal, capital ledger or sender.
- Existing status/capability commands and safe-idle behavior unchanged.
- Offline tests, package smoke and full verifier pass.
- Current live_enabled/sign_enabled/send_enabled remain false and live mode hard-denied.
