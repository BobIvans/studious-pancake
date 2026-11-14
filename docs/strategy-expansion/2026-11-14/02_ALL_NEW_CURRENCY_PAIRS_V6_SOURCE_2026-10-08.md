# V6: полный каталог новых пар и доказательств

**Всего новых уникальных пар относительно V5: 175.** Все statuses кроме pool registry и protocol relations — гипотезы. Документированная пара не означает текущую ликвидность.

## Ethereum — 28 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `EUR0/EURe` | FX_SAME_UNIT | P1 | DOCUMENTED_MARKET_HISTORICAL | Ethereum Uniswap V3 EUR0/EURe Feb-2026 documentary liquidity; refresh required |
| `EUR0/EURC` | FX_SAME_UNIT | P1 | DOCUMENTED_MARKET_HISTORICAL | Documented V3 pool; quote sizes, fee tiers and depth unverified today |
| `EUR0/USD0` | FX_CROSS_CURRENCY | P3 | PLANNED_NOT_DOCUMENTED_LIVE | Usual calls direct pool future plan; cannot instantiate swap edge |
| `EUR0/USDC` | FX_SYNTHETIC_ONLY | P2 | DISCOVERY_HYPOTHESIS | Compare EUR0/EURC and EURC/USDC |
| `sEUR0/EUR0` | ERC4626_VAULT_RATE | P1 | PROTOCOL_RELATION_DOCUMENTED | Use previewRedeem/maxRedeem and actual fee; no assumed secondary pool |
| `sUSD0/USD0` | ERC4626_VAULT_RATE | P1 | PROTOCOL_RELATION_DOCUMENTED | Vault share conversion; fee can be up to 3 bps |
| `frxUSD/USDC` | REDEEMABLE_STABLE | P1 | PROTOCOL_RELATION_DOCUMENTED | One-transaction redeem route exists; DEX pool and same-tx callback need verification |
| `sfrxUSD/frxUSD` | ERC4626_VAULT_RATE | P1 | PROTOCOL_RELATION_DOCUMENTED | No lockup stated, verify previewRedeem/maxRedeem and pool price |
| `frxUSD/USDT` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | A second DEX exit leg for frxUSD |
| `frxUSD/crvUSD` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Potential Curve stablecoin multi-pool |
| `scrvUSD/crvUSD` | ERC4626_VAULT_RATE | P1 | PROTOCOL_RELATION_DOCUMENTED | Yearn V3-based savings share; inspect withdrawal limits |
| `scrvUSD/USDC` | SAVINGS_SYNTHETIC | P2 | DISCOVERY_HYPOTHESIS | Require actual pool; compare scrvUSD/crvUSD plus crvUSD/USDC |
| `frxUSD/GHO` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Potential direct-vs-synthetic multi-stable triangle |
| `frxUSD/USD0` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Different issuers and different redemption mechanics |
| `frxUSD/USDe` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Different collateral and peg regimes |
| `frxUSD/PYUSD` | MULTI_STABLE | P3 | DISCOVERY_HYPOTHESIS | Cross-issuer parity only after pool discovery |
| `sfrxUSD/sUSDS` | YIELD_SHARE_RELATIVE | P3 | DISCOVERY_HYPOTHESIS | Both have floating share values, never force ratio=1 |
| `sfrxUSD/scrvUSD` | YIELD_SHARE_RELATIVE | P3 | DISCOVERY_HYPOTHESIS | Rate-adjusted relative basis |
| `USDS/frxUSD` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Issuer variation; any pool must be verified |
| `GHO/crvUSD` | MULTI_STABLE | P1 | DISCOVERY_HYPOTHESIS | Two protocol stablecoins with distinct peg dynamics |
| `GHO/USDe` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Borrowed vs synthetic-dollar supply stress |
| `crvUSD/USDS` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Peg keeper vs Sky settlement |
| `wstETH/weETH` | LRT_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | LRT exchange vs LST exchange and underlying ETH |
| `weETH/rETH` | LRT_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | ETH risk factors, unbond and restake withdrawal schedule |
| `sfrxETH/wstETH` | LST_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Different liquid staking exchange rates |
| `tBTC/cbBTC` | BTC_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Distinct custody/bridge risk; ticker parity isn't executable |
| `LBTC/tBTC` | BTC_REPRESENTATION | P3 | DISCOVERY_HYPOTHESIS | Different BTC wrapper issuers and redemption constraints |
| `bUSD0/sUSD0` | BOND_VS_SAVINGS | P2 | DISCOVERY_HYPOTHESIS | bUSD0 matures 2028; sUSD0 redeemable now; compare discounted cashflows |

