# MEGA-PR-03 CP2 isolated signer and bounded submission gate

This checkpoint adds a side-effect-free evidence contract for the second
MEGA-PR-03 checkpoint.

It does not enable live trading. It does not start a signer, open IPC, load a
private key, build a transaction, sign, submit, call RPC/Jito, or consume a real
canary permit.

## Scope

CP2 covers the signer and bounded-submission half of the mega PR:

- isolated signer process identity and digest-pinned signer image;
- protected key authority through HSM/KMS or owner-only key source;
- no private key access from the runtime container;
- exact message identity derived by the signer from message bytes, not caller
  metadata;
- durable replay store and authorization outbox;
- blockheight/expiry bounded permit semantics;
- one selected transport with bounded attempts and staged write evidence;
- durable intent before any network send;
- no blind resend for unknown outcomes;
- ACK, bundle ID and confirmed status are not economic truth;
- Jito unbundling/rebroadcast safeguards and transaction-local assertions;
- release-bound canary preconditions with two distinct human approvers and
  absolute budgets.

## Acceptance added by this checkpoint

- `src/live_boundary/mega_pr03_cp2_isolated_signer_submission_gate.py`
  defines immutable CP2 evidence and deterministic fail-closed reporting.
- `tests/test_mega_pr03_cp2_isolated_signer_submission_gate.py` covers the happy
  path plus fail-closed regressions for signer metadata trust, key exposure,
  message mutation after simulation, stale blockheight, overlong permit TTL,
  blind resend, ACK/confirmed-as-finality, missing Jito safeguards, missing
  MEGA-PR-02 dependency and live/unrestricted enablement requests.

## Safety boundary

A passing report permits only CP3 finalized-settlement review:

```text
cp3_finalized_settlement_review_allowed=true
bounded_canary_review_allowed=true
live_execution_allowed=false
unrestricted_live_allowed=false
automatic_scale_up_allowed=false
```

The complete MEGA-PR-03 must remain draft until CP2, CP3 and CP4 are wired to
the exact installed artifact and independently reviewed.
