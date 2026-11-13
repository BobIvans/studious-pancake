# Repository-wide coding-agent instructions

1. Before coding, read CODEX_START_HERE.md at repository root, then docs/roadmap/agent-execution-master-2026-11-13/CODEX_START_HERE.md, MULTI_AGENT_EXECUTION_PLAN.md, PROJECT_KNOWLEDGE_BASE_MAP.md and TASK_INDEX.md.
2. Fetch current main and record the exact commit, worktree status, open PRs and CI. Never trust old handoff SHAs as current.
3. R-01 is complete (#584); QPR-01 fixes are already in the reconciled project state. Do not repeat R-01, remerge legacy branches or duplicate QPR/GPR/DIN owners.
4. Read the relevant checked-in offline technical dossiers before external browsing. Use internet access to verify current official source drift, not as a substitute for missing evidence. Pin exact version, commit, blob hash, license and retrieval time. Add a new immutable versioned dossier when a source changes.
5. Preserve the maximum research universe. Do not limit research assets to flash-borrowable assets; route financing is a separate graph dimension.
6. Reuse existing AssetResolver, DynamicUniverse, ResearchEconomicGraph/UniversalArbitrageGraph, relation generators, CorrelationLedger, FlashCapitalGraph, PR118 sizing, exact simulation, QPR/DIN governance, replay and paper lifecycle. Do not create duplicate owners.
7. Distinguish discovery, canonical identity, exact market state, quote, flash capacity, builder conformance, simulation, paper qualification and live authority. Unknown is not zero; fixtures are never live evidence.
8. Keep all providers disabled until their individual evidence gates pass. No secrets/private keys, account/ATA/position creation, signing, sending, borrowing, funds spending, deployments or production promotion.
9. Parallelize independent workstreams in separate worktrees/branches when supported. Each worker owns one narrow task and one reviewable PR. Do not allow concurrent edits to the same canonical owner; use the lead to freeze interfaces and resolve conflicts.
10. Each PR targets current main and includes exact changed paths, source pins, positive/negative tests, offline replay, actual test counts, evidence receipts, blockers and PR link.
11. Do not merge implementation PRs without explicit human approval. Documentation PRs may be merged only after conflict/diff/provenance checks and when the user has explicitly requested the merge.
