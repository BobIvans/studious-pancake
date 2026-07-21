# PR-091 real security, SBOM, provenance and chaos evidence

This directory is the only accepted location for PR-091 release evidence
manifests and the files they reference.

The PR-091 loader is intentionally strict:

- the manifest must use schema `pr091.real-security-sbom-chaos-evidence-manifest.v1`;
- the manifest must live under `release_artifacts/pr091/`;
- every `artifacts[].path` must also live under `release_artifacts/pr091/`;
- every operational-drill scenario must provide an `evidence_path` under this
  directory and its `evidence_sha256` must match the file contents;
- by default, the manifest and all referenced files must be tracked by Git;
- the loaded package is still evaluated by `ActualEvidenceGate`, so live
  submission remains fail-closed through `no_live_submission` and the PR-062
  drill gate.

Do not commit placeholder, synthetic, tmp-path, or unit-test evidence here. This
README does not constitute an accepted evidence package.
