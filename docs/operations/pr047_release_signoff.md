# PR-047 release sign-off template

Release ID:

Candidate Git commit:

Manifest SHA-256:

Image digest:

SBOM SHA-256:

PR-039 evidence SHA-256 and reviewer:

PR-046 evidence SHA-256 and reviewer:

External-contract drift report SHA-256 and checked time:

## P0/P1 disposition

| Finding | Severity | Closed / accepted | Risk owner | Expiry | Rationale |
|---|---|---|---|---|---|

An open P0/P1 is a blocker. Acceptance without a named owner, rationale and
future expiry is invalid.

## Operational drills

| Drill | Performed at | Operator | Environment | Evidence SHA-256 | Passed |
|---|---|---|---|---|---|
| Restore | | | | | |
| Restart | | | | | |
| Key rotation | | | | | |
| Kill switch | | | | | |
| Rollback | | | | | |

## Wallet and service ownership

- wallet public key:
- observed balance in lamports:
- protected reserve in lamports:
- fee buffer in lamports:
- signer reference verified:
- RPC owner / billing owner / rotation owner:
- provider owner / billing owner / rotation owner:
- Jito owner / billing owner / rotation owner:

Do not include credentials or private-key material.

## Rollout and monitoring

- shadow minimum duration and promotion criteria:
- canary maximum exposure and rollback triggers:
- limited-live maximum exposure and rollback triggers:
- rollback target: `shadow`
- on-call owner:
- post-release monitoring window (minimum 24 hours):

## Required decisions

Each role records `approve` or `block` only after reviewing the final manifest
hash. Changing any pinned evidence invalidates the previous sign-off.

| Role | Identity | Decision | Signed at | Comment |
|---|---|---|---|---|
| Release manager | | | | |
| Risk owner | | | | |
| Security owner | | | | |
| Operator | | | | |

A passing tool result is necessary but not sufficient to force a release.
Human operators may always block or roll back.
