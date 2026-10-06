# Asset Registry V2 — provenance and revalidation map

This file records R&D provenance targets for `ASSET_REGISTRY_V2.json`.

It is **not** a substitute for QPR exact on-chain verification.

## Solana identity sources / refresh targets

| Group | Refresh target |
|---|---|
| SOL / WSOL / core payment tokens | https://solana.com/docs/payments/how-payments-work |
| JitoSOL / JTO | https://www.jito.network/ |
| mSOL | Marinade current token / protocol docs |
| INF and Sanctum LST universe | https://learn.sanctum.so/ and https://app.sanctum.so/explore |
| cbBTC | https://www.coinbase.com/cbbtc |
| PYUSD | PayPal/Solana current deployment material |
| USDe / sUSDe | https://gov.ethenafoundation.com/ |
| hubSOL | https://docs.solanahub.app/developers/hubsol-validator-lst |
| PUMP | https://pump.fun/ |
| USDG | https://docs.paxos.com/guides/stablecoin/usdg/mainnet |
| FDUSD | https://www.firstdigitallabs.com/fdusd |
| hSOL/dSOL/bbSOL/bpSOL/dfdvSOL | current stake-pool / Sanctum discovery state |
| BNSOL | current Binance BNSOL deployment material |
| sSOL | current Solayer code/docs |
| fragSOL | current token/account data; Token-2022 semantics separately qualified |
| JLP | current Jupiter Perps / JLP state and NAV definitions |
| EURC | issuer/current Solana identity + EUR/USD structural reference |

### Critical Solana caveats

- `WBTC_WORMHOLE` is the specific Wormhole representation. Do not alias old Sollet BTC.
- `tBTC` remains `REVALIDATE_CURRENT`.
- `sUSDS` remains `UNRESOLVED`.
- `fragSOL` may be used as a research identity but exact Token-2022 semantics remain blocked until qualified.

## Sui identity sources / refresh targets

| Group | Refresh target |
|---|---|
| DeepBook canonical coins/pools | https://github.com/MystenLabs/ts-sdks/blob/main/packages/deepbook-v3/src/utils/constants.ts |
| protocol-config stable identities | https://github.com/MystenLabs/sui/blob/main/crates/sui-protocol-config/src/lib.rs |
| Scallop supported coins | https://github.com/scallop-io/scallop-skills/blob/master/references/supported-coins.md |
| NAVX | current NAVI SDK/source |
| Sui bridging / Wormhole representations | https://docs.sui.io/onchain-finance/fungible-tokens/sui-bridging |
| afSUI instant exit | https://docs.aftermath.finance/liquid-staking-afsui/faqs |
| Aftermath router | https://docs.aftermath.finance/trade/smart-order-router |
| FDUSD | https://www.firstdigitallabs.com/fdusd |
| USDY | https://ondo.finance/usdy |

### Critical Sui representation rules

Never ticker-alias:
- `USDC_NATIVE` with `USDC_WORMHOLE`;
- `USDT_SUI_BRIDGE` with `USDT_WORMHOLE`;
- `XBTC` with `WBTC_WORMHOLE`, `WBTC_SUI_BRIDGE` or `ZWBTC`;
- `SUI` with `WSOL_WORMHOLE`.

`AUSD` remains `REVALIDATE_ISSUER_STATUS`: protocol/on-chain presence alone is not enough for a stronger current issuer-deployment claim.

## Solana <-> Sui economic links

Refresh targets:
- Sui/Circle CCTP integration and current Circle deployment docs for native USDC;
- Sui bridging docs for Wormhole SOL;
- First Digital deployment material for FDUSD;
- Ondo deployment material for USDY.

These links create research/rebalancing relationships only.

They do not create an atomic cross-chain execution path.

## TON

Primary research source:
- STON.fi API/docs: https://docs.ston.fi/developer-section/dex/api/reference
- STON.fi Python quickstart/deployment examples: https://docs.ston.fi/developer-section/quickstart/python

TON identifiers remain research-only in the current GPR roadmap.

## Revalidation receipt

Before any registry identity can move from research-only toward exact use, create a machine-readable receipt containing at least:

- asset_key;
- chain;
- canonical_id;
- representation;
- checked_at;
- source URL(s);
- source hash/revision where practical;
- direct chain-state identity evidence;
- token standard / extensions;
- decimals;
- issuer/protocol status if relevant;
- deprecation/replacement status;
- resulting verification_status;
- campaign/repository generation.
