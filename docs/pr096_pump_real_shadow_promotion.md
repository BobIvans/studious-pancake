# PR-096 Pump real shadow-promotion evidence gate

PR-096 is an optional Pump protocol track. It is not a live-trading feature and
does not enable canary, sender, signer, RPC/Jito submission, or automatic
promotion.

The gate added by this PR accepts only a materialized, human-reviewed Pump
shadow-promotion package that proves all current Pump families in the repository
manifest have real evidence.

## Required evidence

For each Pump family from `src/venues/pump/manifest.json`, the PR-096 package
must provide:

- current official source URL and pinned source commit;
- current IDL SHA-256;
- account layout vector SHA-256;
- discriminator vector SHA-256;
- read-only RPC fixture SHA-256;
- exact simulation report SHA-256;
- reconciliation report SHA-256;
- Token and Token-2022 policy verification;
- human review.

The package must also include materialized artifact files for official source,
IDL, layout vectors, discriminator vectors, RPC fixtures, token policy, exact
simulation, reconciliation, a separate soak bundle, and operator review. The
gate hashes the bytes under an explicit artifact root and fails closed for
missing files, remote-only URIs, size mismatches, or digest mismatches.

## Relationship to earlier Pump guard

The existing PR-065 guard remains the coarse Pump shadow-soak promotion boundary.
PR-096 is stricter: it requires real source/IDL/RPC/simulation/reconciliation
artifacts and a separate Pump soak package before marking the Pump track ready
for manual shadow review.

## Safety contract

`evaluate_pump_pr096_shadow_promotion(...)` always returns `live_allowed =
False`. A successful result is only `ready-for-manual-shadow-review`; it is not
permission to submit transactions, arm canary mode, or merge a live sender path.

## Suggested verification

```bash
python -m pytest tests/test_pr096_pump_shadow_promotion.py -q
python -m pytest tests/test_pr065_pump_promotion_guard.py tests/test_pr096_pump_shadow_promotion.py -q
python scripts/verify_repo.py --skip-dependency-audit
```

## Remaining operational work

This patch does not create the real Pump run bundle. An operator still needs to
collect current official Pump source/IDL evidence, preserve real read-only RPC
fixtures, run exact simulation and reconciliation, conduct a separate Pump
shadow soak, sign/review the immutable bundle, and point the PR-096 package at
those materialized bytes.
