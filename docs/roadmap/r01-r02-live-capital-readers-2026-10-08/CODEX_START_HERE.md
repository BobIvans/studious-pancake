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
