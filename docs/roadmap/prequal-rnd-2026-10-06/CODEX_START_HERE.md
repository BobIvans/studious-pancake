# CODEX START HERE — PRE-QUALIFICATION CAMPAIGN

This repository branch contains the complete R&D ZIP at:
`docs/roadmap/prequal-rnd-2026-10-06/STUDIOUS_PANCAKE_PREQUAL_RND_2026-10-06.zip`.

## Step 0 — materialize the pack

Unpack the archive **inside this branch/worktree** under:
`docs/roadmap/prequal-rnd-2026-10-06/package/`

Do not delete the original ZIP. Verify SHA-256 first using `docs/roadmap/prequal-rnd-2026-10-06/PACKAGE_SHA256.txt`.

Then read:
1. `package/00_README_START_HERE_RU.md`
2. `package/01_MASTER_CONTEXT_RU.md`
3. `package/03_FASTEST_QUALIFICATION_PATH_RU.md`
4. `package/06_RUNTIME_RELEASE_AUTHORITY_UNIFICATION_RU.md`
5. `package/07_RPC_QUORUM_AND_NATIVE_CAPTURE_RU.md`
6. `package/11_SOURCE_PLUGIN_ARCHITECTURE_RU.md`
7. `package/data/acceptance_gates.json`
8. `package/data/pr_plan.json`
9. `package/16_OPEN_PR_REUSE_SUPERSEDE_RU.md`

## Goal

Execute the R&D plan against the **current main descendant**, not stale PR heads. Preserve all pack context in-repo.

Start **QPR-01**, then **QPR-02**. After they pass Campaign-Start Gate, continue the remaining QPR sequence in `package/17_PR_SEQUENCE_RU.md`. Do not collapse all work into one unsafe mega-diff merely for convenience.

## Required constraints

- sender/signer/submission remain unreachable;
- source/catalog/indexed data cannot become exact execution edge;
- no secrets committed;
- every external request uses governed transport + quota + redacted evidence;
- replay performs zero network I/O;
- a single RPC source can collect but cannot qualify;
- preserve historical source generations; never rewrite evidence in place;
- stale PRs are references only: reuse unique tests/contracts, do not merge stale branches wholesale;
- rebase/reconcile pack assumptions whenever current main has advanced.

## Completion output per QPR

- code + focused tests;
- updated problem-register disposition;
- machine-readable receipt with current base/head SHA;
- exact remaining blockers;
- no production-ready claim unless `PRODUCTION_PROMOTION_V1` passes.
