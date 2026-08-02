# MPR-TD-01 current-main baseline and overlap inventory

**Recorded:** 2026-08-02 UTC  
**Status:** implementation stopped at Phase 0; this document is not completion evidence.  
**Requested branch:** `codex/mpr-td-01-canonical-contract-surface`

## Verified current-main facts

The repository had no configured remote when work began. `origin` was configured from the
repository named in the request, `https://github.com/BobIvans/studious-pancake.git`, and
`git fetch origin main --prune` resolved both the checked-out commit and `origin/main` to:

```text
9206e399547a0186f1d1c7a763e084235c7e1d8b
```

That SHA is the exact implementation base. No audit branch or historical snapshot was
used.

### Open pull-request overlap

The GitHub REST API was queried for every open pull request and the changed-file list was
inspected for entrypoints, production manifests, authority maps, schemas, utility owners,
exports, type-check configuration, and historical PR/MPR modules. The following open pull
requests are relevant to the requested ownership boundaries:

| PR | State observed | Relevant ownership / paths | Disposition |
| --- | --- | --- | --- |
| #411, MPR-CLOSE-01 | open, head `c9386f6af8f6e2cfdf01faca5ad64599a750235d` | `arb_bot.py`, `src/cli_pr189.py`, installed-product verification | **Unresolved direct overlap:** it modifies the current canonical installed entrypoint wrapper. |
| #217, PR-190 | open, head `49a1257e7c0193fb9d5c9f93ba89830e5be6539b` | `pyproject.toml`, `mypy.ini`, all three historical CLI targets, exports, execution and release-gate initialization | The current authority map labels it superseded by merged work, but GitHub still reports it open; it must be closed or explicitly resolved before cutover. |
| #220, PR-192 | open, head `7fcb2d5288647f518f39891df2cba0bae17df096` | `pyproject.toml`, `mypy.ini`, package tests and security runtime | Direct package/type-policy overlap; its security ownership also belongs outside this Mega PR. |
| #445, MEGA-PR-01 | open, head `d1843691339caa8b62a8afb81e5e67da7f8cd8bd` | roadmap start document only | No code reuse; roadmap overlaps composition intent but currently changes no implementation. |
| #411 and the open queue represented in `config/runtime_authority_map.json` | open/candidate | installed artifact, provider, durability, release, and runtime candidates | No candidate implementation was blindly merged. |

PR #411 triggers the request's hard-stop condition: it is an unresolved open pull request
changing the same canonical package entrypoint that MPR-TD-01 must replace. Consequently,
no semantic-owner cutover, schema/digest change, compatibility retirement, or deletion was
performed. This is deliberately a red blocker, not a green placeholder.

### Executable target map

| Public executable | Current target |
| --- | --- |
| `flashloan-bot` | `src.cli_pr189:main` |
| `flashloan-bot-healthcheck` | `src.container_runtime:healthcheck_main` |
| `flashloan-contracts` | `src.external_contracts.cli_pr189:main` |
| `flashloan-checks` | `src.automation_cli_pr189:main` |
| `flashloan-release-evidence` | `src.release_gate.materialized_evidence:main` |

The public names are unchanged. Current verification confirms that the package remains
sender-free, excludes sender packages, denies live execution, and reports
`not-production-ready`.

### Authority hashes

| Authority | SHA-256 |
| --- | --- |
| `src/resources/production_surface_manifest.json` | `7698f511a3642c83cadba2346617dd53879876fbba839a7acedfa1f0985300f2` |
| `config/runtime_authority_map.json` | `afb63334739319554b876456925ec9540c159ca66ee1d6f257ff8b706fb947db` |
| `src/resources/runtime_authority_map.json` | `afb63334739319554b876456925ec9540c159ca66ee1d6f257ff8b706fb947db` |

The runtime-authority source and packaged mirror are byte-identical.

### Wheel baseline

A wheel was built from the exact base with CPython 3.13.13, `build==1.5.0`,
`setuptools==83.0.0`, and `wheel==0.47.0`:

* wheel SHA-256: `c29652c599a22d6ee5c98fdea37cd69fa046be1d51cabfbc90c019c902d700fd`;
* member count: 513;
* Python member count: 467;
* historical PR/MPR-numbered Python member count (filename-based baseline): 175.

The exact sorted member list is recorded in
[`mpr_td_01_baseline_wheel_members.txt`](mpr_td_01_baseline_wheel_members.txt). The wheel
hash is a baseline build artifact hash, not a release signature or external conformance
claim.

### Production reachability and import graph

The currently declared installed roots are the five console targets above. The production
surface additionally declares `src.authority_map`, `src.production_surface`, and
`src.pr206_durable_state` as required controls. Its runtime cutover identifies
`src.cli_pr189` as composition owner, with delegation to `src.automation_cli_pr189` and
`src.cli`. The wheel contains 467 Python members, including 175 filenames matching the
historical PR/MPR-number pattern.