**Funding hypothesis:** Morpho Blue; Aave V3; Balancer V2; other by deployment
**Reference docs:** source links available per JSON record.

## Base — 13 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/USDC` | STABLE_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | FraxNet supports Base; bridge/redeem off-chain crosschain not flash leg |
| `sfrxUSD/frxUSD` | ERC4626_VAULT_RATE | P2 | DISCOVERY_HYPOTHESIS | Check whether local vault is deployed and redeemed atomically |
| `scrvUSD/crvUSD` | ERC4626_VAULT_RATE | P2 | PROTOCOL_RELATION_DOCUMENTED | scrvUSD deployed on Base; exact asset identity and live pool missing |
| `frxUSD/USD0` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Different issuer stable pool discovery |
| `frxUSD/USDe` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Potential stable DEX basis |
| `sUSDe/USDe` | ETHENA_STAKING | P2 | DISCOVERY_HYPOTHESIS | A cooldown applies to issuer redemption; DEX swap only if local pools |
| `USDC/PYUSD` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Test second liquidity venue and net fees |
| `cbBTC/tBTC` | BTC_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Wrapper conversion reference not atomic by default |
| `weETH/wstETH` | LRT_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Compare two ETH yield tokens after normalized exchange rates |
| `crvUSD/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Curve crvUSD liquidity discovery |
| `GHO/frxUSD` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Different onchain issuers |
| `USDG/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Find real pools by contract address, not name |
| `USD1/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Avoid false asset symbol matching |

**Funding hypothesis:** Morpho Blue/Aave depending deployment
**Reference docs:** source links available per JSON record.

## Arbitrum — 11 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | FraxNet exists but local AMM to verify |
| `sfrxUSD/frxUSD` | ERC4626_VAULT_RATE | P2 | DISCOVERY_HYPOTHESIS | Local route must be verified |
| `crvUSD/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Pool discovery |
| `scrvUSD/crvUSD` | ERC4626_VAULT_RATE | P2 | DISCOVERY_HYPOTHESIS | Deployment requires official verification |
| `frxUSD/USDT0` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | USDT0 on Arbitrum; local pool to discover |
| `USDT0/USD0` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Two distinct stable issuer paths |
| `GHO/crvUSD` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Stable issuer basis |
| `sUSDS/USDS` | SAVINGS_RATE | P2 | DISCOVERY_HYPOTHESIS | Verify native share conversion before any execution |
| `wstETH/weETH` | LST_LRT_RATE | P3 | DISCOVERY_HYPOTHESIS | Relative yield token basis |
| `tBTC/WBTC` | BTC_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Custody and oracle difference |
| `LBTC/WBTC` | BTC_REPRESENTATION | P3 | DISCOVERY_HYPOTHESIS | Distinct issuer redemption |

**Funding hypothesis:** Aave V3/Morpho Blue as deployed
**Reference docs:** source links available per JSON record.

## Gnosis — 5 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `EURe/EURC` | FX_SAME_UNIT | P2 | DISCOVERY_HYPOTHESIS | Only activate after checking representation deployments |
| `ZCHF/USDC.e` | FX_SYNTHETIC | P2 | DISCOVERY_HYPOTHESIS | Reference CHF/USD is not swap |
| `BRLA/xDAI` | FX_CROSS_CURRENCY | P3 | DISCOVERY_HYPOTHESIS | BRL/USD reference with FX closing leg |
| `USDC.e/USDT` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Wrapped issuer identity matters |
| `sDAI/EURe` | FX_YIELD_SYNTHETIC | P2 | DISCOVERY_HYPOTHESIS | Convert sDAI via savings to USD before EUR FX basis |

**Funding hypothesis:** Aave V3 contingent reserve
**Reference docs:** source links available per JSON record.

