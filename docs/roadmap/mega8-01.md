# MEGA8-01 — continuous truth, attestation and reproducible data

This change implements the roadmap ownership surface **PR-151–PR-162 / NF-353–NF-400**
as an offline, deterministic qualification layer.

## Current-head anti-duplication

The implementation was started from the then-current `main` after searching the
default branch for all twelve primary roadmap symbols. None were present. Existing
canonical release, data-plane, provider-governance, persistence, security and
evidence owners remain authoritative; `src/mega8_01/` is an integration/evidence
surface, not a replacement runtime authority.

## Child ownership

| Child | NF | Contract |
|---|---|---|
| PR-151 | NF-353..356 | HEAD delta qualification and evidence expiry |
| PR-152 | NF-357..360 | program binary / upgrade-authority attestation |
| PR-153 | NF-361..364 | schema evolution and decoder replay |
| PR-154 | NF-365..368 | upstream semantic drift and upgrade gate |
| PR-155 | NF-369..372 | provider consensus and source quarantine |
| PR-156 | NF-373..376 | time calibration and timestamp uncertainty |
| PR-157 | NF-377..380 | idempotent dataset migration/backfill |
| PR-158 | NF-381..384 | content addressing, dedupe and compaction proof |
| PR-159 | NF-385..388 | read-only query contracts and reproducible views |
| PR-160 | NF-389..392 | value-of-information quota allocation |
| PR-161 | NF-393..396 | malformed/poisoned ingest protection |
| PR-162 | NF-397..400 | frozen benchmark manifests and scorecards |

## Safety and effect boundary

MEGA8-01 has no RPC/HTTP clients, signer/key access, transaction submission,
wallet funding, remote mutation, paid service invocation, or automatic capital
promotion. Unknown/stale/inconsistent data fails closed. External upstreams
mentioned by the roadmap remain REFERENCE/WRAP/TOOL candidates; this change copies,
ports, vendors, installs, or executes none of their code.

Code merge, data qualification, shadow qualification, live authorization, and
capital increase remain separate states.

## Verification

```bash
python scripts/verify_mega8_01.py --json
python -m pytest -q tests/test_mega8_01.py
python -m compileall -q src/mega8_01 scripts/verify_mega8_01.py tests/test_mega8_01.py
```

The dedicated GitHub Actions workflow also performs an installed-package smoke.

## Rollback

Disable consumption of `src.mega8_01` or revert the MEGA8-01 commit set. The
package creates no live operation that needs transaction recovery. Preserve emitted
evidence artifacts externally if they have already been used for audit.

## Residual blockers

Deployment-specific program binary evidence, real provider quorum observations,
external SDK immutable revisions/licenses, real warehouse migrations, and measured
benchmark datasets remain environment/evidence work. Their absence is not reported
as PASS and this change does not claim production readiness or profitability.
