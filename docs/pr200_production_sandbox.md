# PR-200 — Reproducible production sandbox foundation

This PR implements the first offline, sender-free foundation slice for the new
consolidated roadmap PR-200.  The uploaded roadmap defines PR-200 as the
production sandbox, operations and cutover boundary: reproducible images,
separate runtime/signer services, deny-by-default egress, external secrets,
read-only runtime hardening, operational runbooks, disaster recovery and legacy
removal before production cutover.

## What this slice adds

`src/production_sandbox_pr200.py` defines a machine-readable production sandbox
manifest validator.  It is intentionally offline and does not parse local secret
files, open sockets, sign transactions, submit transactions, enable Jito/RPC
send paths or switch live mode on.

The validator checks:

- immutable digest-pinned runtime/signer images;
- required source, wheel, image, SBOM, config-generation and protocol-registry
  hashes;
- deny-by-default egress plus explicit HTTPS origin allowlist;
- runtime/signer process split;
- runtime cannot read signer key material;
- signer cannot have arbitrary internet egress;
- read-only root filesystem, no-new-privileges and dropped Linux capabilities;
- no example, sample or placeholder secret source;
- exactly one active submitter at deployment layer;
- signed release pointer, rehearsed rollback and reconciled outstanding attempts.

## Safety boundary

This PR deliberately keeps `live_capability_allowed() == False`.  A valid PR-200
manifest means only that the deployment/cutover policy is coherent enough for
human review and later cutover automation.  It is not a signer authorization,
live trading permit, canary approval or production deployment instruction.

## Deliberate non-goals

This slice does not rewrite Docker Compose, build production images, create a
secret manager integration, deploy a network gateway, run disaster drills, or
remove historical runtime paths.  Those are later PR-200 cutover slices after
PR-199 canary evidence is accepted.

## Focused verification

```bash
python -m pytest \
  tests/test_pr200_production_sandbox.py \
  -q --disable-socket --allow-unix-socket
```

The focused workflow also compiles the PR-200 boundary and runs flake8 critical
syntax/import checks on the new validator and regression tests.
