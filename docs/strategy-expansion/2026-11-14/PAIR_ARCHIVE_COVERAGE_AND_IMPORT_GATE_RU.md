# Pair archive coverage & import gate — 2026-11-14

## Executive finding

**No: the currency/pair candidates from the first Build Bigger Universe ZIP and the V3/V4/V5/V6 sources are not all implemented in the bot.** They are historical research records and discovery hypotheses. The current repository has a small research placeholder universe, not the complete archive imported into canonical, verified markets and not an executable route universe.

This report is a source-row audit, not a profitability assertion. It distinguishes archival pair rows from asset identity, deployed market/pool identity, exact amount quotes, flash capacity, transaction build, simulation and paper qualification.

## Source-backed row counts and evidence

| Source | Rows / count | What the records actually prove | What they do NOT prove |
|---|---:|---|---|
| First `UNIVERSAL_MARKET_GRAPH_RND_2026-10-07` ZIP, `data/market_universe_candidates.json` | 519 | Unique archive candidate IDs; candidate symbols/chains; READ_ONLY; 357 rows have suspected-venue labels and 216 have source URL hints | 0 rows have canonical_a, canonical_b or market_identity; no pool identity, exact quote, or capacity |
| V3 `data_v3/market_universe_v3.json` | 1,147 | 1,147 candidate IDs and 1,147 chain/symbol tuples; evidence classes and priorities recorded | 0 canonical_a, 0 canonical_b, 0 market_identity; 693 READ_ONLY and 454 execution_permission NONE |
| V3 `new_data/unified_market_universe_v2.json` | 693 | Consolidated seed layer; previous_count 519; 174 additional candidates recorded by that file | All 693 are READ_ONLY research candidates; 0 canonical asset pairs and 0 market_identity |
| V3 `new_data/new_seed_candidates_v3.json` | 454 | Additional discovery seeds represented in V3 full universe | All have to be verified; not live markets |
| V3 `v3_research/new_high_value_family_seeds.json` | 162 | Prioritized family seeds | Not a separate additive 162 executable pairs; every row remains discovery-only with no pool/quote/flash proof |
| V4 `data/all_symbolic_research_pairs.json` | 838 | Symbolic pair rows; 659 carry V3 history, 175 are V4 additions, 4 are V3 refresh rows | canonical_count=0; all 838 SYMBOLIC_UNVERIFIED; all execution_permission=NONE |
| V4 `data/v4_new_pairs.csv` | 175 | The V4 addition delta | All 175 SYMBOLIC_UNVERIFIED; all execution_permission=NONE |
| V5 `data/symbolic_route_hypotheses.json` | 39 route hypotheses | Route concepts and candidate topologies | Not 39 executable pair routes; V5 route records are discovery-only |
| V6 `data/v6_new_pair_candidates_DELTA_TO_V5.json` | 175 | New pair hypotheses relative to V5; evidence grades and possible source references | All 175 pair_is_executable=false; all MUST_VERIFY_ON_CHAIN; all NO_EXACT_QUOTE; all NOT_READ for flash capacity and pool liquidity |
| V6 `02_ALL_NEW_CURRENCY_PAIRS_RU.md` | 175 listed pairs | Human-readable V6 pair list by chain and family | No current live market, quote, flash capacity or profitability proof |

Counts are not additive across generations. V3 full 1,147 already includes the earlier 519 and later candidate additions; V4 retains V3 history; V6 is a delta against V5. Do not sum all rows and call that a unique live universe.

### V6 175-pair source details

Per the original V6 catalog:
- Ethereum 28; Solana 22; Sui 20; Base 13; Monad 12; Arbitrum 11; HyperEVM 10; Ink 9; Plasma 7; X Layer 6; Unichain 6; Gnosis 5; Sei 5; Berachain 5; Avalanche 5; Katana 4; Tempo 4; Optimism 3.
- Evidence grades: 154 DISCOVERY_HYPOTHESIS, 6 DOCUMENTED_POOL_ID, 6 PROTOCOL_RELATION_DOCUMENTED, 5 PROTOCOL_ASSET_DOCUMENTED, 2 DOCUMENTED_MARKET_HISTORICAL, 1 PLANNED_NOT_DOCUMENTED_LIVE, 1 PROTOCOL_MARKET_DOCUMENTED.
- Even the six documented pool-ID entries are not execution evidence: in the same file all 175 have pair_is_executable=false, identity MUST_VERIFY_ON_CHAIN, quote NO_EXACT_QUOTE, flash capacity NOT_READ and pool liquidity NOT_READ.
- V6's three removed overlaps with V5 were Ethereum rt-bUSD0/USD0, Gnosis GBPe/EURe, Plasma USDC/USDe. The source also records one duplicate line removed (Gnosis EURe/sDAI).

The full source catalog has been preserved in this PR as `02_ALL_NEW_CURRENCY_PAIRS_V6_SOURCE_2026-10-08.md`; it is copied from the original Library source file and must remain source material, not be relabelled as an implementation.

## Current repository comparison

