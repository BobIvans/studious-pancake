# PR-047 — Production release gate and operational rehearsal

PR-047 is an **offline evidence gate**, not a live-mode switch. It may report
`production-ready` only when one immutable manifest proves every required
release, security, operational and human-review condition. It never signs,
submits, funds a wallet, rotates a credential or changes runtime mode.

## Dependency boundary

Roadmap PR-046 is mandatory. Until a human-reviewed
`pr046-limited-live-canary` evidence file exists and passes, the result is
`blocked`. PR-039 shadow-soak evidence is independently required. A green CI
run cannot substitute for either evidence bundle or for an operational drill.

## Manifest contents

The strict `pr047.production-release-gate.v1` manifest binds:

- the full Git commit SHA;
- pinned config and external-contract artifacts;
- immutable image digest and SBOM file hash;
- reviewed PR-039 and PR-046 evidence;
- every P0/P1 finding and its closure or time-bounded risk owner acceptance;
- restore, restart, key-rotation, kill-switch and rollback drill reports;
- mainnet wallet public key, observed balance, protected reserve and fee buffer;
- RPC, provider and Jito account/billing/rotation ownership attestations;
- an external-contract drift report plus a fresh runtime drift revalidation;
- ordered shadow → canary → limited-live rollout stages and rollback triggers;
- release-manager, risk-owner, security-owner and operator sign-offs;
- CI, PR-043 security gate, artifact rebuild, SBOM build and operational-rehearsal verification records.

All file references are repository-relative SHA-256 pins. Absolute paths,
parent traversal and all-zero placeholder hashes are rejected. Secret-bearing
fields accept only `env:`, absolute `file:/...`, or `keychain:` references.

## Commands

Generate the strict JSON schema:

```bash
python scripts/pr047_release_gate.py schema > /tmp/pr047-schema.json
```

Calculate the canonical hash after creating a manifest. The hash excludes only
`expected_manifest_sha256`, so it can be inserted into that field without a
self-reference:

```bash
python scripts/pr047_release_gate.py hash \
  --manifest release/pr047-release-manifest.json
```

Validate from the exact checked-out release commit:

```bash
python scripts/pr047_release_gate.py validate \
  --manifest release/pr047-release-manifest.json \
  --repo-root .
```

Exit codes:

- `0`: all evidence is valid and the manifest is eligible for human-controlled
  staged release;
- `2`: valid manifest, but one or more release blockers remain;
- `1`: malformed manifest, unreadable evidence or invalid external-contract
  registry.

The validator also compares the manifest code pin with `git rev-parse HEAD` and
reruns the current PR-027 external-contract drift check. A previously saved
`ok` report does not bypass current drift.

## Release process

1. Freeze the candidate commit. Do not update the branch after collecting
   artifact or drill evidence.
2. Build the image and SBOM twice from the same source and lock inputs. Record
   independent successful `artifact-rebuild` and `sbom-build` verification
   records.
3. Attach human-reviewed PR-039 shadow evidence and PR-046 limited-live canary
   evidence.
4. Revalidate external contracts from the candidate checkout.
5. Complete the five drills in the intended operational environment. A table
   exercise or unit test must set `simulated=true` and therefore cannot pass the
   release gate.
6. Complete the wallet and account-ownership checklists without storing a
   private key, API key or Jito credential in the manifest.
7. Resolve every P0/P1 finding. A risk acceptance needs a named owner,
   rationale and future expiry.
8. Obtain all four sign-offs after the evidence hash is stable.
9. Run the validator. Human operators still control rollout and may block a
   technically passing manifest.

## Non-goals

- no automatic live enablement;
- no automatic promotion between rollout stages;
- no credential creation, retrieval or rotation;
- no wallet funding transaction;
- no assertion that CI success proves production readiness;
- no promotion of optional PR-048+ venues.
