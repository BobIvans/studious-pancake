# PR-2 — Human intervention closure

## Goal

Replace informal human/manual state transitions with one fail-closed,
content-addressed intervention authority. Human review remains an explicit safety
boundary, but a free-form acknowledgement must not itself mutate durable state.

## Canonical authority

`src.human_intervention` composes the existing PR-143 acknowledgement gate rather
than inventing a second human-acknowledgement format.

A permit is bound to all of the following:

- exact intervention action;
- exact subject type and subject identity;
- subject-state/decision hash;
- evidence bundle hash;
- release hash;
- configuration/policy hash;
- short validity window;
- two distinct human acknowledgement packages.

Each acknowledgement must independently pass PR-143 and must bind the same
request, evidence, policy and subject hashes. Bot/CI/automation identities,
auto-approval, stale acknowledgement, mismatched evidence, duplicate approvers
and approval packages that still require manual review all fail closed.

## Durable one-shot consumption

`HumanInterventionLedger` accepts an existing caller-owned `sqlite3.Connection`.
It never opens a second database authority. Issued permits are content-addressed
and can be consumed only for their exact action and target. A successful consume
is one-shot; replay with the same idempotency key is harmless, while reuse by a
different consumer fails closed.

## Safety boundary

The permit explicitly carries:

- `execution_capability_allowed = false`;
- `live_submission_allowed = false`;
- `automatic_scale_up_allowed = false`.

PR-2 does not load private keys, initialize a signer, sign or submit a
transaction, contact RPC/Jito, or enable live mode.

## Verification

- `tests/test_pr2_human_intervention.py` exercises dual control, bot rejection,
  exact-hash binding, expiry, one-shot consumption and cross-target rejection.
- `scripts/verify_pr2_human_intervention.py --json` materializes deterministic
  sender-free evidence and rejects unsafe source ownership.
- The verifier is part of `scripts/verify_repo.py` and the authority is required
  in the production wheel manifest.

## Remaining physical cutover

This PR establishes the canonical intervention permit and durable consumption
contract. Existing manual consumers must not be treated as closed merely because
the authority exists. In particular, `src.canonical_control_plane_pr195.clear_latch`
still needs to require the PR-2 permit at its mutation boundary. The older
`src.execution.live_control` manual surface is already quarantined from the
production package/reachability authority and must remain non-canonical.

Until that physical consumer cutover is completed and verified, PR-2 is an
implemented authority foundation, not a claim that live readiness or all human
intervention debt is closed.