## Sui — 20 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `SUI/AUSD` | STABLE_NATIVE_TRIANGLE | P0 | DOCUMENTED_POOL_ID | Mainnet DeepBook SUI_AUSD |
| `AUSD/USDC` | MULTI_STABLE | P0 | DOCUMENTED_POOL_ID | Mainnet DeepBook AUSD_USDC |
| `WAL/SUI` | VOLATILE_TRIANGLE | P1 | DOCUMENTED_POOL_ID | Mainnet DeepBook WAL_SUI |
| `WAL/USDC` | VOLATILE_TRIANGLE | P1 | DOCUMENTED_POOL_ID | Mainnet DeepBook WAL_USDC |
| `NS/SUI` | VOLATILE_TRIANGLE | P1 | DOCUMENTED_POOL_ID | Mainnet DeepBook NS_SUI |
| `NS/USDC` | VOLATILE_TRIANGLE | P1 | DOCUMENTED_POOL_ID | Mainnet DeepBook NS_USDC |
| `WAL/haWAL` | SUI_WAL_STAKING | P2 | PROTOCOL_ASSET_DOCUMENTED | haWAL listed by Scallop; confirm actual staking rate and local markets |
| `USDY/USDC` | YIELD_DOLLAR | P2 | PROTOCOL_ASSET_DOCUMENTED | Official Sui USDY coin type; verify secondary market |
| `USDY/SUI` | YIELD_DOLLAR | P2 | DISCOVERY_HYPOTHESIS | Stable-with-yield vs SUI synthetic |
| `FDUSD/USDC` | STABLE_PEG | P2 | PROTOCOL_ASSET_DOCUMENTED | Sui FDUSD coin type; require DEX pool |
| `mUSD/USDC` | STABLE_PEG | P2 | PROTOCOL_ASSET_DOCUMENTED | Sui mUSD issuer differs from Monad MUSD: do not dedup |
| `mUSD/SUI` | STABLE_NATIVE_TRIANGLE | P2 | DISCOVERY_HYPOTHESIS | A second Sui mUSD path |
| `XBTC/LZWBTC` | BTC_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Two USDC-quoted mainnet pools, direct pair not proven |
| `XBTC/SUI` | BTC_SYNTHETIC | P2 | DISCOVERY_HYPOTHESIS | BTC direct-vs-USDC synthetic |
| `DEEP/AUSD` | CLOB_SYNTHETIC | P2 | DISCOVERY_HYPOTHESIS | Can synthesize via USDC but no direct pool proven |
| `WAL/DEEP` | CLOB_SYNTHETIC | P2 | DISCOVERY_HYPOTHESIS | Volatile token, latency-sensitive |
| `suiUSDe/AUSD` | STABLE_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Compare both via USDC; direct pair discovery |
| `USDsui/AUSD` | STABLE_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Compare both via USDC; direct pair discovery |
| `XAUm/USDC` | GOLD_REFERENCE | P2 | PROTOCOL_ASSET_DOCUMENTED | Scallop knows XAUm, but no DEX liquidity proven |
| `XAUm/SUI` | GOLD_REFERENCE | P3 | DISCOVERY_HYPOTHESIS | Reference gold only; local swap must be discovered |

**Funding hypothesis:** DeepBook flash; NAVI/Scallop contingent live pool state
**Reference docs:** source links available per JSON record.

