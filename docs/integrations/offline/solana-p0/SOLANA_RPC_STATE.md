# Solana RPC — account state and identity proof

**Status:** technical contract extract, reviewed 2026-11-13. Canonical references are in `SOURCE_MANIFEST.json`.

## RPC methods used by the three P0 tasks

### `getProgramAccounts`

Use to enumerate accounts owned by a known program. Its filter contract includes `memcmp` and `dataSize` (where supported), encoding and commitment; `withContext` returns a context slot wrapper. The source endpoint/provider must be separately admitted and bounded.

Do not use an indexer's pool label as a program-owner proof. For each result persist:
- pubkey;
- account owner/program;
- lamports and executable flag where applicable;
- data encoding and raw account bytes/hash;
- response context slot;
- RPC endpoint/provider generation;
- commitment and request parameters.

### `getMultipleAccounts`

Use to read a bounded set of already-known pool/mint/vault/tick/bin accounts in one snapshot. The method accepts up to 100 addresses per request and preserves the requested address order in the returned value array. Request a coherent commitment and record the context slot; `minContextSlot` can prevent reading below a known lower bound.

Do not combine unrelated slots as if they were one atomic state. If data requires more than one call, define a slot-skew policy; reject or downgrade snapshots outside the bound.

### `getAccountInfo`

Use for individual mint, vault, program and pool account proofs. Verify the returned account owner and data against a known program/account version before decoding.

### Commitment

- `processed`: freshest view but rollback risk.
- `confirmed`: supermajority voted, but not the strongest finality.
- `finalized`: strongest commitment available from normal RPC; use for durable identity/campaign receipts unless the task explicitly labels a lower-latency provisional observation.

Public shared RPC endpoints are not production infrastructure and can return 429/403. Treat them as discovery/smoke endpoints only unless separately qualified.

## Identity contract

A Solana token identity is not its ticker or symbol. At minimum bind:
- cluster/genesis identity;
- mint public key;
- mint account owner (SPL Token Program vs Token-2022 Program);
- decimals from the mint account;
- initialized/frozen state;
- Token-2022 extensions that alter transfer, fee, hook, pause or default-account semantics;
- source slot/context and raw evidence digest.

For every pool bind:
- pool account address and owning program ID;
- venue/pool family and program version;
- ordered mint A/B identities and token program IDs;
- vault A/B addresses and their mint/owner relationships;
- exact raw account bytes and decoder version;
- snapshot slot and all dependent account slots;
- relationship/alias group for shared underlying liquidity.

Never promote a ticker-only or symbol-only candidate. Unknown owner, extension, discriminator, version or account length must fail closed.

## Indexed discovery is not execution state

DEX Screener, GeckoTerminal, venue metadata APIs and asset registries can suggest candidates and assist pagination. They cannot prove:
- token owner/decimals or Token-2022 extensions;
- pool program ownership;
- current vault balances at a consistent slot;
- initialized CLMM ticks or DLMM bins;
- amount-specific executable output;
- lender capacity or flash-loan rights.

Keep these in separate evidence classes:
`INDEXED_CANDIDATE`, `IDENTITY_VERIFIED`, `POOL_ACCOUNT_VERIFIED`, `VENUE_STATE_DECODED`, `AMOUNT_SPECIFIC_QUOTE`, `PAPER_QUALIFIED`.

An HTTP 200 or non-empty response advances only transport/parse evidence; it does not set execution qualification.

## RPC transport gates

- Enforce source governance, per-source request quotas, response byte bounds, timeouts, 429 Retry-After handling and bounded backoff.
- Persist full request contract (with secrets removed), response hash, source generation, request ID, context slot and timestamp.
- Do not retire pools or identities based on a partial, truncated, timed-out or failed enumeration.
- Store negative results and schema drift as evidence; do not silently retry until a different payload appears.
- Network-disabled replay must consume only retained raw fixtures/journal entries and make zero outbound calls.

