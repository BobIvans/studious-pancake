# MPR-41 — Trusted provider, webhook and protocol-conformance data plane

This slice adds the fail-closed authority contract for the MPR-41 data-plane cutover.
It is intentionally a reviewable foundation PR: it defines what trusted provider
and webhook evidence must prove before later PRs route the active runtime through
one provider gateway.

## Scope

- Define `trusted-provider-data-plane` evidence.
- Require one deny-by-default transport authority.
- Require TLS, bounded response size, strict JSON, durable quota/retry state and
  persisted provider provenance.
- Require webhook HTTP success only after durable inbox commit.
- Require atomic batch intake, durable NACK/dead-letter handling, timestamp unit
  validation, authenticated routing identity and bounded rate-limit state.
- Add a static scanner for active direct network clients such as ad hoc
  `aiohttp`, `httpx`, `requests`, `urllib` and raw socket construction.
- Keep the runtime default-off: no live, signer, sender or Jito settlement
  authority is enabled by this PR.

## Non-goals

This PR does not yet remove every legacy network client from the tree. The scanner
is introduced first so later commits can turn direct-client findings into a hard
active-runtime gate without relying on hand-written audit notes.

## Suggested checks

```bash
python -m compileall -q \
  src/data_plane/mpr41_trusted_provider_data_plane.py \
  scripts/verify_mpr41_trusted_data_plane.py \
  tests/test_mpr41_trusted_provider_data_plane.py
PYTHONPATH=. python -m pytest -q tests/test_mpr41_trusted_provider_data_plane.py
python scripts/verify_mpr41_trusted_data_plane.py --json
```
