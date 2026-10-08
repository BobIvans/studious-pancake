# CODEX START HERE — MATERIALIZED PRE-QUALIFICATION R&D

The complete 47-file R&D pack is already materialized in this repository branch under:

`docs/roadmap/prequal-rnd-2026-10-06/package/`

No download or unzip step is required.

## Read first

1. `package/18_CODEX_START_HERE.md`
2. `package/00_README_START_HERE_RU.md`
3. `package/01_MASTER_CONTEXT_RU.md`
4. `package/02_MASTER_PROBLEM_REGISTER_RU.md`
5. `package/03_FASTEST_QUALIFICATION_PATH_RU.md`
6. `package/06_RUNTIME_RELEASE_AUTHORITY_UNIFICATION_RU.md`
7. `package/07_RPC_QUORUM_AND_NATIVE_CAPTURE_RU.md`
8. `package/11_SOURCE_PLUGIN_ARCHITECTURE_RU.md`
9. `package/data/acceptance_gates.json`
10. `package/data/pr_plan.json`
11. `package/16_OPEN_PR_REUSE_SUPERSEDE_RU.md`

## Execution instruction

Work against the current `main` descendant. Do not reset main to the historical pack base SHA if main has advanced.

Execute the plan starting with **QPR-01**, then **QPR-02**. After Campaign-Start Gate passes, continue the remaining sequence in `package/17_PR_SEQUENCE_RU.md`.

Do not merge stale foundational PR branches wholesale. Harvest only unique tests/contracts/evidence semantics and rebuild against current canonical owners.

Keep sender, signer and transaction submission unreachable throughout pre-qualification work. Discovery/indexed data may select candidates but may never become exact executable truth without rooted/on-chain qualification evidence.

For every QPR, leave:
- code and focused tests;
- updated problem-register disposition;
- machine-readable receipt with current base/head SHA;
- exact remaining blockers;
- no production-ready claim unless `PRODUCTION_PROMOTION_V1` passes.
