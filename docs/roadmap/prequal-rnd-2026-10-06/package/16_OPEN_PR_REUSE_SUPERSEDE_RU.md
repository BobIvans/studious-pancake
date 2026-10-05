# Open PR Reuse / Supersede Audit

| PR | Title | vs main | ahead/behind | Action |
|---|---|---|---:|---|
| #443 | MPR-43 Unified persistence migration and recovery foundation | diverged | +5 / -1605 | DO_NOT_MERGE_DIRECTLY; harvest tests/contracts into QPR-07 |
| #440 | MPR-41 Trusted provider data-plane authority | diverged | +6 / -1610 | DO_NOT_MERGE_DIRECTLY; harvest contracts/tests into QPR-02 |
| #428 | MPR-NEXT-09 Continuous installed paper/shadow soak producer | diverged | +7 / -1665 | DO_NOT_MERGE_DIRECTLY; harvest continuous-soak semantics into QPR-06 |
| #411 | MPR-CLOSE-01 installed product truth / source-release drift | diverged | +19 / -1853 | DO_NOT_MERGE_DIRECTLY; harvest verification ideas into QPR-01 |
| #467 | MPR-SYS-03 provider entitlement/deadline admission | diverged | +54 / -1507 | Most provider-governance concepts already landed elsewhere; compare unique tests only |
| #565 | ROADMAP PR-020+021 pinned offline research owner | diverged | +1 / -5 | Fresh enough to review/rebase separately; not a substitute for prequalification data-plane work |

Rule: stale branch code is not rebased mechanically. Extract unique tests/contracts/ideas, implement against current canonical owners, then close old PR as superseded.
