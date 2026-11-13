# Multi-agent execution plan — whole project, parallel workstreams

**Date:** 2026-11-13  
**Primary coding agent:** GLM-5.3-Flash (or current configured GLM agent)  
**Coordinator:** one lead agent with GitHub/terminal access  
**Repository baseline:** fetch latest main; never rely on the historical SHA in these docs.

## 1. Why the workflow is being broadened

The previous short trigger focused on R-02 and allowed R-03 offline work in parallel. It did NOT instruct an agent to execute the whole repository strategy concurrently. This plan broadens the mission to the full project while preserving small PR ownership and hard dependencies.

The large token budget should be used for broad codebase understanding, primary-source research, independent implementation, test coverage and parallel agent coordination—not for putting the entire repository into one prompt or making one giant PR.

## 2. Lead agent / coordinator responsibilities

The lead must first:
1. Fetch current main, record SHA, working tree, current open PRs, CI state, runtime capability manifests and all offline dossier verifier results.
2. Build/refresh an IMPLEMENTATION_STATUS.json or equivalent machine-readable workstream board with one row per deliverable.
3. Create an ownership matrix: canonical owner path, interfaces, allowed files per worker, dependencies, PR/branch, tests and blocker.
4. Freeze a small shared contract if agents need to work against the same DTO/evidence schema.
5. Launch independent agents in separate worktrees and collect their findings/PRs.
6. Review diffs for duplicated owners, API/doc drift, safety-gate changes, test gaps and source license problems.
7. Keep a single merge queue; only merge after required review and exact checks pass.
8. Produce a final integration report with implemented/blocked/unqualified distinctions. Never convert an agent's claim into PASS without evidence.

## 3. Parallel launch matrix

Launch these workstreams concurrently when resources/agent tooling permit. If a lane needs a shared interface not yet frozen, it performs read-only audit, contract proposal and fixture work first; it does not edit the shared owner until the coordinator approves the interface.

| Lane | Agent assignment | May implement now | Must wait for |
|---|---|---|---|
| A1 | P0-1 Solana indexed intake → Dynamic Universe | bounded source intake, identity, replay, coverage | shared identity/evidence contract; no promotion |
| A2 | P0-2 Jupiter V2 + 0x quotes | existing quote-owner migration, exact comparison | quote contract pin; no build/send |
| A3 | P0-3 Raydium CLMM + Meteora DLMM | offline decoders/math/fixtures | current source/deployment pins; Orca legal approval |
| B1 | R02-CAP-A Jupiter | read-only reserve/capacity reader | rooted slot/quorum & current SDK/IDL |
| B2 | R02-CAP-B Kamino | full reserve/fee/capacity reader | full pinned SDK layout + deployment evidence |
| B3 | R02-CAP-C NAVI | read-only Sui package/pool reader | governed GraphQL/gRPC checkpoint and object bindings |
| B4 | R02-CAP-D Project 0 | wallet-free bank reader | optional existing public account for user eligibility only |
| C0 | R03-00 financing/unsigned plan contract | contract proposal, offline validation | coordinator interface freeze before shared code |
| C1-C4 | R03 provider builders | SDK source audit, offline instructions/PTB fixtures | R03-00 freeze; R02 proof before live-capital association |
| D1 | Dynamic Universe / graph / strategy audit | owner map, generators, search boundaries, offline tests | no new graph/solver owner |
| D2 | TON / Sui / EVM source research | current-source dossier, deployment/atomicity comparison | exact chain proof before executable promotion |
| D3 | CEX / oracle / reference feeds | source contract dossiers and replay adapters | classification and quota owner; SIGNAL_ONLY by default |
| E1 | R04 route/lender/amount selector | design and tests against frozen contracts | relevant P0 exact quotes + R02 capacity + R03 build |
| E2 | R05 exact transaction/PTB simulation | simulation-owner audit and negative tests | R04 candidates + provider-specific evidence |
| E3 | R06 paper campaign | readiness audit and report improvements | QPR/campaign PASS + R05 exact simulation |
| F1 | R07 provider expansion | rank 27 candidates, pin docs, identify gaps | one provider per PR; qualification gates |
| G1 | Runtime composition / boot path | dependency map, integration design, contract tests | P0/R02/R03 owner readiness and capability review |
| G2 | Platform / CI / reproducibility | WSL/Windows audit, bundle verifiers, test gates | preserve POSIX and capability behavior |
| H1 | Knowledge base / documentation | source pin refresh, owner docs, machine status ledger | verify official current versions and licenses |

