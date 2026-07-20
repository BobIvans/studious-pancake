# PR-056 — runtime discovery, snapshots, universe, and detector composition

## Boundary

The supported `flashloan-bot paper-shadow` command now runs one bounded,
sender-free discovery cycle before invoking the paper/shadow runner:

```text
configured universe
  -> one runtime-owned DiscoveryPlane
  -> normalized provider quotes
  -> immutable provenance-rich snapshots
  -> circular detector
  -> bounded, deduplicated candidates
  -> PaperShadowRunner
```

PR-056 does **not** add capital reservations, transaction planning, compilation,
simulation, reconciliation, signing, or submission. Those remain the scope of
later remediation PRs.

## Fail-closed health semantics

`healthy_idle` is valid only when the discovery evidence says the required
routes completed successfully and the detector produced no candidate. Missing
wallet configuration, cycle timeout, missing required route legs, stale quotes,
or quotes without a context slot produce a blocked state instead of healthy
idle.

## Runtime ownership

`build_runtime_discovery` creates exactly one `JupiterQuotaManager` and injects
it into the single `ProviderRegistry`/`DiscoveryPlane` used by the cycle. This
prevents per-call quota managers from bypassing an account-wide budget.

The packaged universe contains a required SOL/USDC loop and optional selected
LST loops for jitoSOL, mSOL, and bSOL. Every accepted snapshot records provider,
endpoint/source, request fingerprint, response hash, slot, commitment,
observation/expiry timestamps, provider timestamp, and correlation labels.
