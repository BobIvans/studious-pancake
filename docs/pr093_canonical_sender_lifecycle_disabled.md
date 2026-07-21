# PR-093 — Canonical sender lifecycle integration, still disabled

This PR is the roadmap PR-093 safety layer. It makes the canonical sender
lifecycle reviewable after the earlier sender lifecycle boundary, but it does
not enable live submission.

## What this PR adds

- `src/submission/sender_lifecycle_disabled.py`
  - digest-pinned upstream evidence references;
  - required PR-086/087/091/092 evidence names;
  - required lifecycle controls for exact permit/message binding, Jito
    exactly-one-tip evidence, ACK/status separation, durable ambiguity and
    no automatic resend;
  - required submission outcomes for accepted, landed, failed, expired and
    unknown;
  - required RPC/Jito transport contract coverage;
  - hard checks that compile-time, config and supported-command submission
    remain disabled.
- `tests/test_pr093_canonical_sender_lifecycle_disabled.py`
  - proves the package can become review-ready while all runtime submission
    booleans remain false;
  - blocks missing or unreviewed evidence;
  - blocks supported command submission, automatic resend, non-canonical sender
    ownership, wrong outbox topic and missing status coverage.

## Safety boundary

A passing PR-093 result means only:

```text
ready-disabled-for-review
```

It does not mean live-ready or canary-ready.

The evaluator returns:

```text
live_allowed = false
runtime_submission_enabled = false
supported_command_can_submit = false
automatic_resend_enabled = false
```

This PR does not build a sender, does not sign, does not submit, does not poll,
does not resend and does not mutate wallet or runtime state.

## Relationship to the roadmap

The snapshot-7 roadmap says PR-093 should happen only after real security and
shadow-soak evidence. This patch therefore consumes evidence names for PR-091
and PR-092 instead of fabricating those artifacts. Until real reviewed evidence
exists, the evaluator fails closed.
