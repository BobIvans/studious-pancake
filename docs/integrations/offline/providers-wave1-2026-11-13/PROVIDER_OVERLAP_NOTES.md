# Provider overlap notes — Wave-1 quote/build providers

Purpose: feed future correlation groups. Per PARALLEL_EXECUTION_MANDATE §3 invariant 7 ("Aggregator diversity is not liquidity independence") and R13 ("Two aggregators routing to the same pool are correlated observations, not two independent liquidity sources"), every fact below is recorded from the official sources pinned in the per-provider dossiers (retrieved 2026-11-14 UTC).

## Solana quote-race overlap map

| Provider | Officially documented overlap |
|---|---|
| OpenOcean (Solana) | Meta-aggregates "liquidity from the two major Solana Dex aggregators - Jupiter and Titan" (official overview page). OpenOcean quotes are therefore composites of Jupiter V2 and Titan views — zero independence from either. |
| Titan | Its own quote response is a map keyed by downstream providers (`"Titan"`, `"Metis"`, `"Okx"`, …) with a documented `metadata.ExpectedWinner`. Titan observations include OKX- and Metis-routed legs — one Titan capture can quote the same pools as an OKX capture. |
| OKX DEX | Named router inside Titan's quote map and inside Jupiter's default router set (recorded in the existing 0x extract: "Jupiter's default /order router set includes Metis, JupiterZ, Dflow and OKX"). OKX is also available on Sui (error code 80005; OKX provider in 7K MetaAg). |
| Rango | Multi-chain aggregator; routes through per-route `swappers`/`swapperGroups` attribution that includes Solana DEXs/aggregators; same underlying pools as Jupiter/Titan/OKX whenever its selected swapper does. Rango also serves Sui (`tx.type=SUI`). |
| Jupiter V2 (pinned owner, solana-p0) | Baseline aggregator; OpenOcean wraps it; OKX/Metis/Dflow appear inside its router set (per 0x extract note). |
| 0x Solana (pinned owner, solana-p0) | `route_plan[]` exposes `dex_address`/`dex_label`/`dex_program_id` per leg — the attribution field that lets 0x quotes be mapped onto the same underlying-venue groups. |

**Solana correlation rule for the comparable quote race:** group identity comes from the *underlying venue program + pool ID* recovered from each provider's route fields (0x `route_plan`, OKX `dexRouterList`, Titan per-provider entries + instruction program IDs, OpenOcean decoded `path`/tx, Rango `swappers`). Two providers quoting the same pool contribute one independent-liquidity observation, not two. The only structurally distinct Solana depth in Wave-1 scope is direct pool/program state (P0-3 owners) — every aggregator listed here is a routed view.

**RFQ note:** OKX documents `disableRFQ` and RFQ maker unavailability codes (82001–82003) on the RFQ API; Titan sources external RFQ venues. RFQ fills are inventory-based and can diverge from AMM depth under stress — do not merge RFQ and AMM quotes into one price series without regime tagging.

## Sui quote/PTB overlap map

| Provider | Officially documented overlap |
|---|---|
| Cetus Aggregator | Default provider list (SDK v1.5.5): `deepbookv3, flowx v2/v3, kriya v2/v3, aftermath, turbos, volo, afsui, scallop, springsui, bluefin, haedalhmm&v2, alphafi, steamm..., metastable, obric, haedal(hasui & hawal), momentum, magma, fullsail, cetusdlmm, ferraclmm, ferradlmm, bolt, magmapropamm`. Dedicated on-chain router packages exist per venue (`AftermathRouter`, `FlowxRouter`, `BluefinRouter`, `DeepbookV3Router`, ...). |
| FlowX | `Protocol` enum includes `AFTERMATH`, `SEVENK_V1`, `7K_FUN`, `CETUS`, `BLUEFIN`, `DEEPBOOK`, `DEEPBOOK_V3`, `OBRIC`, `STEAMM`, ... — FlowX routes over Aftermath/7K/Cetus/Bluefin venues directly. |
| 7K / Bluefin7K | Direct `sources` include `aftermath`, `flowx`, `cetus`, `bluefinx`, `obric`, `haedal_pmm`, `sevenk_v1`, `steamm_oracle_quoter*`. The official `@7kprotocol/sdk-ts` MetaAg is itself a comparator over `bluefin7k`, `flowx`, `cetus`, `okx`. |
| Aftermath | SOR routes over named venues (`protocolBlacklist: ["Cetus", "BlueMove"]` examples); Aftermath is simultaneously an underlying protocol inside the Cetus/FlowX/7K provider lists. |
| OKX DEX | Sui surface (error 80005 "Not enough Sui objects under the address for swapping"; OKX provider inside 7K MetaAg with `apiKey`/`secretKey`/`apiPassphrase`/`projectId`). |
| Rango | `tx.type=SUI` documented in sample transactions; same swapper-attribution rule as Solana. |
| Direct DeepBook (existing GPR-03 lane) | The distinct order-book venue; appears as `deepbookv3`/`DEEPBOOK_V3` inside every Sui aggregator above plus `totalDeepFee`/`payDeepFeeAmount` in Cetus. |

**Sui correlation rule:** {Cetus Aggregator, FlowX, 7K/Bluefin7K, Aftermath-SOR, OKX-Sui, Rango-Sui} form one heavily inter-wrapped aggregation family. Independence claims require (a) route attribution showing the selected venue is the aggregator's OWN liquidity (Cetus pools via CetusRouter, FlowX v2/v3/PMM pools, Aftermath AMM pools, BluefinX), and (b) pool-ID equality checks against the direct-state owners. Direct DeepBook depth is the one structurally distinct order-book source; Cetus/FlowX/7K DeepBook legs are index-driven views of the same books and must be de-duplicated against the DeepBook owner.

**Cross-chain footnote:** Rango's core business is cross-chain; same-chain quotes extracted from cross-chain flows carry bridge-fee components — only its single-step same-chain routes are comparable.

## Consequences for the quote race (concrete)

1. Minimum genuinely-distinct Solana comparison set for Wave-2: {Jupiter V2, 0x, Titan-as-executor} + OKX as a fourth view — but all four must be tagged with recovered venue/pool IDs before any "independent" claim; expect heavy overlap.
2. Minimum genuinely-distinct Sui comparison set: direct Cetus pool state + direct DeepBook books + direct Aftermath pools vs each aggregator; aggregator-vs-aggregator comparisons are correlation evidence, not depth confirmation.
3. Any provider-overlap matrix row must carry the exact official quote that documents the overlap (recorded in the dossiers above) — never folklore.
4. Losing quotes retain their venue attribution; a losing quote on an overlapping venue is evidence about venue depth, not about aggregator independence.
