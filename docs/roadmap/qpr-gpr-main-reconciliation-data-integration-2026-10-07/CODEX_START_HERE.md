# CODEX_START_HERE — RCN-00 Main Reconciliation → DIN-00 Source Admission → Real Data

**Repository:** `BobIvans/studious-pancake`  
**Roadmap published on branch:** `docs/qpr-gpr-reconcile-data-integration-2026-10-07`  
**Target:** independent implementation PRs **to `main` only**, never to an intermediate QPR/GPR branch.  
**Starting audit snapshot:** 2026-10-07. Revalidate all moving Git refs and public API contracts before coding.

## Explicit assignment

You are continuing existing work, **not** building a fresh arbitrage app and **not** reproducing all merged PRs as new code.

1. **Read completely** `MASTER_CONTEXT.md`, `BRANCH_RECONCILIATION.md`, `DATA_INTEGRATION_PLAN.md`, `SOURCE_MATRIX.md`, `PROVIDER_CATALOG.json`, `IMPLEMENTATION_ROADMAP.md`, `QUALITY_GATES.md` in this folder.
2. Audit current remote `main`, live PR targets/history and source branch `rnd/gpr-parallel-radar-2026-10-06` as described in the runbook. Existing PR status is not sufficient. Compare actual trees, commits and tests.
3. **First implement only RCN-00:** recover the stacked QPR-01/02/03 + GPR-01/02/03 owners and UXE docs into a **new integration branch based on latest `main`**; preserve main PR #566 provider truth, #576 dynamic resolver/universe/relation/correlation/FlashCapitalGraph, #577 storage admission and all later commits. No code-copy reimplementation when a tested original already exists.
4. Resolve any conflicts **semantically**, especially `src/runtime/runtime_entrypoint.py`, `src/market/native_cpmm_capture.py`, `src/paper_shadow/native_cpmm_qualification.py` and three dependency lock files. Don't overwrite newer safety behavior with old branch versions. Record before/after proofs and negative tests.
5. Run focused tests for both original QPR/GPR and the new main Dynamic Universe plus full required CI. If blocked (credentials, CI, remote authentication, merge conflict), retain a precise blocker receipt and create/push the maximum safe partial PR; never report `merged` without re-reading GitHub.
6. Create/push a **real PR to `main`** titled `RCN-00: restore QPR/GPR evidence owners onto main without losing Dynamic Universe`. Include a machine-readable `RECONCILIATION_RECEIPT.json` with source SHA, target SHA, merge-base, owner inventory, six-path conflict decisions, test summaries, negatives and exact remote PR URL. **Do not merge without user approval.**
7. After RCN-00's integrated head is genuinely validated, continue with the **smallest** DIN-00 provider-governance seam, then start DIN-01 Solana and DIN-02 Sui **in parallel isolated branches** (each targets `main` after reconciliation is merged; or explicitly report dependency if not). Use **real bounded captures**, not speculative bulk PRs.
8. Implement later DIN-03/04 quote/build previews, DIN-05 financing/exact verification, DIN-06 correlation scheduling and DIN-07 24h paper evidence only according to their gates; do not treat an incomplete real-data campaign as production proof.

## Source of truth and precise boundaries

1. Repository's **current `main`** code and production safety policy, especially PR #566, PR #576, PR #577.
2. Original merged QPR/GPR implementation and evidence **on the radar source branch** with its own tested owner contracts, not README claims.
3. Original UXE R&D specs PR #575, which contains **docs only**, not an implemented multi-router system.
4. This folder is a reconciliation + data onboarding assignment; it never overrides runtime authority/security owners.

Always reuse rather than rewrite:
- QPR `ProviderProfile`, `SourceDossier`, `SourceIntakePlane`, independent rooted RPC and raw/negative journal.
- GPR `AssetRegistry`, `ResearchEconomicGraph`, `VerificationQueue`, Solana and Sui shadow owners.
- Current main asset resolver, Dynamic Universe, relation generators, correlation ledger, FlashCapitalGraph, `MarketObservationV2`, graph/paper/PR118 and AGG-02 persistence.
- Real operator/underlying-liquidity correlation. An endpoint, hostname or key is **not** an independent RPC provider.

## Engineering priorities after reconciliation

1. **Cheap discovery FIRST:** DEX Screener batch, GeckoTerminal, Raydium, Meteora; Sui DeepBook, Cetus, Aftermath. Provenance-tag exact mint/Move type and pool identity; no ticker-only binding.
2. **Narrow verification NEXT:** bounded real 0x/Jupiter/Titan and Sui Aftermath/Cetus/DeepBook route preview; independent RPC/checkpoint only for shortlisted candidates; OpenOcean/Jupiter/Titan correlation must not be double-counted.
3. **Economic paper evidence:** include all venue/transfer/flash/gas/rent/tip costs, PR118 sizing and simulation failures; show actual read receipts and deterministic replay.
4. **Only later** expand to optional sources, Slumlord rent, TON read-only and additional UXE work as evidence warrants. Current scopes prohibit live capital.

Provider matrix is a **backlog**, not a switch to bulk-enable 37 URLs. Unknown quotas, keyless access assumptions, historical token mints, unsupported Token-2022 or Sui JSON-RPC calls must fail closed until pinned.

## Absolutely prohibited in this assignment

- `sign_enabled=true`, live wallet signing, sending/broadcast, Jito bundle submission, or borrowing real capital.
- Committing API keys, private keys, seed phrases, user-specific wallet identifiers or entire credentialed URL query strings.
- Reducing independent RPC quorum, bypassing QPR hard boundaries, treating indexer/quote evidence as executable transaction proof.
- Re-adding Odos to runtime despite PR #566; bypassing Pyth Hermes Bearer auth; widening global payload bounds just to admit oversized source.
- Force-pushing `main`, merging behind the user's back, claiming a remote merge when only local commits exist.
- Asking to connect every external provider before the minimal authentic source campaign can run.

## Output format after each implementation PR

**Russian summary:** GitHub PR link, exact base/head SHA, owner paths restored/changed, measured real successes and negatives, test/CI statuses (no fabricated PASS), source free plan and provider limits confirmed, preserved safety/credential boundaries, remaining blockers, and the next smallest DIN phase. If you cannot publish remotely, say so and give exact local SHA and remedy. No vague 90%-done claims.

**First action:** inspect branches, compare code, produce RCN-00 conflict resolution and actual tests. Do NOT start DIN-03 quote races or another broad research document while QPR is absent from `main`.
