# MPR-08 completion ledger and release truth gate

This additive slice starts **MPR-08 — Completion ledger, package surface and cryptographic release truth** from the V6 post-MPR roadmap.

## Scope

The gate defines an offline, sender-free acceptance contract for the next completion/release identity boundary. It intentionally does not replace the existing runtime, package smoke, signer service or deployment code in this PR.

It models the minimum evidence future MPR-08 implementation must materialize before the repository can truthfully claim that completed MPR-01…07 work and active MPR-08+ work are the source, wheel, image and policy actually being qualified.

## Covered risk classes

The validator maps F-270…F-280 into deterministic blockers:

- fixed historical authority schemas that cannot represent MPR-08+;
- package smoke or mirrors that validate obsolete completion truth;
- installed console commands missing from the production-surface manifest;
- release evidence whose source commit is not grounded in clean Git HEAD, wheel metadata and image metadata;
- caller-selected release trust anchors;
- stale, future-dated or replayed release attestations;
- unbounded artifact hashing and placeholder digests;
- mutable builder images, unhashed dependencies and missing offline wheelhouse;
- runtime live/sender/transaction-signer enablement inside a completion truth gate.

## Added files

- `src/mpr08_completion_release_truth_gate.py` contains a pure-Python validator and deterministic report model.
- `tests/test_mpr08_completion_release_truth_gate.py` covers the complete happy path and adversarial failures.
- `.github/workflows/mpr08-completion-release-truth-gate.yml` runs focused compile and pytest checks.

## Safety boundary

A passing report still returns:

```text
transaction_signer_allowed=false
sender_allowed=false
live_execution_allowed=false
```

The PR does not perform live trading, signing, provider calls, RPC/Jito submission, transaction assembly, image building, package publishing, secret reads or deployment cutover.

## Next implementation work

A later MPR-08 completion slice can connect this contract to generated release manifests, installed wheel/image inspection, every console script smoke, bounded artifact hashing and policy-owned release-signature verification.
