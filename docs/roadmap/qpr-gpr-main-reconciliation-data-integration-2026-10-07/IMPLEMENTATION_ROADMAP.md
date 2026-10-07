# IMPLEMENTATION_ROADMAP — small PRs, no duplicate implementation

**Execution rule:** RCN-00 is blocking. After the smallest stable source-governance seam, connect *real external data* immediately; do not implement the entire speculative UXE research universe before the first authenticated capture.

## Dependency graph

```text
RCN-00 restore QPR/GPR to latest main + preserve #576/#577
             │
             ▼
DIN-00 source adapter contracts + shared quotas + frozen evidence profile
          ┌──┴─────────────┐
          ▼                ▼
DIN-01 Solana data    DIN-02 Sui data
          │                │
          ▼                ▼
DIN-03 Solana quotes  DIN-04 Sui quotes/PTBs
          └───┬────────────┘
              ▼
DIN-05 verified flash-capital + exact state + sim interfaces
              ▼
DIN-06 event-driven graph + correlation/cost-focused campaign scheduler
              ▼
DIN-07 24h repeated PAPER qualification + report
              ▼
LATER separate production security/release/72h soak gate
```

Parallel isolated worktrees are allowed for DIN-01 and DIN-02 after shared contracts pass. DIN-03 and DIN-04 are independently parallel once their chain discovery adapters are stable. Provider SDK bridges may proceed in parallel with provenance/guard tests, but **no PR merges over a broken base**.

## RCN-00 — Restore stacked QPR/GPR to main (P0, blocking)

Implement `BRANCH_RECONCILIATION.md` exactly. Start a **new PR with base `main`**. Use `rnd/gpr-parallel-radar-2026-10-06` as stacked source branch rather than cherry-picking each merged sub-PR. Integrate QPR-01/02/03, GPR-01/02/03, UXE docs while preserving main Dynamic Universe, Pyth/Odos truth and storage pressure. Write a machine-readable conflict disposition receipt and prove all 14 restored/main owner files in same PR head. Work ends when tests/CI are green and remote PR actually exists — not when a local commit or `make_pr` stub was invoked. No automatic merge without explicit approval.

## DIN-00 — Provider Contracts / Catalog Admission (minimal P0 seam)

**Inputs:** restored QPR `ProviderProfile`, `SourceDossier`, `SourceIntakePlane`, `ProviderGovernance`, existing source catalog, `PROVIDER_CATALOG.json` (**non-executable inventory**).

**Code actions:**
- Audit current source registry and map to 37 catalog rows: `IMPLEMENTED_AND_VERIFIED`, `IMPLEMENTED_BUT_UNBOUND`, `EXISTING_STUB`, `PLANNED`, `RETIRED`, `UNKNOWN`. Never call all providers simply because a row exists.
- Implement chain-neutral outer `ResearchSourceAdapter`/normalized read envelope **only where existing QPR model cannot already express it**. Do not generalize Solana QPR candidate to disable its Solana checks.
- One shared per-operator + per-provider physical bucket with source-specific schema generation and quota generation; pluggable entitlement (RPM/RPS/credits), 429/Retry-After, max concurrency, bytes, strict host/auth allowlists.
- Add a fixture-driven contract test template for one source, including 200/401/403/404/429/5xx, invalid JSON, gzip, payload-too-large, schema drift, TTL and no-provider-key.
- Export onboarding status + credential names (NOT values) + exact reason why profile cannot run.

**Done when:** exactly one documented source can be admitted with a real profile and one blocked source emits zero physical wire calls; all old safety owners unchanged. **Then do DIN-01/DIN-02 rather than a giant abstraction PR.**

## DIN-01 — Solana broad free radar + identities (first external capture)

**Sources (bounded first wave):** DEX Screener batched tokens/pairs, GeckoTerminal, Raydium v3, Meteora DLMM; Manifest separate book lane. Existing GPR-02 quote read profiles remain intact.

**Deliverables:** approved SourceDossiers, tested converters, per-source quota/admission fixtures, host/TLS/auth policy, `asset/pool/venue/representation` normalization into existing Dynamic Universe and ResearchEconomicGraph. Startup mint program/decimals/owner proof for shortlisted signals. Reuse QPR raw+negative evidence; no guessed mints.

**First live smoke:** a small multi-source bounded capture retaining actual HTTP and raw hashes; identify duplicate pools across indexers and report accepted/rejected source rows. A successful indexed observation does not assert QPR exact pass.

