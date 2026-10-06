# Universe V2 expansion — canonical identities available for research

This file extends the original symbolic universe. It does **not** create one polling loop per pair. Relations are materialized only when market/source evidence exists.

## Solana A-tier additions

New asset nodes:
`hSOL, dSOL, BNSOL, bbSOL, bpSOL, laineSOL, dfdvSOL, sSOL, fragSOL, USDG, FDUSD, EURC, JLP, MET`.

High-priority relation seeds:

```text
SOL/hSOL
SOL/dSOL
SOL/BNSOL
SOL/bbSOL
SOL/bpSOL
SOL/laineSOL
SOL/dfdvSOL
SOL/sSOL
SOL/fragSOL

hSOL/JitoSOL
hSOL/JupSOL
hSOL/INF
dSOL/JitoSOL
dSOL/JupSOL
dSOL/INF
BNSOL/JitoSOL
BNSOL/JupSOL
BNSOL/INF
bbSOL/JitoSOL
bbSOL/JupSOL
bbSOL/INF

sSOL/JitoSOL
sSOL/mSOL
sSOL/JupSOL
sSOL/fragSOL
fragSOL/JitoSOL
fragSOL/mSOL

hSOL/USDC
dSOL/USDC
BNSOL/USDC
bbSOL/USDC
sSOL/USDC
fragSOL/USDC

USDG/USDC
USDG/USDT
USDG/PYUSD
USDG/JupUSD
USDG/USDS

FDUSD/USDC
FDUSD/USDT
FDUSD/USDG
FDUSD/PYUSD
FDUSD/JupUSD

EURC/USDC
EURC/SOL

JLP/USDC
JLP/SOL
JLP/JupUSD

MET/SOL
MET/USDC
```

Structural families:
- ordinary LST relative value;
- restaking/LRT basis (`sSOL`, `fragSOL`);
- JLP market price vs reconstructed protocol NAV;
- EURC vs EUR/USD reference, **not** USD parity;
- same-issuer FDUSD cross-chain reference.

## Sui expansion

High-priority stable/representation graph:

```text
USDC_NATIVE/USDT_SUI_BRIDGE
USDC_NATIVE/USDT_WORMHOLE
USDT_SUI_BRIDGE/USDT_WORMHOLE
USDC_NATIVE/WUSDC_ETH_ORIGIN

USDC_NATIVE/FDUSD
USDC_NATIVE/AUSD
USDC_NATIVE/USDSUI
USDC_NATIVE/suiUSDe
USDC_NATIVE/USDY
USDC_NATIVE/mUSD
USDC_NATIVE/BUCK

AUSD/SUI
FDUSD/SUI
USDSUI/SUI
suiUSDe/SUI
```

BTC representation graph:

```text
XBTC/USDC_NATIVE
XBTC/SUI
ZWBTC/USDC_NATIVE
WBTC_WORMHOLE/USDC_NATIVE
WBTC_SUI_BRIDGE/USDC_NATIVE

XBTC/ZWBTC
XBTC/WBTC_WORMHOLE
XBTC/WBTC_SUI_BRIDGE
ZWBTC/WBTC_WORMHOLE
ZWBTC/WBTC_SUI_BRIDGE
WBTC_WORMHOLE/WBTC_SUI_BRIDGE
```

Sui staking graph:

```text
SUI/afSUI
SUI/haSUI
SUI/vSUI
SUI/scaSUI

afSUI/haSUI
afSUI/vSUI
afSUI/scaSUI
haSUI/vSUI
haSUI/scaSUI
vSUI/scaSUI

afSUI/USDC_NATIVE
haSUI/USDC_NATIVE
vSUI/USDC_NATIVE
scaSUI/USDC_NATIVE
```

For each Sui LST relation compare:
`market price vs staking exchange rate vs instant exit vs direct DEX vs SUI synthetic path`.

## Identity caveats

- `USDC_NATIVE`, `WUSDC_ETH_ORIGIN`, and `USDC_SOL_PORTAL_ON_SUI` are distinct representations.
- `USDT_SUI_BRIDGE` and `USDT_WORMHOLE` are distinct representations.
- Solana `WBTC_WORMHOLE` is not old Sollet BTC.
- `tBTC` remains `REVALIDATE_CURRENT`.
- `sUSDS` remains `UNRESOLVED`.
- Sui `AUSD` remains `REVALIDATE_ISSUER_STATUS`.
- `fragSOL` is a research identity but Token-2022 semantics remain an exact-qualification gate.

## Cross-chain

See `INTERCHAIN_RELATIONS_V2.json`. Cross-chain edges are economic/rebalancing relations only; they are never atomic swap edges in the local execution graph.


---

# V2.1 priority override

The original expansion remains a broad research universe. It is **not** the initial expensive campaign queue.

Use `FIRST_CAMPAIGN_FAMILIES_V2_1.json` as the first 14-family campaign seed.

Important corrections:
- USDG and PYUSD are Token-2022.
- Solana `xBTC_OKX` is a new BTC representation candidate.
- PYUSD/USDG begins as a synthetic relation through USDC; do not invent a direct market.
- Sui `WUSDC_ETH_ORIGIN` is distinct from `USDC_SOL_PORTAL_ON_SUI`.
- XAUM/XAU is a COLD/RESEARCH oracle-market experiment.
- Sui DeepBook priority markets use the explicit pool IDs in `SUI_DEEPBOOK_POOLS_V2_1.json`.

Promotion from the broad universe depends on measured evidence, not the old static tier label.
