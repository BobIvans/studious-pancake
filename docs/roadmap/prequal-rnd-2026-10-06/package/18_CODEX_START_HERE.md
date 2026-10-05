# CODEX START HERE — PRE-QUALIFICATION CAMPAIGN

Base against current `main` commit **ac6297e3f174d073c524099f599490edfe30f7b1** or a newer descendant. Never reset main to this SHA if it has advanced.

## Goal
Implement the smallest safe sequence that starts a real read-only qualification/problem-testing campaign without duplicating stale PR architecture.

## Read first
1. `00_README_START_HERE_RU.md`
2. `03_FASTEST_QUALIFICATION_PATH_RU.md`
3. `06_RUNTIME_RELEASE_AUTHORITY_UNIFICATION_RU.md`
4. `07_RPC_QUORUM_AND_NATIVE_CAPTURE_RU.md`
5. `11_SOURCE_PLUGIN_ARCHITECTURE_RU.md`
6. `data/acceptance_gates.json`
7. `data/pr_plan.json`
8. `16_OPEN_PR_REUSE_SUPERSEDE_RU.md`

## First implementation target
Start **QPR-01**, then **QPR-02**. Do not combine with full persistence migration or live execution.

## Required constraints
- sender/signer/submission remain unreachable;
- source/catalog/indexed data cannot become exact execution edge;
- no secrets committed;
- every external request uses governed transport + quota + redacted evidence;
- replay performs zero network I/O;
- a single RPC source can collect but cannot qualify;
- preserve historical source generations; never rewrite evidence in place;
- stale PRs are references only.

## Completion output per PR
- code + focused tests;
- updated problem register disposition;
- machine-readable receipt with current main/base/head SHA;
- exact remaining blockers;
- no production-ready claim unless `PRODUCTION_PROMOTION_V1` passes.
