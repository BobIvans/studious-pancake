# MASTER-00 — whole-project research-to-repository reconciliation

**Task class:** inventory / reconciliation / interface freeze / documentation-data only.  
**Base main:** `86be458a87ed3f499cc32ff56426b2866c90422a`.  
**Do not implement the whole project in MASTER-00.**

## Objectives
A. Reconcile archive candidate pairs and asset relationships with the live repository's canonical AssetResolver, research registry, Dynamic Universe and market identities.  
B. Reconcile source catalogs and direct venue families with the QPR/DIN source admission + market observation owners.  
C. Reconcile all strategy families with `src/strategy`, `src/strategy_evolution`, `src/strategies/stable_peg`, `src/liquidation`, `src/research_economic_graph`, `src/research/correlation_ledger` and economics owners.  
D. Reconcile all funding providers and flash mechanisms with `FlashCapitalGraph`, R-02 readers, R-03 builder contracts and chain-local settlement requirements.  
E. Refresh the PR/workstream dependency graph, including #590, #586, #583, #578, #593, #594, #595.  
F. Freeze the canonical identity/evidence envelope and ownership boundaries for parallel implementation.

## Required source material
Read the original user-shared source archive history and extracted technical material:
- Market Universe V3 (519 base market candidates; 162 curated high-value additions; historical 693-row dedup audit; 86 source profiles; 33 direct-venue rows; 17 lender profiles; 64 route templates; 43 anomaly classes; 18 detector extensions).
- Economic World Graph V4 (838 symbolic research pairs, 1,399 local 3–5 hop motifs, 2,998 nodes, 11,523 edges, 25 detector templates, 30 learning features).
- Flashloan Source Expansion V4.1 (98 symbolic relations, 19 cycle motifs, 23 source capability rows, nine lender-contract rows, 12 staged PRs).
- Four-Document Deep Market Atlas V5 (203 chain-local seeds, 39 route hypotheses, 11 non-swap hyperedges, 14 source capability rows, 12 DeepBook SDK pool IDs explicitly not live).
- Deep Pair Research V6 (175 pair rows delta to V5, 36 routes, 12 conditional protocol hyperedges, 33 documentation-ledger rows, 14 data-source rows; 154/175 V6 rows were classified as discovery hypotheses in the historical receipt).
- Maximum Direct Data Graph V3 and Direct Venue Audit (use as overlapping technical references; do not add their repeated registries a second time).
- `FROM_PRIOR_CHATS_STRATEGY_DELTA.md`, `DIRECT_DEX_IMPLEMENTATION_MATRIX.md`, `CHAIN_MARKETS_AND_ATOMIC_ROUTES_RU.md`, `FOUR_DOCUMENT_CROSSWALK.md`, `FREE_DATA_GOVERNANCE_RU.md`, and the pair/cluster notes.

These statistics describe the **historical archive contents as of 2026-10-08**, not current market listings, current liquidity, repo code coverage or profitable routes. The current source archive ZIP hashes and pair inventory recipe must be retained in the generated machine-readable handoff.

## Current-main registries to reconcile
- Asset identity: `src/assets/resolution/`, `src/resources/asset_mint_registry_pr117.json`, current GPR `ASSET_REGISTRY_V2.json` and provenance/aliases.
- Market discovery & source governance: `src/qualification_campaign/`, `src/provider_governance/`, `src/solana_parallel_radar/`, `src/gpr_sui_shadow/`, `src/market/source_catalog.py`, `src/resources/market_source_catalog.json`, `config/qualification/din00-source-status.json`.
- Dynamic markets / identities: `src/discovery/dynamic_universe/`, `src/research_economic_graph/`, `src/strategy/relation_generators/`, `src/research/correlation_ledger/`.
- Market/pool state: `src/providers/raydium_cpmm_native.py`, `src/market/native_cpmm_capture.py`, `src/direct_venue/`, `src/providers/orderbook/`, `src/multichain/`.
- Routes/strategy: `src/strategy/`, `src/strategies/stable_peg/`, `src/strategy_evolution/`, `src/liquidation/`, `src/economics/non_monotonic_sizing.py`.
- Capital/build/simulation: `src/economics/flash_capital_graph/`, `src/lending/`, `src/providers/marginfi/`, `src/execution/exact_simulation.py`, `src/planning/`, `src/paper_shadow/`.
- Authority/runtime: existing QPR/DIN source evidence, `config/capabilities.json`, `src/resources/runtime_authority.json`, supported composition root and README.

## Required outputs
1. `MASTER_PAIR_DELTA_SUMMARY.json`: raw archive row counts, normalized symbol-pair candidate groups, archive overlaps, exact unresolved collisions, source record references, explicit NOT_IDENTITY_MERGE labels. The pre-audit input corpus contained 1,897 pair records across V3 base, V3 high-value, V4, V5 and V6; casefold(chain+unordered pair symbols) produced 959 candidate clusters with 938 extra mentions, 551 clusters referenced by multiple archive generations. **This is not an address-level dedup and must not delete records.**
2. `STRATEGY_CROSSWALK.json`: every archive strategy family → existing repository owner → status → missing proof → next bounded task.
3. `DIRECT_VENUE_CROSSWALK.json`: each venue family/variant → code/reader/quote/SDK/atomic-builder state → current owner → exact missing evidence.
4. `MASTER_PR_DEPENDENCY_INVENTORY.json`: PR status, base/head, merged state, unique value, dependency and decision.
5. `OWNER_INTERFACE_FREEZE.md`: common schemas and files that cannot be edited concurrently.
6. `MASTER_00_RECEIPT.json`: current main SHA, archive hash list, tests actually run (may be `NOT_RUN` for documentation work), unresolved blockers and status counts.

## Dedup and identity policy
- Candidate key `(chain, casefold(symbolA), casefold(symbolB)` is **only a browsing key**. Preserve original symbols, order, archive ID, relationship type and provenance.
- Never merge on ticker/symbol. Resolve through chain, canonical address/full Move type, token program, issuer/wrapper/bridge, decimals, mint authority, genesis and Resolver generation.
- A pair can be a DEX pool candidate, synthetic conversion, NAV relation, maturity claim, redemption right, orderbook market, reference-only signal or bridge-flow relation. Do not promote all rows to swaps.
- USD0, USDT0, bUSD0 and rt-bUSD0 are distinct economic/legal objects. Keep issuer rights, redemption windows, maturities, wrapper/bridge and network identity explicit.
- A chain symbol in an archive is not current chain support; source/market existence must be refreshed.

## Exclusions
Robinhood Stock Tokens and tokenized equities are excluded from the trading/route universe by user policy. Do not introduce them into registries, strategies, benchmarks used for execution, or PnL. Keep non-equity RWA, FX and gold feeds separately classified as reference-only only when lawful and supported.

## MASTER-00 exit gate
PASS when inventories are complete, conflicts are explicit, one canonical owner per responsibility is recorded, P0/R-02/R-03/route dependencies are unambiguous, and shared evidence contracts are frozen. MASTER-00 does not qualify any new asset/pool/provider or change runtime authority.
