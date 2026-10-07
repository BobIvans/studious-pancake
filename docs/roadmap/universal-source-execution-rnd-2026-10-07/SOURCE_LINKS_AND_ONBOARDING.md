# Source Links + Onboarding

This file is the registration/integration navigation map for the provider matrix.

## Solana quote/build

### Jupiter
- Platform/pricing: https://developers.jup.ag/pricing
- Role: reference/meta-router + separate transaction submission/execute lanes.
- Free general API: 1 RPS. Execute/submit buckets are separate.
- Secret: `JUPITER_API_KEY`.

### 0x Solana
- Introduction: https://docs.0x.org/svm/solana-swap-api/introduction
- Get started: https://docs.0x.org/svm/solana-swap-api/guides/get-started-with-solana-swap-api
- Swap instructions: https://docs.0x.org/api-reference/solana-swap-ap-is/swap/instructions
- Role: alternate quote + composable instruction builder.
- Secret: `ZEROX_API_KEY`.

### Titan
- Developer pricing: https://developer.titan.exchange/
- SDK: https://github.com/Titan-Pathfinder/titan-sdk-ts
- Role: provider/meta-route race + transaction/instruction builder.
- Secret: Titan API key.

### OpenOcean
- Solana API: https://docs.openocean.finance/docs/solana-swap-api
- API pricing/access: https://docs.openocean.finance/docs/swap-api/api-pricing-and-access
- Role: correlated Jupiter+Titan comparator.
- Secret/access: API key / plan as applicable.

### OKX DEX
- Developer docs: https://web3.okx.com/onchainos/dev-docs
- Role: alternate Solana/Sui aggregator + transaction data.
- Secret: OKX developer credentials.

### Rango
- API key/rate limits: https://docs.rango.exchange/api-integration/api-key-and-rate-limits
- transaction samples: https://docs.rango.exchange/api-integration/basic-api-single-step/sample-transactions
- Role: universal Solana/Sui/cross-chain route/builder.
- Secret: Rango API key.

## Solana radar / direct context

- DEX Screener: https://docs.dexscreener.com/api/reference
- GeckoTerminal: https://api.geckoterminal.com/docs/index.html
- Meteora: https://github.com/MeteoraAg/docs
- Raydium: https://api-v3.raydium.io/docs/
- Manifest: https://github.com/Bonasa-Tech/manifest
- Sanctum: https://learn.sanctum.so/docs/for-developers/sanctum-api
- Vybe: https://docs.vybenetwork.com/
- Birdeye: https://docs.birdeye.so/
- Pyth: https://docs.pyth.network/
- Switchboard: https://docs.switchboard.xyz/

## Sui quote/PTB

### Aftermath
- Router: https://docs.aftermath.finance/for-developers/typescript-sdk/products/router
- Role: route + Transaction builder; can append a route to an existing Transaction.

### Cetus Aggregator
- Getting started: https://cetus-1.gitbook.io/cetus-developer-docs/developer/cetus-aggregator/getting-started
- Role: multi-DEX SOR + PTB composition.

### DeepBook
- SDK/constants: https://github.com/MystenLabs/ts-sdks/tree/main/packages/deepbook-v3
- Role: direct CLOB state/build + exact verification + flash-capital research.

### Rango Sui
- same Rango API docs as above.
- Output includes `unsignedPtbBase64`.

### Additional meta-router candidates
- 7K/Bluefin7K
- FlowX MetaAggregator
- OKX DEX Sui

Before activation, re-pin their official endpoint/package/version and provider overlap into a SourceDossier.

## Sui context/capital

- Scallop: https://docs.scallop.io/
- NAVI SDK: https://sdk.naviprotocol.io/
- Sui data access: https://docs.sui.io/develop/accessing-data/
- Aftermath: https://docs.aftermath.finance/
- Cetus: https://cetus-1.gitbook.io/cetus-developer-docs/

## Solana rent / capital

### Slumlord
- Source: https://github.com/igneous-labs/slumlord
- Program: `s1umBj7CEUA6djs6V1c6o2Nym3QrqF4ryKDr1Nm1FKt`
- Role: zero-fee SOL rent flash financing, not trading capital.

### Project 0
- Docs: https://docs.marginfi.com/typescript-sdk/
- Role: Solana flash capital.

### Kamino
- SDK: https://github.com/Kamino-Finance/klend-sdk
- Role: reserve-specific flash-capital candidate.

## TON

- STON API: https://docs.ston.fi/developer-section/dex/api/reference
- Omniston: https://docs.ston.fi/developer-section/omniston
- DeDust: https://docs.dedust.io/
- TON docs/data: https://docs.ton.org/
- Rango can provide TON transaction-message flows where supported.

Also onboard swap.coffee, Tonco, TON Center and TonAPI through reviewed SourceDossiers before high-frequency use.

## Secret hygiene

Never commit provider keys or wallet private keys.

Provider API credentials go in environment secret references.

Signing keys remain in the local signer/wallet boundary and are never sent to quote/build providers.
