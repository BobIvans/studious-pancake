# PR-106 — Canonical sender lifecycle integration, still disabled

PR-106 adds the review boundary that sits above PR-080 and PR-093.  It is meant
for proving that the canonical sender lifecycle is internally consistent after
real security evidence and real shadow-soak evidence exist, while live remains
unreachable.

## Scope in this slice

This patch adds `src/submission/canonical_lifecycle_pr106.py`, an offline
fail-closed evaluator.  It checks that:

- PR-104 security/SBOM/provenance/chaos evidence exists, passed and was reviewed;
- PR-105 real 72h shadow-soak evidence exists, passed and was reviewed;
- PR-093 sender-lifecycle-disabled review evidence exists, passed and was
  reviewed;
- the PR-093 readiness object is already review-ready while runtime submission,
  supported-command submission and automatic resend remain disabled;
- lifecycle controls cover exact permit/message/payload identity, RPC/Jito
  evidence-bound transports, isolated signer boundary, exactly-one Jito tip,
  ack-vs-landed separation, signature/bundle status polling, durable unknown
  state, no resend under ambiguity, outbox recovery and compile/config hard
  deny.

## Safety properties

The evaluator always returns:

```text
live_allowed = false
runtime_submission_enabled = false
supported_command_can_submit = false
automatic_resend_enabled = false
```

Any attempt to supply `compile_time_live_enabled`, `config_live_enabled`,
`supported_command_submission_enabled`, `automatic_resend_enabled` or a signer
import path becomes a blocker.

## Non-goals

- no sender construction;
- no signer import;
- no RPC/Jito network I/O;
- no status polling loop;
- no live or canary enablement.

## Suggested verification

```bash
python -m pytest tests/test_pr106_canonical_sender_lifecycle_disabled.py -q
python scripts/verify_repo.py --skip-dependency-audit
```