## Solana — 22 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Frax documentation has Solana transfer; local mint and pool still verify |
| `USDG/USD1` | STABLE_TRIANGLE | P1 | DISCOVERY_HYPOTHESIS | Direct stable leg requires pool, do not infer from USDC hubs |
| `USDT/USDG` | STABLE_TRIANGLE | P1 | DISCOVERY_HYPOTHESIS | Potential independent Manifest pool |
| `USD1/PYUSD` | STABLE_TRIANGLE | P2 | DISCOVERY_HYPOTHESIS | Issuer difference |
| `USD1/JupUSD` | STABLE_TRIANGLE | P2 | DISCOVERY_HYPOTHESIS | Issuer difference |
| `PYUSD/JupUSD` | STABLE_TRIANGLE | P2 | DISCOVERY_HYPOTHESIS | Issuer difference |
| `JupUSD/USDG` | STABLE_TRIANGLE | P2 | DISCOVERY_HYPOTHESIS | Compare synthetic USDC routes |
| `JLP/JupUSD` | JLP_NAV | P2 | DISCOVERY_HYPOTHESIS | NAV numerator vs quote asset |
| `JLP/SOL` | JLP_NAV | P2 | DISCOVERY_HYPOTHESIS | JLP basket risk and SOL synthetic |
| `INF/JitoSOL` | LST_BASKET_PARITY | P1 | DISCOVERY_HYPOTHESIS | Sanctum Infinity LST basket relative value |
| `INF/JupSOL` | LST_BASKET_PARITY | P2 | DISCOVERY_HYPOTHESIS | NAV and SOL rate |
| `JitoSOL/JupSOL` | LST_LST_RATE | P1 | DISCOVERY_HYPOTHESIS | Compare independent SOL conversion rates |
| `JitoSOL/mSOL` | LST_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Compare LST underlying rates |
| `JitoSOL/BNSOL` | LST_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Need active pool |
| `JupSOL/BNSOL` | LST_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Need active pool |
| `BNSOL/bbSOL` | LST_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Need actual pool |
| `JitoSOL/dSOL` | LST_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Protocol rate and stake exit restrictions |
| `xBTC/WBTC` | BTC_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Two wrappers have different issuer risk |
| `tBTC/cbBTC` | BTC_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Two wrappers have different issuer risk |
| `USDY/USDC` | YIELD_DOLLAR | P2 | DISCOVERY_HYPOTHESIS | NAV and yield-bearing USDY, no dollar peg assertion |
| `FDUSD/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Canonical mint not hardcoded |
| `USDe/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Verify local chain issuer contract representation |

**Funding hypothesis:** Project0/Kamino — verify live eligible banks and asset caps
**Reference docs:** source links available per JSON record.

## X Layer — 6 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `PT-USDG-29OCT2026/USDT0` | PT_VS_STABLE | P1 | PROTOCOL_MARKET_DOCUMENTED | PT exists as asset but direct USDT0 pool not proven |
| `PT-USDG-29OCT2026/PT-USDG-25FEB2027` | MATURITY_ROLL | P2 | DISCOVERY_HYPOTHESIS | Never assert direct pool or pre-maturity redemption |
| `GHO/USDT0` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Aave GHO and USDT0 reserves are not DEX pool evidence |
| `xBTC/USDT0` | BTC_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | USDG synthetic route, direct pool to discover |
| `xSOL/USDT0` | SOL_WRAPPER | P2 | DISCOVERY_HYPOTHESIS | USDG synthetic route, direct pool to discover |
| `syrupUSDG/USDG` | ERC4626_RATE | P3 | DISCOVERY_HYPOTHESIS | Verify token and issuer on X Layer first |

**Funding hypothesis:** Aave V3 — reserve specific current amount and premium
**Reference docs:** source links available per JSON record.

## Monad — 12 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | FraxNet supports Monad mint; DEX pool not verified |
| `sfrxUSD/frxUSD` | ERC4626_RATE | P2 | DISCOVERY_HYPOTHESIS | Local vault and pool must be identified |
| `frxUSD/AUSD` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | DEX A vs synthetic route |
| `AUSD/USDT0` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Flow impact on local AUSD |
| `MUSD/AUSD` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Both distinct USD assets |
| `MUSD/USDT0` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Bridge inflow response |
| `USDT0/WETH` | STABLE_ETH | P2 | DISCOVERY_HYPOTHESIS | Need liquidity, don't force triangle |
| `XAUT0/USDT0` | GOLD_REFERENCE | P2 | DISCOVERY_HYPOTHESIS | Cross-representation gold reference, requires local pool |
| `EURW/USDT0` | FX_CROSS_CURRENCY | P3 | DISCOVERY_HYPOTHESIS | EUR token identity and FX spot feed required |
| `sMON/MON` | LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Staking rate, quote leg if pool |
| `shMON/MON` | LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Separate staking share |
| `sMON/shMON` | LST_LST_RATE | P3 | DISCOVERY_HYPOTHESIS | If no direct pool use synthetic comparative signal |

**Funding hypothesis:** Morpho Blue/Aave V3 — lender balance/premium not TVL
**Reference docs:** source links available per JSON record.

