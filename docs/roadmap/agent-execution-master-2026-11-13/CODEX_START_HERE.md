# MASTER CODEX HANDOFF — whole-project parallel research and flashloan arbitrage execution

**Updated:** 2026-11-13  
**Repository:** https://github.com/BobIvans/studious-pancake  
**Target:** latest main; fetch and record exact SHA before every workstream.

## Copy-ready master trigger

Act as the lead engineering orchestrator for the entire existing Studious Pancake project, not only R-02. Read root AGENTS.md and CODEX_START_HERE.md, this master entrypoint, TASK_INDEX.md, MULTI_AGENT_EXECUTION_PLAN.md and PROJECT_KNOWLEDGE_BASE_MAP.md. Audit the latest main, open PRs, runtime capability truth, all canonical code owners, offline manifests, existing test coverage and source pins before editing.

R-01 is COMPLETE (#584). QPR-01 fixes and the QPR/GPR/DIN owners are already restored; do not recreate them or remerge historical branches. R-02 remains BLOCKED by the real negative evidence in #585: the recorded Jupiter/Kamino/Sui observations did not prove resource-level flash capacity, zero qualified edges were produced and 27 financing candidates remained disabled. The offline SDK references and R-03 handoff in #586 are merged. The Solana market-data master and Raydium/Meteora reference packs in #588/#589 are merged. The whole-project handoff was added by #591/#592 and expanded by #595. Current-main audit SHA is 86be458a87ed3f499cc32ff56426b2866c90422a (historical; fetch again before work). PR #593 P0-1 remains open on an older base and must be refreshed; #594 is superseded and should not be merged.

Do not execute only one lane sequentially. Refresh docs/roadmap/agent-execution-master-2026-11-13/PROJECT_STATUS.json and the ownership matrix, then launch all independent workstreams concurrently in isolated worktrees when the coding harness supports it: P0-1/2/3 market data; R02-CAP-A/B/C/D lender readers; R03-00 unsigned financing contracts and offline builder conformance; strategy/graph/correlation research; Sui/TON/EVM venue and capital research; CEX/oracle/reference feeds; platform/CI/replay reliability; supported runtime-composition integration audit; R13 multi-provider quote/build races; and R14 RentSponsorPlanner/Slumlord/provider sponsorship. See the specialist assignments in TASK_INDEX.md. Use MULTI_AGENT_EXECUTION_PLAN.md to avoid file collisions. One agent owns one narrow task/PR; no two agents edit the same canonical owner concurrently.

Keep the maximum research universe. A token need not itself be flash-borrowable if a verified settlement hub can fund the local atomic route. Preserve Solana, Sui, TON, EVM, long-tail tokens, LSTs, stablecoins, BTC wrappers, event/meme assets, RWA references, CEX/oracle signals and cross-chain research. Do not misclassify reference data or asynchronous cross-chain paths as exact local atomic liquidity.

Reuse existing AssetResolver, DynamicUniverse, ResearchEconomicGraph, UniversalArbitrageGraph, relation generators, CorrelationLedger, FlashCapitalGraph, PR118 nonlinear sizing, existing lender ports, AtomicMarginfiJupiterPlanner, instruction firewall, ExactSimulationFinalizer, QPR/DIN governance, unified lifecycle/capital authority and paper service. Never create a second graph, market resolver, quote schema, RPC authority, evidence journal, amount solver, transaction kernel, capital ledger, signer or sender.

Parallelize research, source verification, offline implementation, negative fixtures and independent data/capital readers immediately. Gate only dependent integrations: R04 route/lender/amount selection needs exact quotes + relevant R02 capacity + R03 unsigned conformance; R05 needs complete R04 candidates and current state; R06 needs QPR/campaign readiness PASS and R05; R07 adds one provider at a time after its own evidence gates. Research dossiers for later phases may proceed concurrently; provider activation may not.

Use internet access to verify current official contracts where needed. Record URLs, retrieval date, API/SDK version, source commit/blob SHA, license, schemas/IDL/ABI/OpenAPI, units, decimals, fee rounding, quotas and error semantics in versioned local dossiers. Existing offline docs remain the first source of context. A web result, API key, source pin, HTTP 200, TVL or token list is not live capacity proof.

No secrets or private keys, account/ATA/position creation, signing, sending, borrowing, spending, receiver deployment or production promotion. Keep live hard-denied and all unqualified providers disabled. Build only sender-free evidence. Produce small review-only PRs against current main with exact SHA, tests, offline replay, evidence hashes, blockers and PR links. Do not mass-merge. The lead reviews overlaps and gates before any merge.

## Required work products
1. Current-main baseline and IMPLEMENTATION_STATUS.json (or equivalent) with every major deliverable, owner, files/tests, external pin, status, dependency, blocker, PR and acceptance command.
2. Ownership/interface matrix and multi-agent worktree plan.
3. Focused PRs across all independent workstreams.
4. R04/R05/R06/R07 only as their dependencies become true.
5. Full repo verifier output, offline replay evidence and a project-wide integration report.

## Read order / maps
- PROJECT_STATUS.json — refreshed machine-readable inventory for 19 workstreams at the audit SHA; refresh it against current main and PRs before coding.
- MULTI_AGENT_EXECUTION_PLAN.md — launch matrix, worktree and dependency rules.
- PROJECT_KNOWLEDGE_BASE_MAP.md — current main code owners and docs.
- TASK_INDEX.md — all assignment texts.
- GLM_AGENT_OPERATING_GUIDE.md — efficient long-horizon/multi-agent usage.
- P0 market data: docs/roadmap/p0-offline-execution-master-2026-11-13/.
- R02/R03 capital: docs/roadmap/r02-capacity-recovery-2026-10-08/ and docs/roadmap/r01-r02-live-capital-readers-2026-10-08/.

## Offline verifiers
- python docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/verify_bundle.py
- python docs/roadmap/r02-capacity-recovery-2026-10-08/offline/verify_offline.py
- python docs/integrations/offline/solana-p0/verify_offline_bundle.py
- python scripts/verify_repo.py

Report exact pass/fail/skip counts and platform; never copy historical totals as current.
