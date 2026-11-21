# Sui asset universe, pair discovery and venue/provider plan

## 1. What the existing registry contains

Canonical source: docs/roadmap/dynamic-universe-master-2026-10-07/CODEX_START_HERE.md, Part A, §2. It is an **asset identity seed registry**, not a prequalified list of executable pairs.

Sui identity is the complete package::module::type CoinType. A ticker, package address alone, token-list entry or symbol match is not enough. Every HARD_BIND row still requires current startup/on-chain verification; VERIFY_STARTUP needs the stated live verification; RESOLVE_LIVE must be resolved from issuer/protocol source and verified before promotion.

Examples already in that source:

| Cluster | Seed assets | Example purpose |
|---|---|---|
| Settlement / stable | SUI, native USDC, wUSDC, USDCsol, wUSDT, sbUSDT, FDUSD, USDY, mUSD, suiUSDe, USDsui, AUSD, BUCK, sUSDB | base/quote hubs, stable representation/parity research |
| BTC / ETH / SOL representations | xBTC, wBTC, sbwBTC, zwBTC, LBTC, wETH, sbETH, wSOL | wrapped-asset representation / cross-venue paths |
| SUI LST | sSUI, afSUI, haSUI, vSUI, scaSUI, stSUI (RESOLVE_LIVE), eSUI (RESOLVE_LIVE) | SUI/LST basis and venue fragmentation |
| Ecosystem / venue | DEEP, WAL, SCA, NAVX, CETUS, NS, SEND, IKA, ALKIMI, BLUE, HAEDAL, wWAL, haWAL, TYPUS, DRF | DeepBook/CLOB and multi-venue discovery |
| Event / long-tail | FUD, BLUB, LOFI, TRUTH (RESOLVE_LIVE) | only after identity/liquidity/risk checks |
| Commodity reference | XAUm, XAGm (RESOLVE_LIVE) | structural/oracle reference, not auto-trade |

The registry includes stable representations that are NOT interchangeable. In particular, native USDC, Wormhole wUSDC and Wormhole USDCsol have distinct CoinTypes and bridge/origin risk. Never merge them into one asset key or assume 1:1 conversion without a separately proven local route.

## 2. Priority pair families to DISCOVER — not hardcode as if already executable

Use these as initial search families; instantiate a pair only when a real pool/book or supported router path exists and identity/state/fee provenance is verified.

**P0 — deep settlement and core market coverage**
- SUI ↔ native USDC
- SUI ↔ wUSDC (separate representation)
- DEEP ↔ SUI and DEEP ↔ native USDC
- SUI ↔ vSUI / afSUI / haSUI / sSUI, subject to live token resolution and exact LST conversion semantics

**P1 — stable representation / market fragmentation**
- native USDC ↔ wUSDC
- native USDC ↔ wUSDT / sbUSDT
- native USDC ↔ FDUSD / USDY / AUSD / mUSD
- wUSDC or stable hubs ↔ xBTC / wBTC / wETH / wSOL where a verified pool/book exists

**P1 — SUI LST / ecosystem**
- sSUI, afSUI, haSUI, vSUI, scaSUI against SUI and appropriate stable hubs
- WAL, SCA, NAVX, CETUS, NS, SEND, BLUE against SUI/stable hubs only when current pool/book data supports a real path

**P2 — research only until strong evidence**
- BTC/ETH/SOL representation parity; stablecoin depeg/bridge basis; LST fair value; XAUm/XAGm oracle basis; event tokens.
- Cross-chain correlations are signals only; no Solana↔Sui single-transaction flashloan assumption.

These are candidate families, not claims that every pair is listed, liquid, flash-borrowable or profitable. Do not generate a full N×N token cross product. Generate bounded relations from actual pool/book/router inventory and activity/quality thresholds. Retain explicit pool IDs, source operators, route legs and exact amount ranges.

## 3. Sui market data and quote providers

