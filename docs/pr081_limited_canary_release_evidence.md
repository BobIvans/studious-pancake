# PR-081 — Limited canary and production release evidence

PR-081 is the final release-evidence boundary before a human-controlled canary.
It is intentionally offline: it evaluates pinned artifacts and explicit human
authorizations, but it does not import a sender, sign, submit, poll, retry, or
mutate runtime live configuration.

## Scope

The gate consumes:

- PR-079 real shadow soak readiness;
- PR-078 security/SBOM/chaos evidence;
- PR-080 sender/outbox conformance evidence;
- a multi-step human enablement sequence;
- a pair/provider/program allowlist;
- tiny exposure and protected reserve limits;
- exactly one outstanding submission policy;
- loss, failure, stale-data, ambiguity, manual kill-switch and indeterminate
  outcome latches;
- a release manifest with code SHA, config fingerprint, contract pins, SBOM,
  image digest/signature, evidence hashes and rollback-plan hash.

## Safety boundary

A passing `evaluate_limited_canary(...)` result means only that the package is
ready for manual canary release review. It still returns:

```text
default_live_enabled = false
runtime_live_enabled = false
```

Runtime live enablement remains an explicit external operator action guarded by
configuration, permit, outbox and sender controls. This PR does not arm those
controls.

## Required latches

Every latch must be present, armed, tested and proven to block when triggered:

- loss-limit;
- failure-limit;
- stale-data;
- ambiguity;
- manual-kill-switch;
- indeterminate-outcome.

An open indeterminate outcome blocks readiness. Rollback to shadow must require
no code change.

## PR-080 evidence expected later

Because PR-080 may be applied in parallel, PR-081 does not import PR-080 code.
It consumes a digest-pinned sender conformance evidence record instead. That
record must prove:

- exact-message permit enforcement;
- fake acknowledgements cannot become landed;
- restart from unknown is idempotent;
- no resend under ambiguity;
- live gate is closed by default;
- one outstanding submission is enforced.

## Suggested focused verification

```bash
python -m pytest tests/test_pr081_limited_canary_release.py -q
python -m black --check \
  src/release_gate/limited_canary.py \
  tests/test_pr081_limited_canary_release.py
python -m compileall -q src/release_gate tests/test_pr081_limited_canary_release.py
```

Full repository verification:

```bash
python scripts/verify_repo.py --skip-dependency-audit
```

## Non-goals

- No live trading enablement.
- No sender import.
- No signer or wallet mutation.
- No RPC/Jito submission or polling.
- No retry/resend behavior.
- No dependency on unmerged PR-080 implementation files.