**Expansion after passing:** Orca and Sanctum/LST NAV by explicit source version/policy review; don't tie every pool to quote HTTP calls.

## DIN-02 — Sui shadow free radar + gRPC/GraphQL (first external capture)

**Sources:** known DeepBook pool registry/book, targeted Cetus/Aftermath, Scallop rates. Reuse #573 negative fixtures: wrong DeepBook endpoint, oversized Aftermath, Scallop encoding/host, Cetus response shape. Full Move type + package identity.

**Deliverables:** direct/reader contracts and state boundary with checkpoint/object version/digest and independent operators. Legacy Sui JSON-RPC cannot be a required codepath. Repeat a small real diagnostic, report real exact quorum as `BLOCKED` until distinct legitimate providers and equal checkpoints exist.

**No unsafe porting:** Sui shadow result stays separate from Solana exact graph and may only generate cross-chain research/basis relations.

## DIN-03 — Solana alternate quotes + unsigned build preview

**Prioritized:** 0x, Jupiter and Titan; then OpenOcean/OKX/Rango only if required keys/allowlist and docs current. Race must be **bounded**, not unlimited parallel calls per token pair. Use tested quote amount/decimals/slippage/slot equality; record instruction/ALT/transaction body format and *every* losing quote with provider lineage. OpenOcean references Jupiter/Titan and cannot count as independent exact source.

**Output:** candidate IDs with negative/positive quote evidence, normalized costs, selected route preview; signature absent. Build+simulate feature flag remains read-only. Source/failure data goes into existing journal and correlation ledger.

## DIN-04 — Sui alternate quote/PTB preview

Start with Aftermath, Cetus and direct DeepBook; add 7K/FlowX/OKX/Rango behind plan/SDK checks. Reject returned routes with legacy JSON-RPC hidden dependencies; no unsigned PTB returned? typed unsupported evidence, not false quoted opportunity. Compare checkpoint/object, gas coins, PTB size, venue lineage.

## DIN-05 — Exact state, financing and simulation

Use QPR-02 independent rooted direct state on Solana and gRPC/GraphQL exact object verification on Sui. Add live (read-only) dynamic Project 0 bank eligibility/capacity/tags and Kamino reserve policies, Sui NAVI/DeepBook/Scallop loan size/cost; feed already-existing FlashCapitalGraph without implementing duplicate graph. Normalize all costs including compute/priority/Jito tip, DEX fee, Token-2022 transfer fee, rent and failures. **Do not implement Slumlord execution or any signer** in this wave; research account/rent planner later.

## DIN-06 — Event/heat scheduler + correlation evidence

Wire current main Dynamic Universe relation generators and correlation ledger to exact, typed QPR/GPR owner ports. Use event-driven heat + TTL and operator bucket, not hand-polling 160 static pairs at provider quote rates. Keep time alignment, freshness, shared pool fingerprint, independent confirmations and replay. Produce a source-efficiency report: useful deduped edges, qualified quote windows, exact rejected reasons per 100 physical calls.

## DIN-07 — 24h paper qualification (after capability gates)

Prepare immutable campaign manifest, reviewed source entitlements, credential-presence self-check, two or more distinct operator profiles where required. Run bounded repeated capture and report detailed outcomes; if true independent exact proof missing, remain `BLOCKED` and continue research only. Paper ledger must reconcile costs/flash/size and show zero realized live trading. No inference of profitability from aggregate indexed prices alone.

**Exit:** all relevant CI/focused tests green; `READ_ONLY_REAL_DATA_CAMPAIGN_V1` determined from current generation actual evidence; paper readiness report with remaining blockers; **signer/send/production remain disabled**.

## What NOT to implement before first sources

- A second whole-market graph, duplicate journals, token resolver or QPR promotion flag.
- Production submit/Jito bundle landing, wallet onboarding, unrestricted account creation or cross-chain live bridge.
- TON flash-arbitrage executor or old Odos runtime.
- Hundreds of additional source stubs with no real auth/host/negative evidence.
- Artificially green CI from suppressed tests or fake credentials.

## PR discipline

Every step: source SHA + base SHA, changed owner list, exact diffs, positive **and negative** tests, authentic API docs pins, provider operator quota, read-only effect boundary, no keys in commits, CI URLs, blockers and next smallest step. Use **`main` as base on every PR**, do not chain new merges into temporary branches unless clearly designated as review-only stacked PRs. If CI/merge authentication unavailable, mark work `IMPLEMENTED_LOCAL_NOT_PUBLISHED`; never claim merged.
