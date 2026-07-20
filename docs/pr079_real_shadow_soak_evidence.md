# PR-079 — Real 72h shadow soak evidence package

This PR starts the roadmap PR-079 boundary. It does not claim that a new
72-hour soak was run inside this change. Instead, it defines the immutable
package that a real soak must satisfy before it can be consumed by later
sender/canary work.

## Scope

PR-079 consumes the existing PR-060 `ShadowSoakEvidence` model and adds a
stricter `RealShadowSoakPackage` gate.

The package requires:

- a PR-060 soak evaluation tied to the exact same evidence hash;
- a real `shadow` or `mainnet-read-only` environment, never a recorded fixture;
- at least 72 hours of duration;
- a minimum sample threshold;
- deterministic replay verified after collection;
- a signed immutable artifact bundle;
- zero observed sender usage;
- zero live submissions;
- reviewed upstream evidence for:
  - PR-076 production paper/shadow runner;
  - PR-077 data/lifecycle/observability;
  - PR-078 security/SBOM/chaos evidence.

## Safety boundary

`evaluate_real_shadow_soak(...)` always returns `live_allowed=false`.
A passing result means only:

```text
ready-for-release-evidence
```

It does not enable live mode, sender mode, signer mode, Jito/RPC submission,
canary exposure or automatic trading.

## Why this is fail-closed

A chat or CI run cannot honestly manufacture an actual 72-hour mainnet shadow
soak. This PR therefore rejects placeholder proof and recorded-only fixtures.
Real artifacts must be generated outside the code patch by the operational
runner and attached as immutable digest-pinned evidence.

## Expected future artifact layout

A later operational run should produce a package similar to:

```text
artifacts/pr079/<run-id>/
  raw-events.jsonl
  replay-corpus.jsonl
  metrics.json
  operator-review.md
  immutable-bundle.tar.zst
  immutable-bundle.sig
```

The code only stores digests and review metadata. Raw private keys, signed
transactions, API secrets and live submission payloads must never be included.

## Suggested verification

```bash
python -m pytest tests/test_pr079_real_shadow_soak.py -q
python -m compileall -q src/shadow_soak tests/test_pr079_real_shadow_soak.py
python scripts/verify_repo.py --skip-dependency-audit
```

## Non-goals

- Running the 72-hour soak.
- Generating fake soak data.
- Enabling live or canary.
- Importing sender/signing/submission code.
- Retrying or resubmitting any transaction.
