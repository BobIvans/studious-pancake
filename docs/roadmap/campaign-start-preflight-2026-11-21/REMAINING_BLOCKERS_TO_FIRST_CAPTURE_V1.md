# REMAINING BLOCKERS TO FIRST READ-ONLY CAPTURE_ONLY — 2026-11-21

Disposition of every blocker from `docs/roadmap/paper-data-campaign-universe-2026-11-21/CAMPAIGN_READINESS_REPORT_2026-11-21.md`, updated after the #664/#668 merges and this preflight PR. **No blocker was bypassed.** `LIVE_READ_NOT_AUTHORIZED` and `BLOCKED_SINGLE_SOURCE` remain in force until real, operator-authorized events clear them.

## RESOLVED (by merges / this PR)

| Blocker | Resolution |
|---|---|
| `BASELINE_NOT_ON_BRANCH` | PR #668 merged (commit `0a0c8ad9`): `docs/roadmap/live-data-qualification-2026-11-21/LIVE_DATA_QUALIFICATION_BASELINE.json` + DIN-01 docs pins now on main (snapshot HTML files redacted of 11 Mintlify CSS tokens to pass gitleaks; pin hashes recomputed, redaction documented in the pins JSON) |
| runtime/policy/source-registry hashes unbound | `CAMPAIGN_MANIFEST_CAPTURE_ONLY_V2.json`: runtime authority `abafb600…` (canonical-JSON), source registry `16837d79…` (canonical-JSON, cross-checked vs generation_bindings), policy bundle `89fddcd0…` (raw sha256 of the new bundle manifest); runtime-shape proof via `CampaignManifest` construction receipt |
| Pack stale pointer / pack facts stale | pointer fixed and merged in #664; current truth carried by crosswalk + reports |

## OPERATOR_REQUIRED (human gates — nothing automated clears these)

| Blocker | What the operator must do |
|---|---|
| `LIVE_READ_NOT_AUTHORIZED` (both governed RPC readers) | explicit authorization of the V2 manifest (quotas/retention/profiles) and of the specific capture run; fill `operator_approval.authorized_by/at` |
| two independent RPC profiles | copy `CAMPAIGN_RPC_PROFILES_TEMPLATE_V1.json` to a gitignored local file, replace `-replace-me` placeholders with two independently operated providers (distinct provider/operator/correlation_group), set env-var NAMES for any keys (values never in repo); see `CAMPAIGN_RPC_PROFILES_OPERATOR_CHECKLIST.md` |
| quota/retention sign-off | approve V2 budgets (`rpc_physical_attempts_max 200`, `storage_bytes_max 104857600`, 12/60s/100 per source, 24h window) |
| `NOT_AUTHORIZED_NOT_STARTED` → authorized | human sign-off recorded in manifest + a dedicated authorization PR/issue; merging any PR does not start the campaign |

## DAG_NODE_OWNED (one bounded PR each; unchanged from NEXT_PR_DAG_V1.json)

| Blocker | Owner |
|---|---|
| openocean `BLOCKED_SCHEMA_DRIFT` (now enriched: docs land on EVM v4, amountDecimals/gasPriceDecimals deprecation) | N05 |
| prop-AMM `MISSING_OWNER` | N01 (one venue per PR, HumidiFi first) |
| lender statuses (jupiter_lend capacity UNKNOWN; project0 rebind; kamino SDK pin; navi checkpoint; save_solend support proof; marginfi separate gate) | N06..N10 + PR #655 owner |
| astralane_iris / 0slot `VENDOR_CLAIM_UNVERIFIED` + `DOCS_UNREACHABLE` (DNS dead); titan docs domain dead | N11 benchmark-dossier PR set (re-locate official sources first) |
| CLMM/DLMM pins (DLMM amount-specific quote, CLMM tick-array bitmap extension, Orca license) | N12 under #660 lineage |

## CREDENTIALS_REQUIRED (names only; values never stored)

- `JUPITER_API_KEY` — Jupiter Swap V2 comparator phase (x-api-key; recheck confirms V2 2.0.0 current).
- `ZEROX_API_KEY` — 0x Solana comparator phase (0x-api-key; recheck confirms current, v0/v1 transaction_version).
- Not required for the first read-only discovery/rooted capture; required before aggregator-comparator phases.

## ENV_DEBT (Windows local CI; PR #670 carries receipts)

- `WINDOWS_PYTEST_SOCKET_PROACTOR_LOOP` — conftest/loop-factory fix (separate task; clears bulk of 288 baseline failures).
- `WINDOWS_LOCK_UVLOOP_NO_MARKER` — regenerate `requirements.lock` with environment markers (package_smoke wheelhouse stage).
- `WINDOWS_SQLITE_TEMP_CLEANUP_PERMISSION` — `verify_occ_durable_host.py` sqlite close-before-cleanup.

## EXACT REMAINING LIST — what stands between now and the first authorized read-only CAPTURE_ONLY run

1. Operator fills the two local RPC profiles + approves V2 manifest quotas/retention (checklist §1).
2. Operator records explicit authorization (who/when/what manifest+budget) — human gate.
3. Operator runs the bounded capture command from the runbook S7 with the approved profiles.
4. Quorum gate must pass on real reads (≥2 provider/operator/correlation_group; else verdict stays `BLOCKED_SINGLE_SOURCE`).
5. Aggregator-comparator phases additionally require JUPITER/ZEROX keys (names only, values in env).
6. Everything else (lenders, prop-AMM venues, delivery benchmarks, openocean refresh) proceeds in parallel through DAG N01–N12 and does not gate the first capture.
