# PR-030 — canonical four-provider discovery plane

This change turns the existing normalization-only routing skeleton into one failure-isolated discovery boundary.

## Runtime contract

All providers return `NormalizedQuote` with integer base-unit amounts, token decimals, fee metadata, timestamps/slots, response hashes and correlation labels. Provider-specific wire schemas stay inside provider clients.

Capabilities are explicit:

- Jupiter `/swap/v2/build`: composable instructions and the only provider eligible for execution planning.
- OKX: discovery-only until a later promotion gate.
- OpenOcean: quote-only discovery with underlying-source correlation labels.
- Odos: immutable-transaction discovery; never inserted into a MarginFi atomic message.

PR-027 remains the authority for contract admission. A static adapter capability cannot promote a disabled registry entry. PR-031 remains the authority for account-wide Jupiter quota; the PR-030 network client reserves `DISCOVERY` capacity from the shared `JupiterQuotaManager` before issuing a request.

A disabled or failing provider does not stop the remaining providers. Unknown, partial or mismatched schemas fail closed and become typed provider failures.

## Transport boundary

`HttpxJsonTransport` provides bounded deadlines, retries for 429/5xx and transport timeouts, cancellation propagation, HTTPS/host validation, JSON-only responses and redacted diagnostics.

PR-030 does not create a second execution planner and does not enable live trading.

## Verification

```bash
pytest tests/routing/test_pr012_router.py tests/routing/test_pr030_discovery_plane.py -q
flashloan-contracts validate
flashloan-contracts drift
```
