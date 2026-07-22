# PR-177 — Repository evolution hygiene and generated-artifact governance

This PR starts PR-177 as a side-effect-free repository hygiene governance layer.

Snapshot `(11)` found that the repository is more honest and fail-closed, but it now has a new maintenance risk: accidental markers, duplicated roadmap/gate files, committed generated reports, and unclear supersession metadata can become permanent production surface.

## Scope implemented here

This patch adds `src/repository_hygiene.py`, which models:

- artifact classes: source, generated, fixture, evidence, documentation, temporary and forbidden;
- artifact lifecycle states: active, deprecated, quarantined, scheduled-for-removal and removed;
- generated-artifact reproducibility manifests;
- supersession metadata for canonical/superseded docs and evidence;
- quarantine owner/removal metadata;
- duplicate production-domain owner detection;
- repository surface budgets;
- release-branch cleanliness checks;
- deterministic machine-readable hygiene results.

## Snapshot `(11)` findings mapped

PR-177 is designed to make these findings enforceable:

- accidental root marker such as `tmp_accidental_pr_marker_168` must be rejected;
- caches, local DBs and generated local artifacts must not enter release branches;
- PR-number experiments must not become second production owners;
- docs and evidence require canonical/supersession metadata;
- committed generated artifacts require generator command, version, input hashes, deterministic output hash and verification test;
- quarantined code requires owner, reason, removal owner and removal release;
- production wheel contents must not include temporary, forbidden, removed, scheduled-for-removal or quarantined artifacts;
- repository surface growth and duplicate-domain count must be measurable.

## What this PR deliberately does not do

- It does not delete existing files.
- It does not mutate packaging configuration.
- It does not scan the working tree directly.
- It does not change the runtime import graph.
- It does not remove or rename duplicated historical PR modules.
- It does not mark the release branch clean by assertion.
- It does not enable paper, live, signer, sender, Jito or provider/RPC paths.

The evaluator is intended to be wired into CI and release qualification after PR-174 canonical ownership and PR-176 hermetic qualification define the authoritative package/test surfaces.

## Safety posture

The evaluator is fail-closed. A repository state is not hygiene-clean if it contains:

```text
tmp_* / accidental marker files
cache or local DB artifacts
unregistered generated outputs
docs/evidence without supersession metadata
duplicate production owners for one domain
quarantined code without owner/removal metadata
stale evidence on a release branch
temporary/forbidden/non-active artifacts in production wheel
surface budget violations
```

## Suggested verification

```bash
python -m pytest tests/test_pr177_repository_hygiene.py -q
python -m compileall -q src tests
```

## Follow-up integration owner

A later integration PR should connect this policy to:

- release qualification profile from PR-176;
- canonical owner registry from PR-174;
- generated evidence pipeline from PR-175;
- packaging/profile boundaries from PR-173;
- final release branch checks.

Until that wiring exists, this PR is a governance contract and test suite, not a claim that the repository is already release-clean.
