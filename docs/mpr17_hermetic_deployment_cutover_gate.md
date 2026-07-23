# MPR-17 — Hermetic deployment cutover and final production qualification

This package starts the V7 **MPR-17** boundary as a fail-closed acceptance
contract.  It is not live activation and it does not build images, read
secrets, contact RPC/Jito, start a signer, submit transactions or mutate
deployment state.

## Audit mapping

MPR-17 absorbs V7 findings **F-361…F-365** and integrates completed
MPR-13…MPR-16 evidence before a production-ready claim may be reviewed.

Covered residual blockers:

- dependency truth differs between `requirements.txt`, `pyproject.toml`,
  wheel/container and actual imports;
- Docker builder/runtime images are mutable tag based rather than digest-pinned;
- PM2/source-checkout launch paths can bypass the signed installed artifact;
- legacy setup script creates a stale `.env`/`arb_bot.py` deployment contract;
- isolated intent DB durability and permissions need explicit production policy.

## Contract added

`src/mpr17_hermetic_deployment_cutover_gate.py` defines
`mpr17.hermetic-deployment-cutover.v1`.

The gate requires:

1. Accepted materialized **MPR-13**, **MPR-14**, **MPR-15** and **MPR-16**
   generations.
2. One dependency lock generated from `pyproject`, exact synced, hash locked and
   backed by a signed wheelhouse/SBOM.
3. No forbidden alternate HTTP stack packages such as `httpx2`/`httpcore2` in
   the runtime surface.
4. Digest-pinned builder/runtime base images, wheel/image/provenance/SBOM
   digests and reproducible network-disabled rebuild evidence.
5. Removal or non-promotable status for PM2, source-checkout execution,
   `python arb_bot.py` production launch and `setup_flashloan.sh` legacy
   bootstrap.
6. Production bootstrap evidence for typed config, secret references, sandbox,
   provider registry, authority generations and raw-secret-env rejection.
7. Power-loss, restart, failover, disk-full, clock-step, RPC ambiguity, Jito
   ambiguity and archive-outage drills against the installed artifact.
8. Seven-day sender-free soak and one tiny manual canary using the exact
   production composition with finalized reconciliation.
9. Independent review signatures over exact source commit, image digest,
   dependency lock, policies, stores, soak and rollback bundle.

## Safety boundary

A passing MPR-17 report permits only promotion review:

```text
promotion_review_allowed=true
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
automatic_cutover_allowed=false
```

It does not turn on private keys, live submission, RPC/Jito sends or automatic
cutover.

## Verification

Focused local verification:

```bash
PYTHONPATH=. python -m py_compile \
  src/mpr17_hermetic_deployment_cutover_gate.py \
  tests/test_mpr17_hermetic_deployment_cutover_gate.py
PYTHONPATH=. python -m pytest -q \
  tests/test_mpr17_hermetic_deployment_cutover_gate.py
```

## Remaining full implementation

This first slice is an acceptance contract only.  Follow-up work must wire the
contract into the actual release/build/deployment pipeline, regenerate locks and
SBOMs from the accepted dependency model, delete or disable PM2/source checkout
production paths, enforce digest-pinned images, execute the real 7-day
sender-free soak and tiny canary, and persist the signed offline-verifiable
qualification bundle.
