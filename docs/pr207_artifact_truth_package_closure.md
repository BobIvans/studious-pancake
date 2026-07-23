# PR-207 — Artifact Truth, Package Closure and Hermetic CI

This is the first Pass 6 corrective slice for **PR-207 — Artifact Truth,
Package Closure and Hermetic CI**.

It is intentionally additive, offline and sender-free. It does not enable live
trading, load keys, call RPC/provider services, build transactions, submit
transactions or mutate production release state.

## Why this slice exists

Pass 6 identified that multiple safety gates still prove repository checkout
state or caller-supplied artifact claims instead of the installed artifact that
would actually run in production. PR-207 is the corrective package that makes a
built wheel/image and release set the source of truth.

This slice starts that cutover by adding a deterministic wheel-inspection gate:

```text
pr207.artifact-truth-gate.v1
```

## Files

- `src/pr207_artifact_truth_gate.py`
- `tests/test_pr207_artifact_truth_gate.py`
- `.github/workflows/pr207-artifact-truth.yml`

## Finding coverage started here

| Finding | Coverage in this slice |
|---|---|
| F-217 | The verifier takes a wheel path and inspects wheel bytes instead of checkout manifests. |
| F-221 | Sender-free wheel inspection rejects live/submission/signer-like namespaces. |
| F-222 | The deny surface starts covering `src.submission`, live boundary, signer service, sender and ingest prefixes. |
| F-223 | Entry points and inventory are read from the wheel, not from caller-provided lists. |
| F-224 | Placeholder SHA-256 values are rejected and wheel bytes are re-hashed. |
| F-225 | Wheel metadata and `RECORD` membership are checked for basic closure. |
| F-228 | A release-set digest report requires distinct main and signer wheel digests plus IPC/policy hashes. |

## What this does not complete

This is not the full PR-207 completion. Remaining work must still:

- build the release wheel once in CI and run all safety gates from that installed artifact;
- replace denylist-only policy with allowlist package closure and ownership metadata;
- generate import/call reachability from installed entrypoints;
- scan every production-reachable module for optimize-mode assert removal;
- remove generated/cache/build artifacts from repository snapshots;
- pin all external GitHub Actions to full commit SHA;
- produce one signed release-set manifest for main runtime, signer service, IPC schema and policy bundle.

## Suggested focused verification

```bash
python -m py_compile \
  src/pr207_artifact_truth_gate.py \
  tests/test_pr207_artifact_truth_gate.py
python -m pytest -q tests/test_pr207_artifact_truth_gate.py
```

GitHub Actions remains the source of truth for full repository compatibility.
