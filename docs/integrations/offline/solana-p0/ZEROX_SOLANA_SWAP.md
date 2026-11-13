# 0x Solana Swap API — offline contract extract

**Official source page:** https://docs.0x.org/api-reference/solana-swap-ap-is/swap/instructions  
**Markdown page:** https://docs.0x.org/api-reference/solana-swap-ap-is/swap/instructions.md  
**Reviewed:** 2026-11-13. Current page identifies this Solana API surface as Open Beta. Re-fetch the official page and refresh source hashes before any live qualification.

## Endpoint

`POST https://api.0x.org/solana/swap-instructions`

Headers:
- `0x-api-key: <locally configured secret>`
- `Content-Type: application/json`

The key is created in the 0x Dashboard. Existing repo's credential reference is `ZEROX_API_KEY`; the current provider docs examples may name the environment variable `ZEROEX_API_KEY`. These are local naming conventions, not wire protocol fields. Codex must inspect `config`, settings and secret references, then choose one canonical internal name without exposing the value or breaking existing deployments.

## Required request body

| Field | Type | Meaning |
|---|---|---|
| `amount_in` | integer/long | Exact input amount in smallest token units |
| `taker` | string | Base58 public wallet address; **public address only**, never secret key |
| `token_in` | string | Input token mint |
| `token_out` | string | Output token mint |

Optional fields include:
- `slippage_bps` (default 50, range 0..10000);
- `disabled_sources`;
- `transaction_version`;
- `recipient`, `sponsor`, transaction space reservation and 0x swap fee parameters.

For P0, do not add optional fields that create extra recipients, sponsor/rent side effects or provider-specific fee arrangements unless the comparison explicitly models them. Record every option in the request evidence.

## Response fields

The documented response includes:
- `amount_out` and `min_amount_out` in output base units;
- `instructions[]` (program id, account metas, data);
- `address_lookup_tables[]`;
- `route_plan[]` with `token_in`, `token_out`, `amount_in`, `amount_out`, `dex_address`, `dex_label`, `dex_program_id`, `ppb`;
- `zid` and optionally `sponsor`.

The official contract does not establish a Solana context slot in the quoted response. Store slot as unknown/null unless independently bound from RPC or a provider field is added to a newer reviewed schema. Do not synthesize a slot.

## Comparison requirements

A 0x response is not automatically comparable to Jupiter:
- same canonical input/output mint identities;
- same exact input base-unit amount;
- same public taker (required by 0x; use the same taker on Jupiter when taker-aware comparison is selected);
- same time window and explicit slippage assumptions;
- record route legs, fee/sponsor/recipient semantics and response freshness;
- compare only quotes that pass response/request identity validation.

Jupiter's default /order router set includes Metis, JupiterZ, Dflow and OKX. Route overlap may mean Jupiter and 0x share a DEX/program or underlying liquidity. Preserve the route program/venue identities and provider correlation groups; don't count two aggregators as independent venue-depth confirmations.

## Safety boundary

The endpoint returns swap instructions. P0 uses these only as evidence for quote capture and route metadata. Do not compile, sign, submit or execute returned instructions. No /execute-like path, account creation, ATA initialization, sponsor payment or token transfer is allowed.

## Missing/unstable contract items

The current public page does not establish a stable machine-readable OpenAPI artifact, provider quota/429 limits for the user's exact account tier, or any context-slot guarantee. Keep these fields explicit in the source manifest as unpinned until captured from a provider-approved current specification/dashboard. A live HTTP 200 alone cannot change this.

