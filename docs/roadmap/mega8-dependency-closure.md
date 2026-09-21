# MEGA8 current-head dependency reconciliation

This closure repairs evidence and integration debt caused by parallel development
and out-of-order merges. It does not create another runtime, solver, signer,
sender, capital ledger or release authority.

## Historical facts retained

The canonical merge receipts preserve three dependency-order inversions:

- MEGA8-02 merged before MEGA8-01;
- MEGA8-05 merged before MEGA8-04;
- MEGA8-06 merged before MEGA8-04.

MEGA8-07 merged after MEGA8-01..06 were present on its merge base, so its debt is
a stale dependency manifest, not another implementation inversion.

## Current-head closure

The closure baseline is 613884d8a5d50b1230b29ec5db14627222a9e85d.
The reconciliation verifier requires all seven merged receipts, exact roadmap
dependency edges, the historical inversion set, current cross-Mega imports and
retirement of stale OPEN_NOT_MERGED / NOT_MERGED blockers.

Requalification is deliberately scoped:

- MEGA8-02 is rechecked with MEGA8-01 and the canonical SUPER-02 financing closure.
- MEGA8-05 is rechecked after MEGA8-04.
- MEGA8-06 is rechecked after MEGA8-04 and MEGA8-05.
- MEGA8-07 dependency evidence is resealed on a baseline that contains all 01..06.
- SUPER-02 -> AGG-04 code/import/owner contracts are requalified on the same
  closure baseline.

## What remains blocked

This PR does not convert external or operational evidence into PASS. Real
deployment/program/provider state, SDK license/conformance, loaded-state/fork/
finalized landing/soak campaigns, real HSM/KMS, chaos deployment, EVM/Sui/bridge
qualification, TPU/block-engine measurements, Rust/GPU parity and capital/live
promotion remain separate evidence work.

SUPER-02 remains BLOCKED_EXTERNAL. Its old generic
AGG04_REQUALIFICATION_REQUIRED_ON_EXACT_LENDER_PROFILE_GENERATION blocker is
retired only at the code-contract layer and replaced by the narrower external
campaign requirement for an exact deployment/profile generation.

## Verification

- python scripts/verify_mega8_dependency_closure.py --json
- pytest -q tests/test_mega8_dependency_closure.py
- focused regressions for MEGA8-02, 04, 05, 06 and 07
- repository verification and installed-package smoke

All live/signing/submission/automatic-capital permissions remain false.
