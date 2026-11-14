# TON state providers — TON Center and TonAPI (rate limits verified, method schemas blocked)

**Retrieved:** 2026-11-14 UTC
**Purpose:** record what is verified about the two main TON state-read providers and what is explicitly missing before any state-view adapter may decode their payloads.

## TON Center

- **Canonical URLs:** https://toncenter.com/api/v2 (v2 swagger UI), https://docs.ton.org/api/rate-limit, https://toncenter.com/
- **API versions:** v2 and v3 (both rate-limited by default without a key).
- **Auth:** API key plans via TON docs "Get API key"; unauthenticated requests stay at 1 RPS even with a subscription; keys are per-network.
- **Published limits (verbatim from https://docs.ton.org/api/rate-limit):**
  - "Without any API key, the default rate limit is 1 request per second."
  - Free plan: 1 key, 10 RPS — "Shared liteservers suitable for low-volume testing and small projects."
  - Plus: 3 keys, 25 RPS; Advanced: 10 keys, 100 RPS (private liteservers/infrastructure); Enterprise: custom via `@toncenter_support`.
  - "Rate limits apply to all API keys in total separately for every TON network" (e.g. Plus = 25 RPS shared across all mainnet keys).
  - Over-limit response: HTTP `429` with body `{"ok": false, "result": "Ratelimit exceed", "code": 429}`; docs recommend exponential backoff.
- **Missing pin (`BLOCKED_MISSING_PIN`):** exact request/response schemas for state-read methods (`getAccountState`, `getExtendedAccountInformation`, `runGetMethod`, v3 equivalents) were not captured from the official swagger this wave. No `{"ok": true, "result": ...}` payload decoder may be written from memory.

## TonAPI (tonapi.io)

- **Canonical URLs:** https://tonapi.io/ (official page), swagger UI https://tonapi.io/api-v2, repository https://github.com/tonkeeper/tonapi (API key registration documented there).
- **API version:** REST API v2; production base `https://tonapi.io/v2/` (official page example: `GET https://tonapi.io/v2/accounts/{account_id}`).
- **Verified endpoint families:** `GET /v2/accounts/{account_id}`, `POST /v2/accounts/_bulk`, `GET /v2/blockchain/transactions/{transaction_id}`, `POST /v2/blockchain/message`, `GET /v2/blockchain/config`, `GET /v2/wallet/emulate`; jettons family referenced on the page.
- **Published limits (official pricing tiers):** Start (Free) RPS 1; Lite ($9.9) RPS 10; Standart ($95) RPS 100; Plus ($290) RPS 300; Heavy ($890) RPS 1,000; Custom "Unlimited". Liteservers plan: Free RPS 1; Lite ($50) RPS 10; Custom "Unlimited".
- **Missing pins (`BLOCKED_MISSING_PIN`):** (a) exact response schema of `/v2/accounts/{account_id}` and jetton endpoints; (b) the API-key header name; (c) pagination semantics. No TonAPI state-view adapter may decode unverified field layouts.

## Consequence for the radar

- No TON Center or TonAPI adapter is added in this wave. The existing bounded-polling patterns (budget, timeout, `max_attempts=1`, negative evidence, fail-closed schema decoding, journal replay) are the template to reuse once the missing pins are captured under live-capture authorization.
- The verified TON Center 429 envelope is the negative-evidence fixture shape for any future state adapter; 429 handling must preserve `Retry-After` and never retire a market.
