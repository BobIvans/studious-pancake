# CODEX START HERE — R-01 then R-02
Branch planned for R&D documentation: docs/r01-r02-capital-readers-rnd-2026-10-08
Target for actual code PRs: main only.

## Your first action is R-01 VERIFY, NOT ANOTHER MEGAMERGE
Read README.md, MASTER_CONTEXT.md, R01_BRANCH_RECONCILIATION.md, then fetch live refs and #579/#580/#581/#582. Recheck ancestry and compare main against old GPR/UXE/QPR refs. Confirm 0-ahead old branches, classify QPR one unique commit, verify RECONCILIATION_RECEIPT.json provenance and main QPR/GPR/DynamicUniverse source owners. If R-01 already PASS, publish minimal verification receipt / code review summary and move on without cherry-picking random commits. If not PASS, fix R-01 in separate narrow PR first. Never rewrite main history or force-push.

## R-02 implementation
Read PROVIDER_SELECTION.md, PROVIDER_CATALOG.json, R02_ARCHITECTURE.md, R02_TESTS_AND_EXIT_GATES.md and existing code owners. Deliver **actual read-only** live capital adapter PRs:

1. Jupiter Lend FlashloanAdmin + token reserve reader + NEW narrowly reviewed jupiter_lend FlashCapitalGraph compatibility; zero-position-init preferred, fee/capacity on-chain proof.
2. Kamino official klend reserve reader, verify flash vs obligation path, no initObligation; fee and cap on-chain.
3. NAVI official Sui SDK getAllFlashLoanAssets + shared pool state/checkpoint + exact decimal normalization.
4. P0 official SDK bank/account reader; preexisting account only, no account creation, strict bank tag.
5. Optional separate DeepBook follow-up; do not block core acceptance for it.

All adapters must use current quota/admission/provenance owners, produce exact atom/fee evidence and typed negatives, replay deterministically, and preserve broad Dynamic Universe. Return no edge when state/access/source version unknown; never fake zero fee or current capacity. Do not create a second graph, transaction engine, market resolver or authority.

## Safety and handoff
sign_enabled=false; send_enabled=false; no keys, no new token account, no margin account, no real flashloan and no spending. Do not change any existing release/paper/production gate. Need actual R-02 verified external captures; inability to connect is explicit BLOCKED, not PASS.

Publish each scoped code PR on main with exact branch/HEAD, changed paths, code-owner matrix, tests and source pins, pass/fail, wallet setup-cost proof and live negative receipts. **Do not merge without explicit user instruction.**

## Full verification
Run focused existing capital graph/lending/Jupiter/Kamino/QPR/DIN/Sui tests, then python scripts/verify_repo.py; report real run, not #579/#582 historical test totals.


## Offline documentation guarantee and additional provider options (2026-10-08 update)

**READ LOCALLY FIRST**: `offline/README.md`, `offline/SOURCE_LEDGER.json`, `offline/CONTRACT_FACTS.json`, all three `offline/*_PROTOCOL_DOSSIERS.md`, `offline/PROVIDER_ECONOMICS_AND_SELECTOR.md` and `offline/GAPS_AND_STOP_CONDITIONS.md`. Run `python docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/verify_bundle.py`. This script uses only standard Python and makes no web requests.

This package now catalogs **27 distinct IDs**, but not 27 independent qualified flash lenders: some are pool-specific flash-swaps, one is an aggregator, one is a standard, one is rent-only, and others are unverified/blocked. Strong options newly found: Euler EVault, Uniswap V2 flash swaps, PancakeSwap V3, Silo flash loans, Balancer V2, Instadapp FLA routing (not independent). Separate source review required for each later implementation.

The OFFLINE materials are an original primary-source synthesis, not complete mirrored SDK and IDL files. If code cannot be implemented from existing repo decoders, cached verified SDK version and local dossiers, stop that provider with MISSING_PINNED_ABI or NETWORK_STATE_UNAVAILABLE; **never fabricate ABI layouts, live capacities, fee quotes or 'account-free' status**.

**Only R-02 four readers first**: Jupiter, Kamino, NAVI and pre-existing-account-only P0. The expanded catalog is an **R-07 optional provider selection backlog**, not scope creep before R-02 verified snapshots and exact simulation. New provider contracts/reusable EVM callback deployment must not be attempted during R-02.

For Sui, JSON-RPC retired in 2026; use existing DIN-02 governed gRPC/GraphQL readers. Kamino flash has an official separately pinned instruction flow with no obligation account in flash instruction accounts, but fees may apply. Jupiter docs no position initialization; Solana ATA/network costs still apply. Scallop `ScallopClient` may sign/send by default; read via `ScallopQuery` only. Save/Solend historical flash interface remains unqualified.

No signing, sending, account creation, live flash borrowing, or production deployment in any R-02 document/test.
