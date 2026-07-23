# PR-199 isolated signer, exactly-once submission and finality scaffold

This PR is the first safe implementation slice for roadmap PR-199 from the consolidated seven-PR production plan.

## Scope

The added `flashloan_isolated_signer.pr199` module models the live boundary without enabling live execution:

- accepted PR-198 sender-free evidence is required before a PR-199 admission policy can issue metadata permits;
- a semantic authorization digest binds attempt, generation, plan hash, message hash, wallet, provider, market, reservation, session, nonce, config generation, program/account/amount hashes, fees, expiry and transport;
- limited canary bounds are enforced before a durable submission intent is prepared;
- durable intent storage is exactly-once by idempotency key and rejects conflicting signed payload hashes;
- transport dispatch is compile-time disabled and does not call a transport implementation;
- a transport ACK can only move an intent to `acknowledged`; finality requires explicit chain reconciliation evidence;
- status reports expose no private-key loader, no network transport implementation and no automatic scale-up.

## Safety boundary

This PR intentionally does **not** implement:

- key loading;
- transaction signing;
- Jito or RPC network submission;
- automatic retries;
- live capability activation;
- canary scale-up;
- accounting as if a Jito/RPC acknowledgement were finalized settlement.

The code is a reviewable policy and durability scaffold only. The next accepted implementation slice must connect this to the canonical PR-195 lifecycle store and PR-198 evidence bundle before any production live gate can be considered.

## Verification

Focused verification checks:

```bash
PYTHONPATH=isolated_signer_service/src python -m pytest -q tests/test_roadmap_pr199_isolated_submission_boundary.py
python -m black --check \
  isolated_signer_service/src/flashloan_isolated_signer/__init__.py \
  isolated_signer_service/src/flashloan_isolated_signer/pr199.py \
  tests/test_roadmap_pr199_isolated_submission_boundary.py
python -m compileall -q isolated_signer_service/src/flashloan_isolated_signer tests/test_roadmap_pr199_isolated_submission_boundary.py
```

## Roadmap dependency note

The consolidated roadmap states that PR-199 depends on accepted PR-198 real sender-free evidence and opens only a minimal live path after that acceptance. This scaffold preserves that ordering by requiring explicit `PR198AcceptanceEvidence` and by keeping live submission disabled at compile time.
