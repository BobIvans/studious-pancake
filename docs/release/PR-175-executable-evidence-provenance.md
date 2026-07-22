# PR-175 executable evidence production and provenance

PR-175 closes the gap where readiness gates can consume internally valid
caller-supplied descriptors without proving that an active runtime, probe, test,
or settlement pipeline actually produced the evidence.

## What this slice adds

- `RawEvidenceArtifact` records an executable producer result:
  - requirement ID;
  - exact command;
  - source commit;
  - release digest;
  - PolicyBundle digest;
  - component owner;
  - environment;
  - start/end time;
  - exit code;
  - raw/stdout/stderr/input artifact hashes;
  - raw artifact URI;
  - optional cluster genesis hash.
- `IndependentEvidenceVerifier` converts raw evidence into `VerifiedEvidence`.
- Verification enforces:
  - requirement match;
  - accepted source class;
  - release and PolicyBundle binding;
  - optional cluster binding;
  - non-zero successful producer exit;
  - freshness;
  - independent producer/verifier identity;
  - signed provenance reference.
- `VerifiedEvidencePackage` is the release/readiness-facing object that fails
  closed if required evidence is missing, blocked, stale, cross-release, or
  cross-policy.

## Safety boundaries

This slice is intentionally offline and side-effect free:

- no RPC calls;
- no provider probes from CI;
- no signer import;
- no Jito/RPC submission;
- no live enablement;
- no private key or auth header handling.

Executable producers are represented by immutable raw artifacts in this PR. A
later integration slice can attach actual probe commands and artifact storage to
these contracts.

## Why this matters

A random valid-looking SHA-256, a caller-supplied `passed=true`, or a reviewed
JSON manifest is not enough to close a production-readiness requirement. PR-175
requires a raw basis and an independent verifier result that is bound to the
exact release and PolicyBundle.

## Suggested focused verification

```bash
python -m pytest tests/test_pr175_executable_evidence_provenance.py -q
python scripts/verify_repo.py
```