### Suggested execution waves

- Wave 0 (start immediately): coordinator baseline; all offline verifiers; P0-1/2/3 code audits; R02-A/B/C/D audits; R03-00 contract proposal; D1 strategy map; D2/D3 source research; G2 platform tests. All can run at once in isolated worktrees.
- Wave 1 (after interface freeze): parallel P0 implementations, parallel R02 reader code, parallel R03 offline builder/fixture branches, strategy and stream experiments.
- Wave 2 (when per-provider evidence exists): R04 for each supported chain/provider combination; do not wait for every research asset or every lender if a qualified subset is sufficient.
- Wave 3: R05 full simulation per supported path, then R06 paper qualification only when campaign readiness passes.
- Wave 4: R07 incremental provider integrations and future strategy promotion. Research/dossier work may continue in parallel through every wave.

"Run all at once" means parallelize independent work packages, not merge every branch simultaneously or bypass the gates above.

## 4. Worktree and file-collision protocol

Each worker:
- starts from latest origin/main and records exact SHA;
- has one named task ID and one Git worktree/branch;
- owns a declared file set and may not edit another lane's owner;
- may read any repo file and official docs but must pin source facts;
- submits one focused review-only PR to main; no force push or mass merge;
- includes tests, fixtures, verifier commands, source pins, exact results and blockers.

Suggested branch naming:
- agent/p0-1-solana-intake
- agent/p0-2-jupiter-0x
- agent/p0-3-direct-state
- agent/r02-cap-a-jupiter
- agent/r02-cap-b-kamino
- agent/r02-cap-c-navi
- agent/r02-cap-d-project0
- agent/r03-00-contracts
- agent/r04-route-selector
- agent/platform-repro

Do not have multiple agents write the same src/resources/*.json, src/qualification_campaign/, FlashCapitalGraph, UnsignedExecutionPlan, runtime composition root or shared model file concurrently. Propose one owner PR, then rebase dependent worktrees.

## 5. Research protocol for internet-enabled agents

For every external dependency:
1. Read the checked-in dossier first.
2. Search the official documentation and source repository; avoid blogs/aggregators for ABI semantics when primary source exists.
3. Record canonical URL, retrieval time, API/SDK version, commit/tag, blob SHA, license, exact methods/account fields, units/decimals, fee rounding, max/cap semantics, rate limits/auth and failure behavior.
4. Compare to current chain program/contract/package deployment and current network state.
5. Add a new versioned dossier rather than overwriting historical source pins.
6. Retain only legally distributable source; otherwise create an original factual summary with source references and license blocker.
7. Mark any unavailable detail MISSING_PIN, MISSING_DEPLOYED_ABI, MISSING_CHAIN_STATE or another typed BLOCKED reason.

Internet research does not qualify a live provider. A browser result, HTTP 200, source-code pin, API token, token list or TVL figure is not proof of current executable market depth or borrowing capacity.

## 6. Global integration gates

- Discovery → canonical identity → exact market state → quote → route → verified capital → unsigned build → exact simulation → paper receipt are distinct states.
- For each route, re-quote each candidate input amount. Never extrapolate one quote across sizes.
- Resource identity prevents double-counting of a lender reserve, shared AMM pool, wrapper route or router aggregator.
- Local atomicity is chain-specific. Cross-chain, CEX and bridge opportunities stay research/signal-only unless their exact settlement atomicity is proved.
- ML and correlations can rank or alert; they cannot bypass deterministic constraints or qualify an unverified route.
- Live remains hard-denied; no signer/sender code is added by these tasks.

## 7. Agent report schema

Every worker returns:
- task ID, branch, base SHA, head SHA and PR URL;
- status per deliverable (IN_MAIN_VERIFIED, IMPLEMENTED_UNQUALIFIED, LIVE_READ_PROVEN, RPC_EXACT, BUILT_OFFLINE_UNQUALIFIED, SIMULATION_PASS, PAPER_QUALIFIED, BLOCKED, etc.);
- current canonical owners reused and files changed;
- external source pins/licensing;
- test commands, exact pass/fail/skip counts and platform;
- replay command and receipt hashes;
- dependency/overlap notes;
- unresolved blockers and recommended next task.

The lead updates the central status board after each PR. "Done" without an artifact and test/evidence is not an accepted status.
