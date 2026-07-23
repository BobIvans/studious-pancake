# PR-197 — bounded data/provider plane foundation

This patch starts the new consolidated roadmap **PR-197 — unified bounded data/provider plane** without reusing the older merged PR-197 archive-resubmission scope.

## Safety boundary

No live trading, wallet loading, signer access, transaction construction or transaction submission is introduced. The implementation is a sender-free provider/data authority foundation that can be wired into PR-196/199 later.

## What this slice enforces

`src/data_plane/bounded_provider_plane_pr197.py` adds fail-closed primitives for:

- endpoint validation with mandatory host allowlists and DNS resolve-and-pin evidence;
- private, loopback, link-local, multicast, reserved and unexpected CIDR rejection;
- absolute retry budgets tied to one freshness deadline;
- bounded provider response admission with content-type, content-length, gzip decompression, duplicate-key, non-finite JSON and JSON-depth checks;
- SQLite-backed cross-process quota reservation per provider/API-key fingerprint;
- deterministic discovery cycle IDs and deterministic snapshot tie-breaking;
- rooted multi-RPC quorum generation with genesis, source-group and state-hash agreement;
- durable webhook inbox semantics where authenticated body persistence and deduplication happen before an HTTP 200 decision;
- sender-free evidence reports that explicitly keep live/signer/sender/submission disabled.

## Findings covered by this foundation

This directly targets the new audit findings around shared transport bounds, host/DNS allowlists, absolute retry freshness, response buffering, account-wide Jupiter quota ownership, deterministic discovery identity/tie-breaks, rooted RPC coherence, and durable-before-200 Helius acknowledgement.

It intentionally does not claim full PR-197 completion yet. Remaining work includes active adapter cutover, credentialed provider drift artifacts, WebSocket catch-up, legacy Helius isolation/removal, and full integration into the canonical PR-196 runtime kernel.

## Verification

```bash
python -m mypy --config-file mypy.ini src/data_plane/bounded_provider_plane_pr197.py
python -m pytest -q tests/test_pr197_bounded_provider_plane.py --disable-socket --allow-unix-socket
python -m py_compile \
  src/data_plane/bounded_provider_plane_pr197.py \
  tests/test_pr197_bounded_provider_plane.py
```

Formatter coverage for this new surface is intentionally not added to `config/format_targets.txt` in this PR because that manifest is currently the highest-conflict parallel-PR hotspot. PR-194 remains the correct vertical for full production-surface Black baseline expansion.

## Rollback

The patch is additive and default-off. Reverting the PR removes the new focused workflow, module, docs and tests without touching active runtime paths or existing provider configuration.
