# PR-201 — observability, readiness, deployment and release-image foundation

This patch starts the new consolidated roadmap **PR-201 — Observability,
readiness, deployment, backup/restore and immutable release image**.

## Safety boundary

No live trading, wallet loading, signer access, transaction construction or
transaction submission is introduced. The implementation is an additive,
sender-free evidence authority that can be wired into the PR-196 runtime kernel
and PR-200/PR-202 execution boundaries later.

## What this slice enforces

`src/operations/pr201_observability_readiness.py` adds fail-closed primitives for:

- a management/readiness plane that separates liveness, safe-idle, data
  readiness, paper workload readiness, protocol readiness, DB/outbox health and
  live gate status;
- healthy status being impossible when a mandatory paper worker is dead or
  mandatory evidence is stale;
- SLO evaluation for cycle freshness, durable inbox lag, queue age, provider
  success, reconciliation completeness, shutdown time, recovery time,
  DB contention and the data-loss invariant;
- observability event redaction and bounded label cardinality before logs or
  evidence are exported;
- deployment hardening evidence for non-root runtime, read-only rootfs,
  capability drop, no-new-privileges, seccomp, resource limits, immutable image
  digest, SBOM and attestation hashes;
- backup/restore rehearsal evidence binding state, outbox and accounting hashes
  before and after destructive restore tests;
- immutable release-image manifest binding source commit, lock, wheel, image,
  config, contract evidence and soak artifact hashes;
- a combined operator-readiness report that keeps live/signer/sender/submission
  disabled.

## Findings covered by this foundation

This directly targets the PR-201 roadmap concerns around false healthy/safe-idle
states, stale evidence, absent SLO baselines, secret-safe observability, container
hardening, backup/restore rehearsal, release manifest binding and no
branch-mutating diagnostic workflows.

It intentionally does not claim full PR-201 completion yet. Remaining work
includes active management endpoint cutover, real deployment evidence capture,
real backup/restore artifacts, runbook/alert integration, secret rotation and
provider-drift drills, and release qualification against the exact protected
merge commit/image digest.

## Verification

```bash
python -m pytest -q tests/test_pr201_observability_readiness.py --disable-socket --allow-unix-socket
python -m py_compile \
  src/operations/pr201_observability_readiness.py \
  tests/test_pr201_observability_readiness.py
```

Focused CI intentionally runs behavior and compile gates only. `src/operations`
is not part of the current repository mypy production target; full typecheck and
formatter enrollment for this new surface belong to PR-194's production-surface
quality baseline expansion. This keeps PR-201 from repeatedly conflicting on
shared `mypy.ini` and `config/format_targets.txt` while parallel roadmap PRs are
landing.

## Rollback

The patch is additive and default-off. Reverting the PR removes the focused
workflow, module, docs and tests without touching active runtime paths, provider
configuration, signer/sender code or deployment manifests.
