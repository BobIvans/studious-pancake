# PR-078 — Actual security, SBOM and chaos evidence

## Purpose

PR-062 introduced the offline security/SBOM/chaos gate contract. PR-078 adds the
next admission layer: the gate now rejects synthetic placeholder evidence and
requires every required security, build and drill report to be backed by a real
repository-relative artifact hash.

This remains an evidence-only change. It does not import signer adapters, RPC
senders, Jito transports, live runtime code or wallet material.

## Evidence contract

`src.release_gate.actual_evidence` defines:

- `ActualEvidenceKind` — the required artifact set for PR-078;
- `ActualEvidenceArtifact` — a file pin plus policy/review metadata;
- `ActualEvidencePackage` — the artifact set plus the PR-062 drill suite;
- `ActualEvidenceGate` — a fail-closed evaluator that consumes PR-062 output.

Required artifact kinds cover:

- isolated signer disabled-mode boundary;
- inline private-key rejection;
- CycloneDX and SPDX SBOM outputs;
- dependency vulnerability scan with critical-CVE policy enforcement;
- signed artifact/image provenance;
- license inventory;
- secret scan;
- provider 429/5xx/schema drift;
- RPC lag/fork/drop;
- blockhash/ALT expiry;
- queue saturation;
- journal lock/corruption;
- ambiguous RPC/Jito ack;
- bounded retries/tasks/queues;
- measured recovery-time SLO;
- restore/corruption drill report.

## Fail-closed behavior

The PR-078 gate blocks when:

- any required artifact kind is missing or duplicated;
- a path is absolute, escapes the repo root, is missing, or its SHA-256 does not
  match the recorded digest;
- an artifact digest is a zero/placeholder hash;
- artifact metadata identifies a placeholder, synthetic, unit-test or fixture
  source;
- dependency evidence reports critical findings or lacks policy enforcement;
- secret/private-key evidence lacks policy enforcement;
- journal/corruption/recovery drill reports are not reviewed by a named reviewer;
- PR-062 operational readiness is blocked;
- a chaos scenario does not end in an explicit safe-idle/manual-review state;
- any scenario attempted automatic duplicate submission or left residual tasks.

## Compatibility with parallel PRs

The patch is additive and sits on top of the current `main`. It does not rebase
or copy previous PR branches. If PR-077 lands while this PR is open, the package
builder can feed its final paper-vertical artifacts into this PR-078 contract
without changing the gate semantics.

## Suggested checks

```bash
python -m pytest tests/test_pr078_actual_security_sbom_chaos_evidence.py -q
python -m pytest tests/test_pr062_security_chaos_drills.py -q
python -m compileall -q src/release_gate tests/test_pr078_actual_security_sbom_chaos_evidence.py
python scripts/verify_repo.py --skip-dependency-audit
```

## Safety boundary

This PR deliberately does not make live trading possible. It only turns real,
hashed, reviewed evidence into a stronger fail-closed release-gate input. Live
submission must remain blocked until the later roadmap PRs provide shadow soak,
canonical sender integration and human canary evidence.
