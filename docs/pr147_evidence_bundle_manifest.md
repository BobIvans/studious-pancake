# PR-147 — Evidence bundle manifest sealing gate

This PR is an additive, review-only slice for roadmap-style **PR-147**.

The uploaded second deep-audit roadmap does not define an explicit PR-147 item.
It defines PR-128 through PR-140, then returns to the real-paper sequence. Recent
parallel PR work has already added PR-141/142/143/144/145 continuation gates.
This PR adds the next narrow safety boundary: a deterministic evidence bundle
manifest that prevents readiness, shadow-soak, or release evidence from being
relabelled as complete unless every required gate has an immutable, redacted,
reviewed artifact hash.

## Why this exists

The new queue now contains many independent review gates. A later operator report
or release bundle needs to prove that it is using the exact reviewed evidence
from those gates rather than synthetic, stale, mutable, unredacted or duplicate
artifacts.

PR-147 therefore seals the bundle metadata itself. It does not fetch GitHub,
download artifacts, sign releases, publish containers, call RPC, or modify live
runtime behavior.

## What this slice adds

- `src/evidence_bundle_pr147.py`
  - `PR147EvidenceEntry`
  - `PR147EvidenceBundleManifest`
  - `PR147EvidenceBundleDecision`
  - `evaluate_pr147_evidence_bundle(...)`
  - `assert_pr147_evidence_bundle(...)`

- `tests/test_pr147_evidence_bundle.py`
  - complete bundle review-ready case;
  - missing required gate blocked;
  - duplicate required gate blocked;
  - unexpected gate blocked;
  - unreviewed/unredacted/mutable evidence blocked;
  - synthetic evidence blocked by default;
  - expiring evidence blocked;
  - bundle hash mismatch blocked;
  - paper/live claims blocked in this review slice;
  - malformed hashes and unsafe paths rejected.

## Required gates encoded

The default bundle requires the current bridge/readiness/live-canary gate set:

```text
PR-105
PR-128
PR-129
PR-130
PR-131
PR-132
PR-133
PR-134
PR-136
PR-137
PR-138
PR-139
PR-140
PR-141
PR-142
PR-143
PR-144
PR-145
```

This is intentionally an evidence-manifest boundary, not a statement that every
listed gate has already been merged or that a real bundle already exists.

## Safety boundary

Passing this gate means only:

```text
evidence-bundle-review-ready
```

It still reports:

```text
paper_claim_allowed = false
live_claim_allowed = false
```

This PR intentionally does not mutate:

- `config/format_targets.txt`;
- `scripts/verify_repo.py`;
- workflow files;
- Dockerfile or dependency locks;
- existing simulator/planner/sender/runtime/readiness/settlement modules.

That keeps the patch low-conflict while parallel PRs continue moving `main`.

## Suggested verification

```bash
python -m pytest tests/test_pr147_evidence_bundle.py -q
python scripts/verify_repo.py --skip-dependency-audit
```

## Follow-up integration

Later work can feed this gate from real GitHub PR metadata, workflow artifacts,
artifact digests, provenance attestations, release signatures and shadow-soak
reports. This first slice only makes the manifest-sealing contract explicit and
testable.
