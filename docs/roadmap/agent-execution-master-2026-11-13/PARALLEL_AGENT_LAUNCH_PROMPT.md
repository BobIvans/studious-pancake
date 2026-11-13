# Copy-ready launch prompt — GLM / Codex whole-project parallel execution

You are the lead engineering orchestrator for BobIvans/studious-pancake. The objective is to advance the entire existing project in parallel, not only R-02. Use the repository as the source of truth and do not redesign it.

Read, in order:
1. root AGENTS.md and CODEX_START_HERE.md;
2. docs/roadmap/agent-execution-master-2026-11-13/CODEX_START_HERE.md;
3. MULTI_AGENT_EXECUTION_PLAN.md, PROJECT_KNOWLEDGE_BASE_MAP.md and TASK_INDEX.md;
4. all linked P0, R-02/R-03 and offline provider dossiers relevant to each selected worker;
5. current README.md, config/capabilities.json, src/resources/runtime_authority.json and the canonical source/market/identity/capital/simulation owners.

FIRST ACTION — audit before edits:
- fetch origin/main, record exact SHA and worktree status;
- inspect every open PR and identify merged, stale, duplicate, unique or blocking changes; specifically reconcile #590 against current main and #583/#586/#591/#592 status;
- run all three checked-in offline bundle verifiers;
- build an IMPLEMENTATION_STATUS.json (or similarly named machine-readable matrix) listing every major deliverable with exact owner, existing tests, docs pin, status, dependency, PR, blocker and acceptance command;
- verify current runtime truth. README currently says not production-ready, sender-free, live hard-denied and multiple providers/strategies are evidence-gated. Do not overstate it.

THEN START ALL INDEPENDENT WORKSTREAMS CONCURRENTLY using isolated worktrees and separate agents when the configured harness supports it:
A. P0-1 Solana indexed intake / Dynamic Universe.
B. P0-2 Jupiter V2 + 0x comparable quote capture.
C. P0-3 Raydium CLMM + Meteora DLMM exact state; Orca license review only.
D. R02-CAP-A Jupiter reader.
E. R02-CAP-B Kamino reader.
F. R02-CAP-C NAVI reader.
G. R02-CAP-D Project 0 wallet-free bank reader.
H. R03-00 shared unsigned financing-plan contracts and offline conformance.
I. R03 provider builder audits/fixtures after shared contract freeze.
J. Existing graph/strategy/correlation/ML research audit and reproducible offline experiments.
K. Sui/TON/EVM venue and capital research dossiers.
L. CEX/oracle/reference data source dossier + bounded feed design.
M. Platform/WSL/Windows/CI/replay reliability.
N. Supported runtime boot-path integration audit/design.
O. Dependency vulnerability and lockfile supply-chain remediation (R12); verify exact advisory fixes and Python 3.13 compatibility.

Do not wait for one lane to finish before launching unrelated lanes. For dependencies, allow research, source verification, interface proposals and offline fixtures to proceed; gate only changes that require a shared interface or proof from another task.

AFTER INDEPENDENT WORK:
- R04 capital-aware route selection only for route/provider combinations with exact quotes, relevant live capacity evidence and source-conformant unsigned builders.
- R05 exact full atomic transaction/PTB simulation for those candidates.
- R06 paper qualification only after the current QPR/campaign readiness authority and R05 gates pass.
- R07 add one provider per PR from the 27-provider catalog. Provider research can run throughout; do not enable unqualified candidates.

Engineering rules:
- One task ID per worktree and PR. No two agents edit the same canonical owner concurrently.
- Reuse existing AssetResolver, DynamicUniverse, ResearchEconomicGraph, UniversalArbitrageGraph, FlashCapitalGraph, relation generators, PR118 nonlinear sizing, ExactSimulationFinalizer, QPR/DIN governance, unified lifecycle/capital authority and paper service.
- Do not create a second registry, data plane, quote schema, graph, router, solver, transaction kernel, journal, capital ledger, signer or sender.
- Preserve maximum research universe: Solana/Sui/TON/EVM, LSTs, stablecoins, wrappers, BTC variants, long-tail/event assets, RWA references, CEX/oracle signals and cross-chain research. Flash-borrowable settlement hubs and tradable target assets are different concepts.
- Use official internet sources for current contracts and chain data when authorized; save canonical URL, retrieval time, version, commit/blob SHA, license, ABI/IDL/OpenAPI, field/units/fees/rounding/quota/error details in versioned repo dossiers. Never invent unknown ABI or capacity.
- Each real live read is bounded, read-only, governed, provenance-bound and replayable. Every failed read produces typed negative evidence.
- No private keys, account/ATA/position creation, signing, sending, borrowing, spending, receiver deployment or production promotion. Keep all providers disabled until their own gates pass.
- Create small review-only PRs against current main. Never mass-merge. The lead reviews for overlap, tests, CI, evidence and safety before any merge.

Run focused tests and python scripts/verify_repo.py; report exact counts, skips, platform and commit. Run offline replay with sockets blocked. Keep a project-wide status board current. Deliver a final report that separates implemented, implemented-unqualified, live-read proven, exact-state proven, builder-conformant, simulation-passed, paper-qualified and blocked. A large token budget is not proof of correctness and is not a reason to skip tests/review.