## HyperEVM — 10 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `USDe/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | USDe asset seen in protocol but pool to discover |
| `USDe/USDT0` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Bridge flow driven stable basis |
| `sUSDe/USDe` | ETHENA_STAKING | P2 | DISCOVERY_HYPOTHESIS | Do not treat staking exit with cooldown as instant |
| `kHYPE/USDT0` | HYPE_LST | P2 | DISCOVERY_HYPOTHESIS | Synthetic WHYPE path |
| `UBTC/USDT0` | BTC_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Underlying BTC fee spread |
| `UETH/USDT0` | ETH_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Underlying ETH fee spread |
| `UBTC/kHYPE` | BTC_HYPE_SYNTHETIC | P2 | DISCOVERY_HYPOTHESIS | Multi-hop venue combinations |
| `wstHYPE/kHYPE` | LST_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Independent staking rates |
| `lstHYPE/kHYPE` | LST_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Unbond and redemption risks |
| `beHYPE/kHYPE` | LST_LST_RATE | P2 | DISCOVERY_HYPOTHESIS | Distinct staking wrappers |

**Funding hypothesis:** Morpho Blue contingent singleton balance
**Reference docs:** source links available per JSON record.

## Plasma — 7 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `USDai/USDe` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Different peg mechanisms |
| `sUSDai/USDai` | ERC4626_VAULT_RATE | P2 | DISCOVERY_HYPOTHESIS | Share exchange rate plus exit fee |
| `sUSDe/USDe` | ETHENA_STAKING | P2 | DISCOVERY_HYPOTHESIS | Cooldown not a flash leg |
| `GHO/USDe` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Pool detection needed |
| `GHO/USDC` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Pool detection needed |
| `EURC/USDT0` | FX_CROSS_CURRENCY | P2 | DISCOVERY_HYPOTHESIS | FX feed only, track parity |
| `sUSDe/sUSDai` | YIELD_SHARE_RELATIVE | P3 | DISCOVERY_HYPOTHESIS | NAV normalized shares, no 1:1 |

**Funding hypothesis:** Aave V3 — fresh reserve availableLiquidity needed
**Reference docs:** source links available per JSON record.

## Ink — 9 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/USDT0` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | FraxNet supports Ink, DEX pool required |
| `frxUSD/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | FraxNet and Aave market existence not DEX proof |
| `sfrxUSD/frxUSD` | ERC4626_VAULT_RATE | P2 | DISCOVERY_HYPOTHESIS | Must check vault deployment |
| `USDC/USDG` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Discovery-only stable leg |
| `kBTC/USDC` | BTC_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | kBTC variant, separate from other chains |
| `USDe/GHO` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Interest bearing vs stable |
| `sUSDe/USDe` | ETHENA_STAKING | P2 | DISCOVERY_HYPOTHESIS | Issuer exit cooldown |
| `USDG/GHO` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Issuer basis |
| `GHO/USDC` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Requires live pool |

**Funding hypothesis:** Aave V3 — token-specific capacity
**Reference docs:** source links available per JSON record.

## Sei — 5 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | FraxNet supports Sei, pool unresolved |
| `frxUSD/USDT0` | MULTI_STABLE | P2 | DISCOVERY_HYPOTHESIS | Cross issuer stable, lender fee Yei may erase spread |
| `sfrxUSD/frxUSD` | ERC4626_RATE | P3 | DISCOVERY_HYPOTHESIS | Local share vault unverified |
| `WETH/WSEI` | VOLATILE_TRIANGLE | P2 | DISCOVERY_HYPOTHESIS | WETH-USDC & WSEI-USDC synthetic |
| `WBTC/WETH` | BTC_ETH | P2 | DISCOVERY_HYPOTHESIS | Direct-vs-USDC synthetic |

**Funding hypothesis:** Yei Aave fork — initial 0.1% flash fee, query live fee
**Reference docs:** source links available per JSON record.

## Berachain — 5 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/USDC.e` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | FraxNet supports Berachain, pools to discover |
| `frxUSD/BUSD` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Berachain BUSD is not Binance historical BUSD |
| `sfrxUSD/frxUSD` | ERC4626_RATE | P2 | DISCOVERY_HYPOTHESIS | Local vault check |
| `sWBERA/USDC.e` | LST_NATIVE | P2 | DISCOVERY_HYPOTHESIS | Unstake delay and WBERA synthetic |
| `WETH/USDT0` | ETH_STABLE | P2 | DISCOVERY_HYPOTHESIS | Local pool must be discovered |

