# GLM-5.3-Flash operating guide for this repository

Purpose: make long-horizon GLM coding capacity useful for multi-agent project execution while protecting repository correctness.

## Model and plan notes (checked 2026-11-13)

- Z.AI's official GLM-5.3-Flash announcement says the model is available to GLM Coding Plan users and offers 3x the usable quota of GLM-5.3. Official announcement: https://z.ai/blog/glm-5.3-flash
- Official ZCode docs describe long-horizon coding workflows and stable long-context handling: https://zcode.z.ai/en/docs/welcome
- ZCode's official changelog describes dynamic workflows that use one script to coordinate multiple subagents: https://zcode.z.ai/en/changelog
- Z.AI describes a points-based Coding Plan quota, separate input/cached-input/output consumption, and reduced off-peak point use. Details can change: https://z.ai/blog/glm-5.3 and https://zcode.z.ai/en/docs/usage-stats

Do not assume a user's stated "500M coding tokens" is a single context window, a guaranteed concurrent-agent count, or an unlimited number of tool calls. The exact entitlement belongs to the signed-in account's live usage page. The repository workflow should be efficient even with smaller quotas.

## Recommended use of a large token/tool budget

1. Spend a small first pass on repo discovery and the machine-readable workstream inventory; do not ingest every source file blindly.
2. Use PROJECT_KNOWLEDGE_BASE_MAP.md to select the canonical owners and retrieve only relevant call graphs/tests.
3. Launch agents by independent workstream. Prefer four-to-eight concurrent focused workers only if the actual coding harness permits and RPC/provider quotas are respected; otherwise queue them without changing the dependency graph.
4. Reserve one strong lead agent as integrator/reviewer. Workers must not all edit shared files or merge each other's PRs.
5. Assign a bounded output contract to each worker: findings, exact owner files, source pins, changed files, tests, receipt and PR link.
6. Use tool calls for real work (code, tests, source retrieval, replay, diffs), not repeated summaries or huge prompts.
7. Cache stable project context in these repo docs and keep task prompts short. Re-read current main and linked files when the branch changes.
8. Allocate more effort to independent verification, negative tests, failure injection and exact-source comparison than to generating more speculative architecture.

## Multi-agent coordination pattern

- Lead: baseline + owner map + interface contract + status board + integration queue.
- Worker agents: one workstream, isolated worktree, declared file ownership, one reviewable PR.
- Research agents: official source acquisition, protocol/venue/strategy matrix, no code merge unless assigned.
- Test/review agents: independent diff review, offline replay, dependency/security/package gates.
- Do not let two agents both own DynamicUniverse, FlashCapitalGraph, source intake, route solver, exact simulation or runtime composition.

## Token-budget truth

A large usage allowance is valuable, but it does not remove:
- source-license obligations;
- API/RPC quotas, provider throttling or chain-state latency;
- compile/test/CI time;
- code review and conflict resolution;
- cryptographic/deployment proof;
- market risk, latency or transaction economics.

Do not equate model confidence, model tokens, long context, a successful web query or a green unit test with live qualification. The evidence gates in this repository remain authoritative.
