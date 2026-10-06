# GPR-03 source contracts and qualification limits

`config/gpr03_sui_source_pins.json` retains source commit, path and SHA-256
from official repositories read through the existing HTTPS Git proxy. External
SDK code was inspected, never installed or executed. These are source contracts;
successful production endpoint reads must be measured separately.

The GraphQL source is MystenLabs/ts-sdks commit
`045187f24721f4590203e13731bfe1174713f74f`,
`packages/sui/src/graphql/generated/schema.graphql`. Its reviewed fields include:

```graphql
type Query {
  chainIdentifier: String!
  checkpoint(sequenceNumber: UInt53, digest: String): Checkpoint
  coinMetadata(coinType: String!): CoinMetadata
  object(address: SuiAddress!, version: UInt53, rootVersion: UInt53,
         atCheckpoint: UInt53): Object
}
type Checkpoint {
  sequenceNumber: UInt53!
  digest: String
  timestamp: DateTime
  epoch: Epoch
  query: Query
}
type Object {
  address: SuiAddress!
  version: UInt53
  digest: String
  asMoveObject: MoveObject
}
type MoveObject { contents: MoveValue }
type MoveValue { type: MoveType, bcs: Base64, json: JSON }
```

`Checkpoint.query` scopes nested object and coin metadata reads to the specified
checkpoint. The initial checkpoint request obtains a context; the next request
uses that exact sequence number. No latest-state mixture, cursor pagination,
GraphQL mutation, legacy Sui JSON-RPC or PTB execution is permitted. The source
schema supports these templates; source inspection alone does not establish
that the current hosted endpoint is available or has deployed that schema.

DeepBook's reviewed generated `pool.ts` at the same source commit shows a
`Pool` containing a versioned inner object, and `PoolInner` containing book,
state, vault and fee-related inputs. A root object or `/all_pools` row does
not prove dynamic book depth or current fee rules. All nine original DeepBook
identifiers stay research references until these separate objects and BCS
layouts are qualified. The indexer's exact response field contract remains
unreviewed; missing canonical pool/coin types are retained schema rejections.

Aftermath's `Pools.getAllPools` uses a read-only POST with `{}` at
`https://aftermath.finance/api/pools`; pool coin types are dictionary keys and
pool identity is `objectId`. Cetus's official configuration names
`https://api-sui.cetus.zone/v2/sui/stats_pools`; index rows without exact Move
coin types remain rejected research evidence. Scallop's official indexer uses
`https://sui.apis.scallop.io/api/market/migrate`; `coinType`, `conversionRate`,
`supplyApy`, `borrowApy` and `updatedAt` are retained as structural reference
inputs. Lending APY is never substituted for a staking exchange rate. The
campaign quotas are conservative engineering subcaps, not claimed public plans.

The HARD_BOUND path reconstructs standard `0x2::coin::CoinMetadata<T>` BCS
UID/decimals/name/symbol/description/icon contents with bounded canonical lengths.
Other packages using the same module/type suffix are rejected. Coin Registry
`Currency` layouts and regulated-token additional semantics are unsupported
until separately source-pinned; no compatibility flag bypasses the decoder.

No production DeepBook/AMM depth/fee decoder is installed in this slice.
An explicitly pinned decoder must bind exact venue Move package/module/type,
object/version/checkpoint, actual coin types, metadata BCS hashes, lot/tick sizes,
bid/ask depth and fee semantics. The deterministic positive test's inline JSON
BCS fixture is a test contract, not a production decoder or mainnet proof.

Two genuinely independent, non-smoke governed providers, reviewed network genesis
binding, current startup identity/decimals policy and complete issuer/origin/
bridge representation proofs are mandatory. Default public sources are smoke
only and cannot produce HARD_BOUND receipts. The published GPR-01 registry is
preserved; missing supplemental provenance remains a qualification blocker.

XAUM/XAU requires a reviewed oracle feed identity, entitlement and unit/time
semantics. This slice does not invent a feed identifier or oracle credential.
Representation basis, exchange-rate residuals and DeepBook/AMM divergence remain
unmeasured whenever those actual inputs are missing.