Current main's GPR `SYMBOLIC_UNIVERSE.md` contains 268 placeholder relationship rows (Solana 224, Sui 38, TON 6) and explicitly states `runtime_enabled=false` for every relationship. Its `ASSET_REGISTRY_V2.json` contains 92 research identities (Solana 51, Sui 33, TON 8); the registry semantics explicitly say R&D identifier evidence is not runtime qualification and current identifiers must be revalidated. The three-chain symbolic list is not a complete import of the multi-chain V3/V4/V6 catalog.

The repository's strategy/capability matrix still says:
- the supported runtime has six strategy registrations;
- circular arbitrage is a two-leg, shadow-only detector;
- LST depeg/unstake are stubs or unbound until their proof gates pass;
- liquidation and orderbook remain fixture-only/quarantined;
- Pump migration remains discovery/boundary-only;
- current capital-provider readers are unqualified, with zero qualified flash-capital edges;
- route selection / exact simulation / paper qualification remain blocked by qualified capital, builder and QPR evidence.

Therefore: a pair appearing in `SYMBOLIC_UNIVERSE.md`, `ASSET_REGISTRY_V2.json`, a route hypothesis or a provider dossier is not an implemented route.

## Mandatory PAIR-00 work package — exhaustive row-level reconciliation

The coding agent MUST do this before declaring the pair-universe assignment complete:

1. Read the original ZIPs listed in `BUILD_BIGGER_UNIVERSE_GRAPH_ARCHIVE_MANIFEST_V1.json`, starting with the first Universal Market Graph archive; then V3, V4, V4.1, V5 and V6. Preserve immutable source names, source paths, archive hashes, row IDs, chain names, original symbols, order, source evidence and version lineage.
2. Build a machine-readable row-level crosswalk, not a count-only report. Every source row must receive one stable archive-row ID and one disposition: DUPLICATE_OF, SYMBOLIC_UNVERIFIED, IDENTITY_UNRESOLVED, IDENTITY_AMBIGUOUS, MARKET_NOT_FOUND, MARKET_IDENTITY_UNVERIFIED, POOL_NOT_FOUND, POOL_STATE_NOT_PROVEN, EXACT_QUOTE_MISSING, CAPITAL_MISSING, EXCLUDED, or one of the later proof tiers.
3. Preserve ticker collisions and chain-specific representations. Do not deduplicate by symbol, case-folded ticker, or assumed economic equivalence. Deduplication requires chain/settlement domain + verified canonical identifier + representation/issuer/origin semantics + actual underlying resource identity. The archive records 34 ticker-collision review cases; resolve each or keep it ambiguous.
4. Import the complete source seed set into the existing AssetResolver/Dynamic Universe and canonical research universe owners. Do not create a second registry or replace the current GPR registry. Discovery candidates remain runtime-disabled until the existing admission gates promote them.
5. For every pair intended for exact graph inclusion, prove both canonical asset identities (chain, mint/contract/Move type/jetton master, decimals, token program/issuer/representation) and the exact current venue market/pool ID, owner/program/deployment revision and underlying resources. A pair with no live pool is retained as a negative discovery result, not a synthetic edge.
6. Capture same-generation state and exact amount-specific quotes for every admissible size. No oracle-only, aggregator-symbol-only, TVL, historic pool, or scaled quote is acceptable. Every route leg is re-quoted at each amount.
7. Separately prove local flash funding for that chain and asset: provider eligibility, amount-specific capacity, fee, caller rights, callback/repayment semantics, all obligations and freshness. No TVL proxy; no cross-chain financing substitution.
8. Publish per-source/per-chain denominators: imported rows, exact duplicates, ticker collisions, canonical identities resolved, pools verified, exact state verified, size quotes, capital-qualified, built, simulated, paper-qualified, rejected, excluded and unresolved. Unknown stays null, never zero.
9. Add replayable positive/negative/stale/no-market/ambiguous/duplicate/no-capacity cases. Re-run the row-level import after every registry/source revision and show deterministic diff.
10. Wire only candidates that satisfy the existing strategy contract and paper/shadow pipeline. Never auto-enable live execution.

### Required pair-level completion states

`ARCHIVE_ROW_PRESERVED → IDENTITY_VERIFIED → MARKET_IDENTITY_VERIFIED → STATE_VERIFIED → EXACT_QUOTE → CAPITAL_QUALIFIED → BUILD_CONFORMANT → SIMULATION_PASS → PAPER_QUALIFIED`

Not every row will reach the final tier. Research-only, blocked, unsupported, async and excluded rows may remain at their truthful tier indefinitely. A completed audit means every source row has an owner and a disposition, not that every symbol pair has a pool or is profitable.

## Archive integrity and policy

- Keep the supplied source ZIP hashes and manifest. Never rewrite the original evidence in place.
- Robinhood Stock Tokens/tokenized equities are EXCLUDED by user policy; preserve only as historical rows marked EXCLUDED, not as executable candidates.
- Cross-chain bridges, CCTP/OFT/IBC, TON async, CEX settlement, cooldown queues, delayed redemption and maturity claims are not local atomic edges.
- V6 LST/yield/vault/wrapper and cross-currency pairs require typed rights, exchange-rate, maturity, oracle and exit semantics; ticker similarity is insufficient.
- Every row must keep `execution_permission=NONE` or its source read-only status until separately admitted by the existing evidence gates.
