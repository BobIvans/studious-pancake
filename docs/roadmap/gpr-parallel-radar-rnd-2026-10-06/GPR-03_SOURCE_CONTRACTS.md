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
state, vault and fee-related inputs. A root object or indexed pool row does
not prove dynamic book depth or current fee rules. All nine original DeepBook
identifiers stay research references until these separate objects and BCS
layouts are qualified. The corrected indexer contract is source-pinned to
MystenLabs/deepbookv3 commit `6f73d976320b3dea9697938cdcb9bebbd5ed3de2`,
`crates/indexer/deepbook-indexer-openapi.yaml`: `GET /get_pools` returns pool IDs,
names and Move types. `GET /orderbook/{pool_name}?depth=20&level=2` supplies an
indexed book reference. Three stable-family names are matched against both
published seed IDs and current index rows. They share provider/operator/
correlation ownership and supply no independent checkpoint/depth/fee proof.

Aftermath's `Pools.getAllPools` uses a read-only POST with `{}` at
`https://aftermath.finance/api/pools`; pool coin types are dictionary keys and
pool identity is `objectId`. Aftermath alone has a pinned 2 MiB/60,000 JSON-node
engineering subcap after the first campaign measured HTTP 200 exceeding 1 MiB.
Normalization scans at most 512 rows and retains a truncation count; common
transport and other profiles keep their existing bounds.

Cetus's official configuration names
`https://api-sui.cetus.zone/v2/sui/stats_pools`; index rows without exact Move
coin types remain rejected research evidence. Its deployed `code=0/data.lp_list`
shape is pinned to the first immutable campaign's raw export; the original
schema rejection is retained. Scallop's `IndexerDataSource` source-pins the
SDK host, `https://sdk.api.scallop.io/api/market/migrate`; `coinType`, `conversionRate`,
`supplyApy`, `borrowApy` and `updatedAt` are retained as structural reference
inputs. Lending APY is never substituted for a staking exchange rate. The
campaign quotas are conservative engineering subcaps, not claimed public plans.

POST reads carry explicit pinned Accept/Content-Type and the exact serialized
body Content-Length and `Accept-Encoding: gzip,deflate,identity`, matching the
canonical transport supported decoders. Sent public request bytes, their hash, actual header length
and negative response bytes are retained to distinguish an application schema
error from any deployed proxy/server request-contract failure.

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


Every MystenLabs source alias shares one conservative operator quota pool:
12 requests/cost units per 60 seconds, zero spend and concurrency one. Distinct
source generations bind each exact endpoint/schema/adapter; a separate shared
quota generation binds operator, credentials and these limits. This prevents
aliases from receiving independent budgets or conflicting durable dependency
generations. Campaign profile attempt caps also remain active. Deterministic
in-memory and durable restart tests verify aggregate exhaustion before any send.
Physical-attempt retention begins only after the canonical governance guard
issues the lease. Retained final quota snapshots record actual accounting.

Public book references validate the pinned string price/size shape, source
millisecond timestamp, best-to-worst order, requested total depth <=20, positive
finite bounded numbers and non-crossed top levels. Summary top levels and exact
rational midpoint spreads describe the observed index only; they never supply
checkpoint state, qualified depth/fees, executable profit or a verified anomaly.

Known book read requests require exactly GET `depth=20&level=2`; depth zero,
unreviewed values and oversized/non-ASCII/non-string query values are rejected
before transport. The immutable final capture already uses this finite template.
