# PR-203 — Final promotion governance

## Purpose

This slice adds a final release-governance gate for the consolidated roadmap
PR-203. It is intentionally offline, review-only and sender-free. A green result
means the release package is ready for manual tiny-canary review; it is not a
permit, transaction submission path or live-mode enablement mechanism.

The roadmap requires the final release layer to remove or quarantine legacy
runtime paths, bind independent assurance, cap the first canary, require a
cryptographically-bound second approval, rollback to shadow on uncertainty and
preserve finalized post-canary evidence.

## Scope

`src/release_gate/final_promotion_governance_pr203.py` validates:

- accepted PR-200 soak and PR-201 release-manifest prerequisites;
- release wheel/image/import graph evidence proving forbidden legacy paths are
  absent from the supported runtime surface;
- independent reviews for protocol vectors, signer/permit, transaction firewall,
  accounting and failure recovery;
- tiny-canary budget: one strategy/pair, one release/config hash, one first
  transaction, explicit fee/tip/loss/uncertainty caps and no automatic scale-up;
- two distinct approval roles bound to the same release/config hashes and valid
  at assembly time;
- rollback-to-shadow triggers for invariants, SLOs, provider drift, balance
  mismatch, ambiguous settlement and approval expiry;
- mandatory post-canary finalized evidence and a new review for any staged
  expansion.

## Safety properties

The result always returns `live_execution_allowed=false`,
`canary_submission_allowed=false` and `automatic_scale_up_allowed=false`. The
module can only produce review readiness. Runtime arming must still be handled by
later signer/permit/sender boundaries and by manually-reviewed operational
controls.

## Deliberate limits

This slice does not delete legacy files, rewrite packaging, fetch external
provider evidence, sign approvals with a real trust anchor or submit a canary
transaction. It gives those later artifacts a single typed acceptance boundary so
PR-203 can fail closed when any of them are missing, stale or contradictory.
