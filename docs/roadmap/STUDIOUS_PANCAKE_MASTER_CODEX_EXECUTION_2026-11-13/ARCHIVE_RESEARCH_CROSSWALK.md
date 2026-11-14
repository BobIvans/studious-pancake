# V3–V6 + prior conversation research crosswalk

## Provenance and proper interpretation
The historical archives were shared in earlier Studious Pancake conversations and loaded for this audit. Their research cutoff is 2026-10-08. The direct venue audit explicitly states that it was a read-only repository review, did not run repo tests or query live pool state, and that routes were hypotheses. The older ZIPs must not outrank current main, current official source docs, deployed code/ABI pins or rooted state.

The historical source packs are overlapping generations, not independent additive databases:
- V3 includes the previous 693-row hypothesis set with 659 casefold symbol keys and 34 collision excess; the 162 curated additions yielded four new casefold-unique rows after that archive's own review.
- V4 overlays a separate 838 symbolic-pair / 1,399 motif graph. Its V3 overlay receipt reports 175 new unique research keys over the historical V3 set; it also retains overlap.
- V5 reorganizes 203 market seeds and 39 route candidates, with conditional non-swap conversion relationships.
- V6 declares 175 candidate rows as a delta to V5 and identifies three overlaps removed; only two were historically market-documented and 154 were discovery hypotheses.
- The Maximum Direct Data Graph V3 archive and the Direct Venue Audit overlap with earlier direct-market registries. They are technical references, not an extra set of distinct markets or implementations.

The master inventory retains raw source rows and groups by chain+symbol pair for navigation only. The 959 candidate groups / 938 repeated mentions from the multi-archive index do not establish duplicate assets or shared pool liquidity.

## Strategy concepts explored across parallel conversations
### Local market and route mechanics
- Two-leg direct arbitrage across independent pools/venues.
- Venue fragmentation and multi-router quote divergence (Jupiter/Titan/OKX/0x can quote the same underlying pool; correlation/resource de-dup mandatory).
- 2–5 hop bounded local cycles, with a fresh exact quote at every amount and no linear scaling of one snapshot.
- Direct-market vs synthetic conversion paths, stable triangles and multi-pool residuals.
- AMM vs CLOB: Phoenix, OpenBook V2, Manifest, DeepBook, Kuru; lot/tick sizes, IOC/depth, sequence, partial-fill rules and fees.
- CLMM/DLMM/AMM microstructure: tick arrays, active bins, dynamic fees, hooks, Token-2022 transfer fees, consumed input, price impact and pool migration.

### Representation, NAV and protocol relations
- LST/LRT relative value, exchange rates, instant redemption vs cooldown/unstake queues, epoch/slashing and validator state.
- BTC wrapper / bridged representation parity: cbBTC, WBTC, xBTC, tBTC, cirBTC, kBTC and similar; issuer, bridge, origin chain and custody distinctions.
- ERC-4626 / vault share NAV: totalAssets, convertToAssets, previewRedeem, maxRedeem/maxWithdraw, withdrawal caps/queues and fees.
- Pendle PT/YT and maturity: pre-maturity sale is a market trade; face value at maturity or a time lock is not an instant flash leg.
- Stablecoin depeg/peg, issuer PSM, mint/burn, redemptions, buffer liquidity and legal/permission constraints.
- Conditional hyperedges: split/combine, mint/redeem, early-exit, claim, vault conversion and receipt-based operations; these are not ordinary swap edges.

### Market-state and external signal strategies
- Liquidation/health-factor and solvency risk events; only with protocol-specific on-chain state, liquidation eligibility and exact postconditions.
- Funding/basis/carry and incentives: epoch transitions, lending utilisation, reward changes, governance and validator/staking queue events.
- Pool birth, liquidity migration, active-bin shifts, token launch/meme/event migration and adverse-selection risk.
- CEX/DEX lead-lag and orderbook imbalance, oracle-vs-DEX residuals, FX/gold and other reference prices; these are signals, not executable local legs by default.
- Cross-chain bridge flows (CCTP, USDT0/OFT, IBC, Wormhole) as flow/context features. Bridge settlement is asynchronous and is never inserted into a same-transaction flashloan loop.
- Inventory rebalancing is a separate prefunded capital/risk strategy, not a flash-only PnL claim.

### Research and learning
- 43-class archive anomaly taxonomy and V4/V4.1 detector/feature templates.
- Time-blocked episodes, preregistered hypotheses, out-of-sample/walk-forward evaluation, null controls, multiple-testing correction, provider/pool alias leakage controls and source ablation.
- Deterministic baselines before contextual bandits or ML. Models remain advisory; no model may skip identity, quote, capacity, simulation or safety gates.

## Historical metrics, not current capability
| Research generation | Historical inventory |
|---|---|
| V3 | 519 base seeds; 162 curated high-value rows; 86 source profiles; 33 direct-venue records; 17 lender profiles; 64 route templates; 43 anomaly classes; 18 detector-family extensions |
| V4 | 838 symbolic pair hypotheses; 1,399 local motifs; 2,998 nodes; 11,523 edges; 25 detector templates; 30 learning features; canonical market count 0 |
| V4.1 | 98 market relations; 19 cycle motifs; 23 source-capability rows; 9 lender contract profiles; 12 staged PR slices |
| V5 | 203 chain-local seeds; 39 symbolic route hypotheses; 11 non-swap hyperedges; 14 source capability rows; 12 documented DeepBook pool IDs (not live verified) |
| V6 | 175 V5 delta rows; 36 route families; 12 conditional hyperedges; 33 official documentation-ledger rows; 14 data-source entries; 19 documented DeepBook SDK pool IDs (not live depth) |

Do not sum these columns and call the total an independent pool count, current pair count or strategy implementation count.

## Key structural corrections carried forward
- USD0 is not USDT0; bUSD0 is not rt-bUSD0; conversion and maturity rights require both legs and timing conditions.
- A stable or wrapped ticker does not establish economic equivalence.
- Pyth/oracle values are references, not swap outputs or liquidity.
- Curve get_dy/rates and Curve NG variant specifics cannot be replaced by generic StableSwap math.
- Uniswap V4 PoolKey/PoolId/hooks and Pancake Infinity pool types/hooks must be proven individually.
- Vault TVL, market TVL, pool balance and lender flash capacity are different measurements.
- Morpho Blue token balance, Aave reserve capacity/premium, Kamino/Jupiter/NAVI/DeepBook per-asset resource caps are separate lender facts.
- One physical pool/orderbook/underlying liquidity resource cannot be double-counted when multiple aggregators or wrappers quote it.
- TON async messages, CCTP/OFT/IBC and cross-chain bridge paths are non-atomic across chains.

## V6 pair/cluster additions worth explicit audit
The V6 delta broadens FX/EUR0, USD0 family and redemption rights, LST/LRT yield shares, wrapped BTC, emerging L2 local stables, chain-specific CLOB/AMM paths and conditional conversion hyperedges. Review every row in the archive; do not hard-bind its documented identifiers or historical URLs without a new source/chain proof.
