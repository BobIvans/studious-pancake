# PR-146 — Bounded provider response parsing

PR-146 is a low-conflict safety slice for the audit finding:

```text
Unbounded response parsing | src/routing/transport.py:146–220
```

The active shared JSON transport previously trusted provider responses enough to
call `response.json()` after retry handling. That left the parser without an
explicit repository policy for response size, declared content length, JSON media
type, nesting depth or node count.

## What this PR adds

- explicit `TransportPolicy.max_response_bytes`;
- explicit `TransportPolicy.max_json_depth`;
- explicit `TransportPolicy.max_json_nodes`;
- optional but default-on JSON content-type requirement;
- content-length pre-check before parsing;
- actual body-size check before parsing;
- fail-closed rejection for non-JSON media types;
- fail-closed rejection for over-nested or over-wide JSON;
- sanitized errors that do not leak query parameters or credentials;
- retry responses are still retried before final JSON parsing.

## Safety / non-goals

- No live trading.
- No sender, signer, wallet, Jito or RPC submission changes.
- No provider credential changes.
- No provider-specific schema adapters in this slice.
- No claim that every provider schema is now fully validated.

Provider-specific schema validation remains owned by each adapter and external
contract admission gate. PR-146 only bounds the shared transport parse surface.

## Suggested verification

```bash
python -m pytest tests/test_pr146_bounded_response_parsing.py -q
python scripts/verify_repo.py --skip-dependency-audit
```