This is the verified **declared authority graph**, not a claim that a complete static and
runtime import closure has been proven. The requested complete production graph cannot be
made authoritative until the #411 entrypoint overlap is resolved. Treating the existing
manually declared set as complete would violate the request.

### Type-check quarantine

`config/typecheck_quarantine.json` contains eight module entries:

1. `src.application`;
2. `src.execution.transaction_compiler`;
3. `src.execution.shadow`;
4. `src.execution.transaction_simulator`;
5. `src.providers.jupiter.router`;
6. `src.routing.adapters`;
7. `src.paper_shadow.durable_service_a3`;
8. `src.security.secure_files`.

The baseline lacks the requested per-entry expiry, exact error-code budget, and full active
production-set derivation. These are merge-blocking debt, not silently accepted exceptions.

### Verification baseline

Executed with CPython 3.13.13 unless noted:

| Exact command | Result |
| --- | --- |
| `python -m pip check` | pass |
| `python -m compileall -q arb_bot.py src scripts tests` | pass |
| `python scripts/validate_authority_map.py` | pass; product remains `not-production-ready` |
| `python scripts/verify_pr194_trusted_foundation.py --json` | pass; sender package excluded and live denied |
| `python scripts/verify_mpr32_public_entrypoint_truth.py --json` | pass for the existing historical target map |
| `python scripts/verify_pr200_production_cutover.py --json` | verifier exits zero but reports `blocked_pending_evidence` and ten promotion blockers |
| `python scripts/verify_pr206_durable_state.py --json` | pass; live and sender/signer remain disabled |
| `python scripts/verify_repo.py --skip-dependency-audit` | fail because `flake8` is unavailable in the CPython 3.13 environment |
| `python scripts/package_smoke.py` under the ambient CPython 3.14.4 | fail because `build` is unavailable there and 3.14 is outside project support |

The network-backed dependency audit was not run and is recorded as skipped, not passed.
No authoritative production image, release approval, release signature, credential-backed
external evidence, or migration decision was available.

## Inherited audit findings versus current-main facts

`PR-024_IMPLEMENTATION_SUMMARY.md` exists in the current tree, but it is an inherited
implementation narrative, not an accepted audit snapshot and not current-main verification.
No old audit snapshot was supplied or identifiable as an authoritative base. Therefore:

* facts and hashes above were measured directly from current main;
* historical claims were not promoted to verified facts;
* differences against an unspecified old audit snapshot cannot be truthfully enumerated;
* current main itself demonstrably includes a 513-member wheel, 175 historical-numbered
  Python wheel members, historical console targets, and eight type-quarantine entries.

## Hard blockers and debt ledger

| Blocker | Owner / resolution needed | Effect on Definition of Done |
| --- | --- | --- |
| Open PR #411 modifies `src/cli_pr189.py`, the same canonical entrypoint ownership requested here. | Repository maintainers must merge, close, or provide an explicit semantic ownership decision. | Stops implementation before Phase 1; entrypoint parity and historical extinction cannot be claimed. |
| Open PRs #217 and #220 overlap package and mypy configuration; #217 also overlaps all historical CLI targets and dynamic initialization surfaces. | Repository maintainers must close superseded PRs or authorize a conflict disposition. | Strict API/type cutover cannot have one reviewed owner. |
| No authoritative old audit snapshot was supplied. | Provide its commit/reference if a comparison is required. | Snapshot differences remain unavailable rather than fabricated. |
| No authoritative production image or image digest is available. | Later artifact owner must supply it. | Image parity is unverified. |
| Release/external approval, signed artifacts, credentials, and external conformance evidence are unavailable. | External/release owners only. | No production-ready or conformance claim is made. |
| Immutable evidence digest migration decisions are not authorized. | Schema/evidence owners must approve any non-compatible migration after overlap resolution. | No active schema or digest was changed. |
| Aggregate verification lacks `flake8` in the selected environment. | Install the pinned dev environment before resuming. | `verify_repo.py --skip-dependency-audit` is not green. |

## Definition of Done status

MPR-TD-01 is **not complete**. Only current-main fetch, base recording, overlap inspection,
baseline wheel capture, and baseline verification were performed. Phases 1–7, all requested
inventories, utility/schema/type/entrypoint cutovers, historical extinction, canonical
verifier evidence, clean-wheel testing, image testing, deletion evidence, and final
migration/rollback publication remain blocked and undone.

The branch remains sender-free because no runtime code changed. Private-key loading,
signing, Solana RPC submission, Jito submission, and live activation were neither added nor
made reachable. Live mode remains denied, and this document makes no production-readiness
claim.
