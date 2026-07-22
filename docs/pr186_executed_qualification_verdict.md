# PR-186 — Executed qualification verdict and release-claim attestation

## Mission

Replace the PR-176 descriptive manifest with three explicit trust levels:

1. `QualificationPlan` — describes intended controls and can never authorize a release;
2. `QualificationRun` — records commands actually executed in one selected environment;
3. `QualificationVerdict` — a signed decision bound to the exact run, source tree and wheel.

The snapshot `(12)` audit reproduced two critical false positives:

- dependency closure was `complete=true` when package names appeared in requirements even though `solders` was not importable;
- dry-run emitted `release_claim_allowed=true` even though mandatory commands, wheel installation and parity checks had not run.

This PR removes both semantics from the active qualification command.

## Active changes

### Installed dependency truth

`inspect_dependency_closure()` now records and checks:

- required and declared package names;
- installed distribution versions from the selected interpreter;
- importability probes;
- missing, undeclared and non-importable packages;
- exact interpreter path;
- global-site-packages state.

A lock declaration is no longer installation evidence.

### Non-authoritative plans

`QualificationPlan.release_claim_allowed` is retained only for compatibility and always returns `False`.

Default command output is:

```json
{
  "schema_version": "pr186.qualification-plan.v1",
  "execution_mode": "planned",
  "qualification_state": "planned_not_executed",
  "qualified": false,
  "release_claim_allowed": false
}
```

### Full source identity

`source_tree_identity()` hashes every non-generated repository file with:

- relative path;
- byte size;
- SHA-256;
- aggregate source-tree digest.

Changing `src/cli.py` or any other tracked production source changes qualification identity.

### Executed run evidence

`QualificationRun` binds:

- source tree;
- exact interpreter and isolation properties;
- installed dependency closure;
- production wheel hash;
- wheelhouse manifest hash;
- selected commands;
- exit codes;
- start/finish and duration;
- stdout/stderr hashes and sizes;
- source-import leakage result;
- network-disabled-after-bootstrap assertion.

### Signed verdict

Only `QualificationVerdict` may expose `release_claim_allowed=true`.

The verdict is fail-closed unless all conditions hold:

- all selected profiles completed and passed;
- installed dependency closure is complete;
- interpreter is isolated and global site-packages are disabled;
- production wheel and wheelhouse hashes are present;
- source import leakage is absent;
- network is disabled after bootstrap;
- a separately produced repeated clean run matches;
- the verdict is cryptographically attested.

This slice uses HMAC-SHA256 for a CI-local attestation boundary. Migration to the reviewed asymmetric `TrustAnchorRegistry` belongs to PR-183; a hash-shaped string alone is never accepted as a signature.

## Execute command

Execution now requires explicit evidence inputs:

```bash
python scripts/qualify_release.py --execute \
  --interpreter /path/to/fresh-venv/bin/python \
  --production-wheel wheelhouse/flashloan_bot.whl \
  --wheelhouse-manifest wheelhouse/manifest.json \
  --attestation-key-file /secure/path/qualification.key \
  --attestation-key-id ci-release-key-1 \
  --run-output artifacts/qualification-run.json \
  --verdict-output artifacts/qualification-verdict.json \
  --repeated-run artifacts/qualification-run-second-clean-env.json
```

Missing evidence returns a blocked non-zero result. The command does not silently fall back to the caller's global Python environment.

## Safety invariants

```text
plan_is_release_evidence = false
dry_run_can_claim_release = false
lock_declaration_is_installation_evidence = false
unsigned_verdict_can_claim_release = false
missing_repeated_run_can_claim_release = false
live_enabled = false
```

## Tests

Focused verification:

```bash
python -m pytest \
  tests/test_pr176_hermetic_qualification.py \
  tests/test_pr186_executed_qualification.py -q
```

The focused suite passed locally before the PR was opened.

## Remaining work

This PR establishes and activates the correct plan/run/verdict semantics. It does not yet claim the complete PR-186 acceptance set:

- CI still needs a workflow that materializes the approved wheelhouse and two fresh environments;
- source and installed-wheel profiles need a dedicated parity comparison artifact;
- JUnit count parsing and resource-usage capture can be expanded;
- HMAC attestation must migrate to PR-183 asymmetric trust anchors before production release signing;
- release promotion workflows must consume only verified `QualificationVerdict` objects.

Until those integrations exist, qualification remains fail-closed rather than producing a false release claim.
