# PR-107 — Reviewed limited-live canary package gate

This PR adds a review-only PR-107 package gate for the roadmap's reviewed
limited-live canary step.

It intentionally does not arm a canary, submit a transaction, import a sender,
access a signer, call RPC/Jito, or make any CLI command capable of live trading.
A passing result only means the package is ready for manual review.

## Required evidence

The PR-107 package must reference reviewed and passing upstream evidence:

- PR-104 security/SBOM/provenance/chaos package.
- PR-105 real shadow soak bundle.
- PR-106 sender lifecycle disabled evidence.

## Required controls

- tiny maximum exposure;
- exactly one outstanding submission;
- reviewed pair/provider/program allowlist;
- protected wallet reserve;
- loss/failure/stale/ambiguity/indeterminate latches;
- manual kill switch;
- post-trade reconciliation requirement;
- rollback to shadow without code changes;
- isolated signer boundary review;
- release/security/risk/operator sign-offs.

## Safety boundary

The evaluator always returns:

```text
default_live_enabled = false
runtime_live_enabled = false
supported_command_can_submit = false
```

This keeps PR-107 compatible with parallel roadmap work while preventing a
review package from becoming an env-only live enablement path.
