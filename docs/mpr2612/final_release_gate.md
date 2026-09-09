# MPR-2612 final release gate

MPR-2612 converges the historical `src/release_gate/mpr31_final_promotion_gate.py` owner into the canonical final release authority. It does not create a second promotion owner.

Accepted predecessor integration context at branch creation:

- MPR-2602 PR #473 merged.
- MPR-2603 PR #474 merged.
- MPR-2604 PR #475 merged.
- MPR-2605 PR #476 merged.
- MPR-2606 PR #478 merged.
- MPR-2607 PR #477 merged.
- MPR-2608 PR #479 merged.
- MPR-2609 PR #480 merged.
- MPR-2610 PR #481 merged.
- MPR-2611 PR #482 merged.
- base `main`: `d23f82e20d10345926742352739b1a6ca3f7a859`.

## Security correction

The historical structural gate accepted fields that merely looked like SHA-256 digests as signature/reviewer evidence. That path is now compatibility-only and always returns `BLOCKED` with `MPR2612_CANONICAL_RELEASE_GATE_REQUIRED`.

The canonical `MPR2612FinalReleaseGate` requires:

- independently recomputed and verified MPR-2611 qualification identity;
- exact release/source/tree/wheel/image/config/policy/runtime/debt/SBOM/platform binding;
- `production_qualification_passed=true` and `eligible_for_release_review=true`;
- MPR-2611 itself to keep `release_claim_allowed=false` and `live_enabled=false`;
- no unresolved P0 blockers;
- a release proposal targeting only `RELEASED_PRODUCTION_DEFAULT_OFF`;
- at least two distinct trusted human principals;
- actual signature verification through an injected accepted cryptographic verifier;
- trust-registry resolution for each approval;
- exact proposal/qualification/release binding and validity windows;
- hard-safety-latch fail-closed behavior.

A successful decision may set `production_ready=true`, `release_claim_allowed=true`, and `product_state=production-ready-default-off`. It always returns `live_enabled=false`, `unrestricted_live_allowed=false`, and `automatic_scale_up_allowed=false`.

## Deliberate remaining blockers

This implementation does not fabricate a real production release. A real release still requires the exact MPR-2611 production qualification bundle, real accepted reviewer identities/signatures, the caller-owned durable one-shot promotion transaction, immutable release receipt, and any external/platform evidence required by policy. Until those are provided, the release verdict remains blocked.
