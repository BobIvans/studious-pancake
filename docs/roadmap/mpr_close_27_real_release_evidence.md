# MPR-CLOSE-27 — Real release evidence, soak, backup/restore and ops gate

This slice implements the fail-closed evidence boundary for MPR-CLOSE-27.

## Purpose

MPR-27 must close the PR200 missing-artifact gap without pretending that unit
fixtures, local smoke tests or synthetic runs are real production evidence.  The
new gate therefore does **not** create fake release evidence.  It accepts only
materialized files under an approved release-artifacts root, computes their
SHA-256 digests locally and emits a report that remains `blocked_pending_evidence`
while required evidence is missing or invalid.

## Covered artifact IDs

Required PR200 artifacts:

- `runtime_wheel_digest`
- `runtime_image_digest`
- `sbom_digest`
- `config_generation_digest`
- `capability_manifest_digest`
- `program_idl_hashes`
- `database_schema_fingerprint`
- `shadow_campaign_report_digest`
- `fault_injection_report_digest`
- `backup_restore_report_digest`

Operational MPR-27 artifacts:

- `slo_baseline_report_digest`
- `secret_incident_drill_report_digest`

## Hard rejection rules

The gate rejects:

- placeholder, fake, TODO, tmp-only, unit-test-fixture and one-shot-smoke evidence;
- artifact paths outside the approved release root;
- empty files, symlinks and non-files;
- synthetic or one-day shadow campaigns;
- shadow reports with sender/keypair enabled;
- backup/restore evidence that does not prove clean-runtime restore, verified event chain and zero duplicate decisions;
- missing fault-injection cases for stale RPC, provider timeout, schema drift, DB write failure, crash during reservation, expired quote, replayed webhook, clock rollback and partial restore;
- invalid SLO metrics and secret-incident drill evidence.

## Commands

Generate a blocked or review-ready report from materialized files:

```bash
python -m flashloan_release_evidence generate \
  --root release_artifacts/current \
  --output release_artifacts/current \
  --artifact runtime_wheel_digest=runtime-wheel.sha256 \
  --artifact runtime_image_digest=runtime-image.sha256 \
  --artifact sbom_digest=sbom.spdx.sha256 \
  --artifact config_generation_digest=config-generation.json \
  --artifact capability_manifest_digest=capabilities.json \
  --artifact program_idl_hashes=program-idl-hashes.json \
  --artifact database_schema_fingerprint=database-schema.json \
  --artifact shadow_campaign_report_digest=shadow-campaign.json \
  --artifact fault_injection_report_digest=fault-injection.json \
  --artifact backup_restore_report_digest=backup-restore.json
```

Verify that a stored report still matches the materialized files:

```bash
python -m flashloan_release_evidence verify-mpr27 \
  --root release_artifacts/current \
  --report release_artifacts/current/mpr27_release_evidence_report.json
```

## Safety boundary

This PR does not enable live trading, signer access, Jito submission, wallet
loading or production promotion.  A complete accepted MPR-27 evidence report is
only a release-review artifact; live canary remains owned by later signer/canary
work.
