# Codex task — P0-2: Jupiter V2 + 0x comparable Solana quote capture

**Priority:** P0  
**Mode:** offline contract migration/tests/replay first; real quote capture requires network and local provider credentials.  
**Technical baseline:** `docs/integrations/offline/solana-p0/JUPITER_SWAP_V2.md`, `JUPITER_SWAP_V2.openapi.yaml`, `ZEROX_SOLANA_SWAP.md`.

## Critical known drift

Current `main`'s `src/solana_parallel_radar/cli.py::read_contracts` and `src/solana_parallel_radar/probes.py::jupiter_request` still describe Jupiter V1 `/swap/v1/quote`. The current official Jupiter documentation is Swap API V2. Treat this as a migration, not as a new parallel adapter.

## Assignment

Connect actual Jupiter and 0x Solana quote capture through the existing governed radar, producing same-input, same-pair, near-same-time quote evidence and deterministic replay. No build, signing or submission.

## Required implementation

1. Reconcile config/env names with existing config. Current Jupiter name is `JUPITER_API_KEY`; repo 0x reference is `ZEROX_API_KEY`, while 0x examples may call it `ZEROEX_API_KEY`. Choose one internal 0x canonical name and support compatibility only deliberately. Never reveal secrets.
2. Jupiter: migrate to `GET https://api.jup.ag/swap/v2/order`. Use `inputMint`, `outputMint`, exact base-unit string `amount`; omit `taker` for a quote-only request or use the same public taker as 0x for a taker-aware comparison. Never call `/execute`.
3. 0x: implement `POST https://api.0x.org/solana/swap-instructions`, `0x-api-key` header and exact documented JSON body: `amount_in`, `taker`, `token_in`, `token_out`, optional `slippage_bps`. 0x requires a public taker; do not ask for or load a private key. Do not guess the rate-limit tier.
4. Reconcile native SOL vs WSOL identifiers explicitly. Do not silently substitute an API's native sentinel for the registry's WSOL mint.
5. Normalize each provider into the existing `QuotePreview`/evidence model. Keep provider raw response (redacted), hash, provider generation, route plan, route programs/labels, amount units, slippage settings, fees, observation timestamp, request id and slot if the source actually provides one.
6. Jupiter V2 has aggregator route competition (Metis, JupiterZ RFQ, Dflow, OKX); 0x also routes across venues. Preserve route program identities and provider/venue correlation. Never count aggregator results as independent DEX liquidity confirmations merely because there are two providers.
7. Do not synthesize a slot for 0x. If no context slot exists in the official response, store null and compare only with a separate freshness window / external state evidence.
8. Quote comparison must enforce the same canonical input/output mint, same exact input base-unit amount, explicit public taker mode, bounded time skew and matching fee/slippage assumptions. Do not extrapolate one amount's quote to another amount.
9. Preserve no route, insufficient liquidity, 400, 401/403, 429, 5xx, timeout, bad JSON, malformed route and schema drift as immutable negative receipts.
10. Do not call Jupiter `/execute`, 0x transaction send, RPC sendTransaction, compile with a signer, or construct any signing path. Returned instruction/transaction bytes are inert evidence only.

## Security and user inputs

- List required environment variable *names* and local validation commands.
- Do not paste or request API keys in chat or PR.
- A public taker address is not a private key. If none is locally configured, quote capture for 0x remains explicitly blocked; Jupiter quote-only mode can be tested independently.
- Bounded live requests are opt-in and quota-admitted. Network-offline implementation must work entirely from fixtures.

## Acceptance

- V2 Jupiter fixtures exactly match the pinned V2 OpenAPI schema; no V1 fixture is silently accepted by the V2 parser.
- 0x parser matches the documented body/response, including route_plan and instructions/lookup-table presence.
- Unit tests cover request/response identity, base units, decimals, fee fields, same-size comparator, route overlap, staleness, null slot and all failure classes.
- Real captures from both providers for an identical mint pair/amount/public taker (when credentials and network are supplied) are retained with redaction and replayed offline. If one provider is not accessible, report it BLOCKED; do not use synthetic success as evidence.
- Offline replay makes zero network calls and is clearly distinguished from live capture.
- Comparison remains `execution_authority=false`, `production_promotion=false`.

## Deliverables

A review-only PR updating existing GPR-02 quote owner, exact API contracts and tests; `P0_2_REPORT.md`; example redacted request/response fixtures; source-generation manifest; offline replay command; explicit live blockers.