**Funding hypothesis:** Bend/Morpho Blue zero protocol fee contingent balance
**Reference docs:** source links available per JSON record.

## Avalanche — 5 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | FraxNet supports Avalanche |
| `sfrxUSD/frxUSD` | ERC4626_VAULT_RATE | P2 | DISCOVERY_HYPOTHESIS | Local vault unverified |
| `scrvUSD/crvUSD` | ERC4626_VAULT_RATE | P2 | DISCOVERY_HYPOTHESIS | Deployment and liquidity unverified |
| `BTC.b/WBTC` | BTC_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Two BTC representations |
| `BTC.b/cbBTC` | BTC_REPRESENTATION | P2 | DISCOVERY_HYPOTHESIS | Custodial difference |

**Funding hypothesis:** Aave V3 — exact current reserve/liquidity
**Reference docs:** source links available per JSON record.

## Optimism — 3 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | FraxNet supports Optimism |
| `sfrxUSD/frxUSD` | ERC4626_RATE | P2 | DISCOVERY_HYPOTHESIS | Local savings not assumed available |
| `scrvUSD/crvUSD` | ERC4626_VAULT_RATE | P2 | DISCOVERY_HYPOTHESIS | scrvUSD deployed on Optimism; pool still needed |

**Funding hypothesis:** Aave V3 contingent pool reserves
**Reference docs:** source links available per JSON record.

## Unichain — 6 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/USDC` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | FraxNet supports Unichain |
| `sfrxUSD/frxUSD` | ERC4626_RATE | P2 | DISCOVERY_HYPOTHESIS | Local vault unknown |
| `USDe/USDT0` | STABLE_PEG | P2 | DISCOVERY_HYPOTHESIS | Pool to discover |
| `EURC/USDC` | FX_CROSS_CURRENCY | P2 | DISCOVERY_HYPOTHESIS | Canonical token issuers and pools |
| `HYPE/USDT0` | HYPE_STABLE | P2 | DISCOVERY_HYPOTHESIS | Direct vs USDC synthetic |
| `WETH/frxUSD` | ETH_STABLE | P3 | DISCOVERY_HYPOTHESIS | Direct pool unknown |

**Funding hypothesis:** Morpho Blue — current contract balance only
**Reference docs:** source links available per JSON record.

## Katana — 4 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/USDC` | STABLE_PEG | P3 | DISCOVERY_HYPOTHESIS | FraxNet supports Katana but local pool unknown |
| `sfrxUSD/frxUSD` | ERC4626_RATE | P3 | DISCOVERY_HYPOTHESIS | Vault unknown |
| `BTC.b/vbUSDC` | VAULTBRIDGE | P3 | DISCOVERY_HYPOTHESIS | VaultBridge redemption via Ethereum not atomic |
| `vbUSDT/AUSD` | VAULTBRIDGE | P3 | DISCOVERY_HYPOTHESIS | Only local DEX legs, never bridge redemptions |

**Funding hypothesis:** Morpho Blue contingent balance
**Reference docs:** source links available per JSON record.

## Tempo — 4 новых отношений

| Pair | Family | Tier | Evidence | Why |
|---|---|---|---|---|
| `frxUSD/pathUSD` | STABLE_PEG | P3 | DISCOVERY_HYPOTHESIS | FraxNet supports Tempo, native stable DEX pool unknown |
| `frxUSD/USDC.e` | STABLE_PEG | P3 | DISCOVERY_HYPOTHESIS | Bridge-backed USD differences |
| `OUSD/USDT0` | MULTI_STABLE | P3 | DISCOVERY_HYPOTHESIS | Thin funding, exact flash balance required |
| `OUSD/cUSD` | MULTI_STABLE | P3 | DISCOVERY_HYPOTHESIS | Mint redeem pathways unverified |

**Funding hypothesis:** Morpho Blue — verify singleton token balance; reported supply may be tiny
**Reference docs:** source links available per JSON record.