| Source | Role | Current repo readiness | Agent direction |
|---|---|---|---|
| Sui gRPC | ledger/checkpoint/object state and subscriptions | governed models exist; live provider binding remains hard BLOCKED | use existing QPR/DIN-02; only exact read methods; no JSON-RPC fallback |
| Sui GraphQL | structured query/checkpoint/object state | bounded source owners exist; live binding remains hard BLOCKED | use current profiles, request budgets, schema pins and capture journal |
| Aftermath Router | economic route quote; separate composable PTB builder surface | offline normalizer exists at src/gpr_sui_shadow/providers/aftermath.py; no transport/boot wiring; live gate blocked | add injected/approved transport and supported R13 ingress; separate quote from add-trade builder |
| Cetus Aggregator V3 | multi-venue quote; SDK can compose swap into caller PTB | docs/source dossier only; adapter absent; package license field absent | use V3 find_routes; verify current schema/terms, do not vendor SDK without license clearance; validate overlayFee/DeepBook fees |
| 7K / Bluefin7K | quote + PTB build/append; MetaAg spans other aggregators | source dossier only; adapter absent; MIT SDK pin available | use quote/build contracts; account for commission partner, tip, platform fee and rate limit |
| FlowX | multi-venue meta-aggregator, quote + PTB build/append | docs-only; SDK license unknown; no adapter | API/SDK integration only after legal and credential review; treat as one correlated SOR group; obey warning that commission-inclusive amountOut is display-only |
| OKX DEX | Sui route source / 7K sub-provider | Sui parameter/schema and quotas remain incomplete | contract-pin before adapter; no assumed independence from 7K |
| Rango | multi-chain route reference / Sui tx response | docs-only; Sui transaction sub-shape and quota incomplete | start quote/evidence only; no PTB builder until exact Move transaction semantics proven |
| Direct DeepBook | direct orderbook pool state and exact book depth | GPR-03 state owner exists; no R13 quote adapter | bind pool/book state and exact price-time/fee/depth math; use same pool object as one capital-resource identity |

Never let aggregator quote output replace direct state. A SOR may route through Cetus, DeepBook, Aftermath, FlowX, Bluefin, Turbos, etc. Store all returned underlying venue/pool IDs and deduplicate. Direct DeepBook state is the structurally distinct book evidence; multiple aggregator responses over that book are correlated.

## 4. Lender selection on Sui

- **NAVI:** priority lender; use modular @naviprotocol/lending, not the deprecated legacy SDK. getAllFlashLoanAssets is discovery metadata until linked to checkpoint-consistent package/config/pool object, exact CoinType/decimals and effective cap. Existing src/multichain/sui.py reader model and src/lending/unsigned_builders/navi_ptb_builder.py builder are offline/unqualified. v1/v2 selection must use verified on-chain config version. Borrow and repay must consume the exact hot-potato receipt in one PTB.
- **DeepBook V3:** priority lender; borrowBase/Quote and return must be in one PTB. Capacity is pool-local and competes with orderbook depth; do not count it twice. Current fee/capacity and pool registry need state proof.
- **Scallop:** candidate lender; use ScallopQuery for read-only state only. Avoid ScallopClient defaults that sign/execute. 0.1% is a cited documentation snapshot, not a current invariant. Verify current per-asset cap, fee and package state before selecting.
- **Bucket:** restricted candidate for USDB flash mint/loan. USDB is not USDC. Current module, exact fee, capacity and repay/PSM path need proof.
- **Cetus / Aftermath / FlowX:** market routing venues, not general-purpose flash lenders in the reviewed source pack. Do not add them to FlashCapitalGraph as lenders.
- **Suilend:** research-only until a general public flash-loan ABI, fee, pool and capacity are verified.

Lender selection for each route:
1. Same chain and exact borrowed CoinType.
2. Effective live capacity >= principal + protocol-specific buffers; no TVL shortcut.
3. Flash fee, rounding, caps, enabled state, object/package version and freshness all proven.
4. The builder supports atomic repayment inside the same PTB.
5. Full route still satisfies minimum output and positive net economics.
6. Choose one lender per plan unless a documented atomic multi-lender primitive is independently proven.

## 5. Identity/units safety examples

- Native SUI is 0x2::sui::SUI, not the ticker alone.
- Native USDC and each bridged stable representation remain separate exact type tags.
- Token decimals come from current metadata, never assume 9.
- Amounts stay integer base units; NAVI max/fee decimal strings must not round-trip through JS floating-point.
- For DeepBook, orderbook pool depth and flash capacity share resource contention: one unique resource identity.
- Pair existence is a runtime fact. A pair family in this document is a discovery hint, not a static enabled strategy.