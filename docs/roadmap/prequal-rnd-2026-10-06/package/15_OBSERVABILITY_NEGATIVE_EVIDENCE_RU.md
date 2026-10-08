# Observability + Negative Evidence

Qualification must store more than wins.

Persist per source:
- 401/403 auth failures;
- 429 + Retry-After;
- timeout/connection/DNS/TLS;
- 5xx;
- schema mismatch;
- missing required fields;
- stale slot/publish time;
- RPC disagreement;
- gap/reconnect/resync;
- rate-limit budget exhaustion;
- unsupported token extension/oracle setup;
- zero candidates / no-trade result.

Why: outages and rejections are part of real strategy capacity. Dropping them creates survivor bias and makes backtests unrealistically clean.

Report both:
`candidate_yield` AND `coverage_failure_rate` by source/venue/time bucket.
