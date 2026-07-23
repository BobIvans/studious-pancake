# PR-205 — Asymmetric qualification and independently verified release evidence

## Purpose

PR-186 executes qualification profiles and records a materialized run. Its legacy
HMAC verdict remains useful as a CI-local integrity record, but a shared secret is
not an acceptable production release authority. PR-205 makes production release
claims fail closed unless an independent verifier validates Ed25519 signatures and
recomputes the qualification semantics from the materialized evidence.

This is the first active slice of roadmap PR-05. It does not claim that the current
repository is production ready and does not enable live trading, signer access or
transaction submission.

## Authority model

A positive release decision requires two separately signed objects:

1. a mandatory qualification-profile policy;
2. an exact release qualification claim.

Both objects are verified through `TrustAnchorRegistry` with `TrustUsage.RELEASE`.
The verifier rejects staged, revoked, expired, wrong-environment and wrong-purpose
anchors. The signed profile policy prevents an untrusted caller from removing a
mandatory profile or lowering the required number of clean environments.

The legacy PR-186 HMAC verdict cannot authorize a production release. It may still
be checked as local CI evidence while callers migrate to the PR-205 verifier.

## Independent semantic verification

`verify_asymmetric_qualification(...)` does not trust the claim's boolean. It
recomputes and checks:

- the canonical PR-186 run hash;
- source-tree digest binding;
- mandatory profile selection and successful execution;
- installed dependency closure;
- isolated interpreter and disabled global site packages;
- network-disabled-after-bootstrap evidence;
- absence of source import leakage;
- production wheel identity;
- wheelhouse identity;
- exact wheel, image, SBOM, provenance and wheelhouse artifact roles;
- two distinct clean-environment run hashes;
- expected source commit, PolicyBundle, environment and release digest;
- release digest recomputation from every artifact byte identity;
- signed-envelope issuance, expiry, domain and maximum TTL.

A cryptographically valid signature over semantically false evidence remains
blocked.

## Filesystem boundary

The independent CLI reads evidence relative to one explicit artifact root. It uses
single-open descriptor traversal and fails closed on:

- absolute paths and `..` traversal;
- symlinks;
- hardlinks;
- non-regular files;
- empty or oversized JSON;
- short reads, growth or inode/size changes during reading;
- invalid UTF-8 or non-object JSON roots.

This prevents path-check-then-reopen races and avoids trusting caller-provided
hashes without reading the materialized artifact.

## Independent verifier CLI

```bash
python scripts/verify_asymmetric_qualification.py \
  --artifact-root /release/evidence \
  --run qualification-run.json \
  --claim release-claim.json \
  --claim-envelope release-claim.envelope.json \
  --profile-policy qualification-policy.json \
  --profile-policy-envelope qualification-policy.envelope.json \
  --trust-registry trust-registry.json \
  --environment production \
  --source-commit <64-hex-commit-identity> \
  --policy-bundle-hash <64-hex-policy-hash> \
  --release-digest <64-hex-release-digest> \
  --output independent-verification.json
```

Exit codes:

- `0`: asymmetric and semantic verification passed;
- `3`: evidence was well formed but release remains blocked;
- `2`: malformed or unsafe evidence input.

## Tests

Focused tests cover:

- successful dual Ed25519 verification;
- materialized run tampering after a claim was signed;
- mandatory-profile reduction attempts;
- revoked and wrong-purpose release keys;
- traversal, symlink and hardlink rejection;
- real `solders` Ed25519 signatures.

## Remaining roadmap PR-05 work

This slice establishes the asymmetric decision authority. Completion of the full
numeric PR-05 still requires release CI to materialize and upload the actual
hash-locked wheelhouse, two freshly constructed clean environments, exact wheel
and image, SBOM and provenance artifacts, and an independently signed verifier
result bound to the release candidate. No release promotion should consume the
legacy HMAC verdict directly.
