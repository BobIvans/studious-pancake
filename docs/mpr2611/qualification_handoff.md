# MPR-2611 production qualification handoff

## Baseline and ownership

MPR-2611 is based on accepted `main` commit `68788d7f7f7da8a2e03b170f93c48af7421ee805` (MPR-2601 / PR #472).

The machine-readable owner map is `config/mpr2611_qualification_authority.json`. MPR-2611 extends the existing qualification composition point in `scripts/qualify_release.py`; it does not create a second debt registry, schema registry, runtime authority, canary controller, signer, economic ledger, or final release gate.

The final promotion authority is reserved to MPR-2612. MPR-2611 always leaves `release_claim_allowed=false` and `live_enabled=false`.

## Parallel scope collision report

Observed parallel owners at the final coordination pass:

| MPR | PR | Head | Owned semantic surface | Collision with 2611 |
| --- | ---: | --- | --- | --- |
| 2607 | #477 | `00e634dd230ff6955cd11fe7bc0257cb95e9d3a5` | shadow-soak campaign evidence | none |
| 2608 | #479 | `aaedbc3dfaaa640317b5f746b7711b7649f5f6f9` | isolated signer/submission + minimum finality | none |
| 2609 | #480 | `7f0633eafdd12bf4e4f4b88986a62ac743d482f7` | one-shot limited-live canary authority | none |
| 2610 | #481 | `0810bde47684931ccfa0f497d3ad4c2380b6b0af` | finalized economic ledger / realized PnL | none |

The exact changed paths are pinned in the authority-map JSON and are verified disjoint from MPR-2611-owned paths.

## Qualification architecture

1. `src/qualification_pr176.py` owns the qualification plan and strict dependency closure.
2. `src/production_qualification.py` is the evidence consumer and semantic authenticity validator.
3. `scripts/qualify_release.py` remains the existing executed-qualification/debt-projection composition point.
4. `scripts/verify_mpr2611_production_qualification.py` verifies single-owner architecture and fail-closed output invariants.
5. `scripts/run_mpr2611_clean_qualification.py` recomputes the deterministic qualification snapshot at least twice and independently recomputes its digest.
6. MPR-2612 is the only final release/promotion gate.

## Evidence contract

Critical production evidence is rejected unless it is a non-empty strict JSON object with an accepted schema family, exact source commit, exact release id, producer identity, explicit production-evidence marker, non-synthetic semantics, and a positive producer verdict. Artifact-specific rules additionally require finalized/reconciled integer realized economics, real shadow duration, or second-human/no-auto-rearm canary semantics.

Raw SHA-256 and canonical semantic SHA-256 are kept separately. A missing or semantically invalid artifact cannot resolve debt.

## Current external/integration blockers

MPR-2611 intentionally does not fabricate evidence that must be produced by other work or by a governed runtime environment. Until those inputs exist for the exact release generation, qualification remains blocked. This includes real shadow-soak evidence, isolated signer/deployed transport evidence, completed limited-canary evidence, finalized realized-PnL evidence, provider/deployment drift evidence, backup/restore and fault evidence, installed image/wheel/SBOM provenance, and any required platform/runtime observations.

A blocked qualification is a valid MPR-2611 result; it is not a test failure and must not be rewritten as a production pass.

## MPR-2612 handoff contract

MPR-2612 may consider a release only when all of the following are true for one immutable release id and source identity:

- `production_qualification_passed=true`;
- `eligible_for_release_review=true`;
- repeated clean qualification is stable and the independent digest matches;
- no required artifact is missing or invalid;
- no production debt item remains open;
- the qualification bundle digest is independently recomputed after the last evidence mutation;
- human review is bound to the final immutable evidence digest;
- `release_claim_allowed` is still false in the MPR-2611 bundle;
- `live_enabled` is still false in the MPR-2611 bundle.

MPR-2612 must reject stale review, changed evidence, mixed release generations, or any attempt to treat MPR-2611 itself as promotion authority.
