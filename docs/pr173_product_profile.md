# PR-173 — Minimal production profile and isolated plugin lifecycle

This PR adds a low-conflict, offline review gate for the roadmap PR-173 product-boundary work.

It does **not** change packaging, active application construction, runtime wiring, signer/sender paths, provider clients, workflows, or dependency locks. The intent is to make the acceptance contract reviewable while parallel PRs continue to move `main`.

## Contract

`src/product_profile_pr173.py` evaluates whether a proposed production artifact is limited to the reviewed core flash-loan vertical and whether optional strategies are physically separated into signed, allowlisted, permissioned plugin components.

The gate checks:

- active production profile is `core-flashloan-paper` or `core-flashloan-live`;
- profile hash and signature are present;
- first production canary remains core-only;
- core package excludes AI advisory, liquidation, orderbook, Pump, lending/indexer, LST and circular-arbitrage domains;
- core does not construct absent or merely disabled optional features;
- missing optional plugins cannot break core import or health;
- capability truth is derived from installed distribution + signed profile + runtime admission;
- plugin discovery is through signed allowlisted metadata rather than arbitrary import path;
- plugin API is versioned and bounded;
- plugin permissions default to no signer, no sender and no treasury mutation;
- plugin crash/hang is isolated from core readiness;
- core and plugin SBOM/provenance are separate;
- revoked plugin cannot stay executable.

## Safety

This PR is intentionally sender-free and live-disabled:

```text
live_claim_allowed = false
sender_submission_allowed = false
```

## Follow-up integration

Later PR-173 work can feed this contract from real packaging metadata, entry points, SBOM/provenance, profile signatures, runtime capability/admission state, and plugin isolation evidence after PR-152/159/161/169 stabilize.
