# MPR-12 — Post-completion cutover qualification and regression lock

This slice starts the V6 **MPR-12** package as a fail-closed offline
qualification contract.  MPR-12 is intentionally not another historical
PR-numbered proof layer.  It defines the only evidence shape that may advance a
future paper/live promotion review after MPR-08 through MPR-11 are accepted.

## What this slice enforces

- MPR-08, MPR-09, MPR-10 and MPR-11 must be present as accepted,
  materialized installed generations.
- Qualification evidence must target the clean installed artifact boundary:
  source export, wheel and image.
- Every installed CLI must have a no-network smoke result and consistent exit
  contract.
- V6 adversarial probes must be executed against the installed artifact, not the
  source tree or focused unit-test objects.
- Source-only and test-only evidence are rejected as promotion evidence.
- Old authority/capability schemas are locked out and cannot silently reappear.
- Migration and failed-deployment rollback must preserve the previous generation
  and block promotion.
- The offline bundle must be signed, immutable and independently verifiable.

## What this slice does not enable

This PR does not enable live trading, signer access, sender access, RPC/Jito
submission, production deployment or automatic cutover.  A passing MPR-12 report
allows only promotion review:

```text
promotion_review_allowed=true
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

## Verification

```bash
python -m py_compile \
  src/mpr12_post_completion_qualification_lock.py \
  tests/test_mpr12_post_completion_qualification_lock.py
python -m pytest -q tests/test_mpr12_post_completion_qualification_lock.py
```

## Remaining full MPR-12 work

The next implementation slices should connect this contract to the release
evidence CLI, build the signed wheel/image from MPR-08 through MPR-11, execute
the V6 adversarial probes against that installed artifact, persist the immutable
qualification bundle, and rehearse rollback from the same deployment
generation.
