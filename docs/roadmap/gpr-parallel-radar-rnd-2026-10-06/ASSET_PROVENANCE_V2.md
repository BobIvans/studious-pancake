# Asset Registry V2.1 — provenance and revalidation map

This file records the R&D provenance targets for `ASSET_REGISTRY_V2.json`.

It is not exact execution proof.

## V2.1 identity corrections

### Solana

- `USDG` = `2u1tszSeqZ3qBWF3uNGPFc8TzMk2tdiwknnRMWGWjGWH`, **Token-2022**.
- `PYUSD` = `2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo`, **Token-2022**.
- `xBTC_OKX` = `CtzPWv73Sn1dMGVU3ZtLv9yWSyUAanBni19YWDaznnkn`, SPL research identity.
- `cbBTC` remains a separate BTC representation.
- `JLP` remains a NAV-bearing LP identity, not a fixed-dollar stable.

Token program must be verified as part of identity; never infer program from symbol.

### Sui

Distinct USDC representations:
- `USDC_NATIVE` = native Sui USDC.
- `WUSDC_ETH_ORIGIN` = generic Wormhole wUSDC currently used on Sui, origin Ethereum.
- `USDC_SOL_PORTAL_ON_SUI` = Wormhole Portal USDC specifically originating from Solana.

Never deduplicate these by ticker.

Distinct USDT representations:
- `USDT_SUI_BRIDGE`
- `USDT_WORMHOLE`

Distinct BTC representations:
- `XBTC`
- `WBTC_WORMHOLE`
- `WBTC_SUI_BRIDGE`
- `ZWBTC`

`XAUM` is a separate tokenized-gold representation with decimals=9 and Pyth XAU/USD as an oracle/reference anchor.

## Key V2.1 provenance targets

| Identity/family | Refresh source |
|---|---|
| USDG | https://docs.paxos.com/guides/stablecoin/usdg/mainnet |
| Solana xBTC_OKX | current OKX xBTC deployment material |
| BNSOL | current Binance BNSOL deployment material |
| bbSOL/hSOL/dSOL | current issuer + Sanctum/stake-pool material |
| JLP | current Jupiter token + JLP NAV material |
| Sui DeepBook identities/pools | https://github.com/MystenLabs/ts-sdks/blob/main/packages/deepbook-v3/src/utils/constants.ts |
| Sui LST/XAUM supported assets | https://github.com/scallop-io/scallop-skills/blob/master/references/supported-coins.md |
| Solana-origin USDCsol on Sui | https://docs.sui.io/onchain-finance/fungible-tokens/sui-bridging |

## DeepBook read-only pool seeds

See `SUI_DEEPBOOK_POOLS_V2_1.json`.

Pool IDs are identifier evidence only. Before exact use verify:
- object/pool identity;
- coin types;
- checkpoint/object version;
- live book/depth;
- fee semantics;
- provider/correlation provenance.

## Existing caveats retained

- Solana `WBTC_WORMHOLE` must not alias old Sollet BTC.
- Solana `tBTC` remains `REVALIDATE_CURRENT`.
- Solana `sUSDS` remains `UNRESOLVED`.
- Sui `AUSD` remains `REVALIDATE_ISSUER_STATUS`.
- Token-2022 identity does not waive extension/transfer-fee/authority qualification.

## HARD_BOUND receipt

Before exact use persist a machine-readable receipt with:
- asset_id;
- chain;
- canonical_identifier;
- owner/program or Move type;
- decimals;
- standard/extensions;
- origin_chain / bridge / issuer where material;
- checked_at;
- source URL/hash/revision where practical;
- direct chain-state identity evidence;
- deprecation/replacement status;
- resulting evidence/verification state;
- campaign/repository generation.

The receipt is the transition from research identity toward exact use; the registry row alone is not.
