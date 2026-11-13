# CODEX START HERE — R-02 live capital readers (R-01 already complete)

**Current handoff date:** 2026-11-13  
**Target:** current \`main\` only. Fetch the exact latest SHA before every implementation PR.

## Do not restart completed work
- R-01 reconciliation is complete and recorded in PR [#584](https://github.com/BobIvans/studious-pancake/pull/584). The QPR-01 authority/fix work is already in the reconciled mainline per the current project handoff. Verify current owner hashes; do not repeat R-01, re-merge legacy branches or reconstruct QPR/GPR owners.
- PR [#585](https://github.com/BobIvans/studious-pancake/pull/585) records the real R-02 prerequisite capture and its negative/blocker evidence.
- PR [#586](https://github.com/BobIvans/studious-pancake/pull/586) is now merged into main. Its local SDK/source snapshots and focused R-02/R-03 plan are the baseline; do not recreate them.
- Solana market-data P0 is a separate track already documented under \`docs/roadmap/p0-offline-execution-master-2026-11-13/\` and \`docs/integrations/offline/solana-p0/\` (PRs #588/#589).

## Current R-02 truth
The #585 observation is partial, not capital qualification: Jupiter FlashloanAdmin and Jupiter/Kamino program accounts were read at finalized slot 454401538; the admin reported enabled/zero fee, but no TokenReserve/vault/effective borrow capacity was proved. Kamino executable program presence did not prove current reserve/fee/capacity. Sui checkpoint 331514367 was obtained, but no NAVI pool state was read. No existing P0 user authority/account was supplied. Result: zero qualified capital edges; all 27 catalog candidates remain disabled. No account was created, no transaction signed or sent.

## Stage 0 — offline-first preflight
1. Read \`MASTER_CONTEXT.md\`, \`R02_UNBLOCK_MATRIX.md\`, \`R02_ACCEPTANCE.md\`, \`R03_SHADOW_BUILDERS.md\`, \`LICENSE_AND_PROVENANCE.md\`, and the entire \`offline/README.md\`.
2. Read the merged R-02 SDK kit at \`docs/roadmap/r02-capacity-recovery-2026-10-08/\`, including \`offline/vendor/\`.
3. Run, from repository root:
   \`\`\`bash
   python docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/verify_bundle.py
   python docs/roadmap/r02-capacity-recovery-2026-10-08/offline/verify_offline.py
   python -m unittest discover -s docs/roadmap/r02-capacity-recovery-2026-10-08/offline -p "test_*.py"
   \`\`\`
4. Re-fetch main, open PRs and current code. Do not treat historical SHAs, docs snapshots or old test totals as current state.

## Stage 1 — R-02 implementation (small independent code PRs, base=current main)
- **R02-CAP-A Jupiter Lend:** use the pinned 192-byte IDL-derived TokenReserve layout; derive the reviewed PDA, read reserve + mint + token vault + applicable flash-borrow limits at one rooted/finalized slot; prove effective borrow capacity, fee, rounding, token program and mint binding. An enabled admin and fee=0 are not capacity proof.
- **R02-CAP-B Kamino:** use the pinned klend-sdk 13.0.2 generated account layouts. Decode full Reserve/LendingMarket, last update, status, supply vault, mint, token program, flashLoanFeeSf, caps and effective available liquidity. Do not mistake the 280-byte prefix probe for a full decoder.
- **R02-CAP-C NAVI:** use pinned modular @naviprotocol/lending 2.0.12 source. Treat \`getAllFlashLoanAssets\` API as discovery only; read deployed package/config/pool/shared-object state through governed Sui gRPC/GraphQL at a real checkpoint. Record v1/v2 PTB version and exact coinType/decimals.
- **R02-CAP-D Project 0:** start with wallet-free bank discovery. Existing user account is optional and only read if a public authority/account is supplied. Never initialize a Marginfi/P0 account.

Reuse current QPR/DIN source governance, rooted RPC quorum, quota and replay; AssetResolver; FlashCapitalGraph; existing lender ports; PR118 sizing and exact evidence. No new graph, transaction kernel, RPC authority or signer.

## Stage 2 — R-03 may proceed in parallel only offline/unsigned
Read \`R03_SHADOW_BUILDERS.md\`. Freeze shared contracts first. Build deterministic source-pinned unsigned Solana instructions and Sui PTB plans. Report build conformance separately from lender-capacity proof. A builder cannot create a positive capital edge or mark a route execution-ready while its R-02 provider state is blocked.

## Safety / acceptance
All 27 research candidates stay disabled until individually qualified. Unknown fee, cap, reserve, mint, owner, package, decimals, or setup cost means typed BLOCKED/negative evidence, not zero. No account creation, ATA creation, position initialization, signing, sending, borrowing, spending, deployment or production promotion. R-02 PASS requires resource-level, current, rooted/independent and replayable capacity evidence per provider. Each code PR targets current \`main\`, is review-only and includes exact source pins, report, tests, negative receipts, and actual test totals. No automatic merge.
