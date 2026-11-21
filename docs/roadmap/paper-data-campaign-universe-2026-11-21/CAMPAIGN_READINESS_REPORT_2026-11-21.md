# CAMPAIGN READINESS REPORT — PR #664 (2026-11-21)

**Lane:** PR #664 campaign preparation — broad market-data universe + sender-free paper campaign (preparation only).
**Date:** 2026-11-21.
**Base:** pack commit `0647fd6b` on `codex/paper-data-campaign-universe-relay-budget-2026-11-21`, merged with reconciled origin/main `ea204222df86a0697cc6bce0e9ec60f7db31ffd8` (the PR #660 merge, merged 2026-11-21T10:43:27Z).
**Head:** filled at commit time (see git history of this branch; commits `694e2d2a` pointer fix + deliverables commit on top of the merge).
**Evidence state:** `CAMPAIGN_PREP_DOCS_ONLY`. **No campaign was started; manifest status `NOT_AUTHORIZED_NOT_STARTED`; merging this PR does not authorize any live activity.**

## 1. Reconciliation facts (recorded at execution time, per AGENTS.md rule 2)

- Local main at task start: `3030fc720c707c994f9d7a21d50e1d181a60b8c9`; origin/main reconciled to `ea204222df86a0697cc6bce0e9ec60f7db31ffd8`.
- Merged: #658, #659 (R10-1 CPMM binding), **#660 (CLMM/DLMM — merged today; ownership preserved, not duplicated)**, #661 (R13 Aftermath), #662 (R05-S seam), #663 (R08-step1 governed-RPC seam).
- Open PRs and their changed-path roots (all verified 2026-11-21 via `gh pr diff --name-only`):
  - #649 SX-03 Curve LLAMMA (`docs/strategy-expansion/2026-11-14/dossiers/`, `src/strategy_evolution/llamma_band_math.py`, `tests/`)
  - #655 R10-2 MarginFi (`src/providers/marginfi/capital_edges.py`, `tests/`, `config/format_targets.txt`)
  - #657 SX-18/W6-12 docs (`docs/strategy-expansion/2026-11-14/` + master docs)
  - #665 prop-AMM toolchain pack (draft; `docs/strategy-expansion/2026-11-21/prop-amm-competitive-toolchain/`)
  - #666 intelligence operating plane (draft; `docs/roadmap/intelligence-operating-plane-2026-11-21/`)
  - #667 real-data multilender (draft; `docs/strategy-expansion/2026-11-21/real-data-multilender-integration/`)
- CI on main: green (`PR-139 scheduled drift operations` success 2026-11-21T10:57:29Z; `#660` merge run success 2026-11-21T10:43:29Z).
- **No path overlap:** all PR #664 changes are 7 new files plus 1 two-line edit inside `docs/roadmap/paper-data-campaign-universe-2026-11-21/` only. No open PR touches that directory; no `src/`, `config/`, `tests/`, `scripts/` changes are made by this PR; #660 CLMM/DLMM ownership (`src/providers/raydium_clmm_native.py`, `src/providers/meteora_dlmm_native.py`, `src/strategy/clmm_dlmm_binding.py`, `scripts/clmm_dlmm_market_trace_replay.py`) is preserved and referenced, not duplicated.

## 2. Deliverable status (8 rows)

| # | Deliverable | Status | Evidence |
|---|---|---|---|
| 1 | Machine-readable owner/strategy/source crosswalk | DONE | `STRATEGY_SOURCE_OWNER_CROSSWALK_V1.json` (20 families, one owner each, reconciled against origin/main ea204222 + all open PRs) |
| 2 | Source/provider readiness dossier matrix | VALIDATED (pack file) | `SOURCE_AND_PROVIDER_READINESS_V1.json` parses; 25 sources with truthful statuses; its `repository_main_sha` 3030fc72 is the pack-creation record, current state is carried by the crosswalk |
| 3 | CAPTURE_ONLY campaign manifest | DONE + VALIDATED | `CAMPAIGN_MANIFEST_CAPTURE_ONLY_V1.json` — `MANIFEST_VALIDATION_OK`: byte-level template diff is exactly campaign_id + release.git_commit (ea204222) + 3 added provenance keys; all 11 safety flags false; budgets 0; canary disabled; unbound hashes carry typed blockers |
| 4 | Read-only capture + replay runbook | DONE | `DATA_CAPTURE_RUNBOOK_V1.md` (S1–S9, `PREPARED_ONLY` banner, not executed) |
| 5 | Execution-delivery research pack (Jito vs Helius vs Astralane vs bloXroute vs 0slot) | DONE | `EXECUTION_DELIVERY_RESEARCH_PACK_V1.md` — all rows `RESEARCH_ONLY_DISABLED`, identical-benchmark methodology, no submission/tip |
| 6 | Future cost-policy specification | DONE | `RELAY_COST_POLICY_SPEC_V1.md` — 7 components all UNKNOWN-start, $10 = aggregate future canary ceiling, no tip escalation |
| 7 | Deterministic replay + coverage receipts | DONE | `.zcode/pr664/replay_receipts.json` (session receipts; values reproduced below) — `r10_offline_replay.py` run twice: exit 0 both, SHA256 run1 == run2 (`r1==r2: True`), byte-identical; `din_discovery --replay` (DIN-01 capture): exit 0, `network_reads: 0`, `replay_identical: true`, 11 deduplicated candidates. **Live-capture count: 0** (no capture run executed in this PR). |
| 8 | Next-PR/task DAG (one bounded PR per missing owner) | DONE | `NEXT_PR_DAG_V1.json` (12 nodes + paper-gate node, acyclic) |

## 3. Exact blockers

| Blocker | Scope | Next action |
|---|---|---|
| `BLOCKED_SINGLE_SOURCE` | any rooted verdict from one RPC | two independently operated providers/correlation groups required (runbook S5) |
| `LIVE_READ_NOT_AUTHORIZED` | `solana_governed_rpc_primary` / `_secondary` | operator-authorized capture manifest + source profiles before any rooted read |
| `BLOCKED_SCHEMA_DRIFT` | `openocean_solana` | DAG N05 dossier refresh (gasPriceDecimals, amount units, auth, fee contract) |
| `OFFLINE_CONTRACT_CAPACITY_UNQUALIFIED` | `jupiter_lend` | DAG N06 (R02-CAP-A, one lender per PR) |
| `OFFLINE_CONTRACT_DEPLOYMENT_REBIND_REQUIRED` | `project0` | DAG N07 (R02-CAP-D + R03-D) |
| `OFFLINE_SDK_PIN_DEPLOYED_STATE_UNQUALIFIED` | `kamino` | DAG N08 (R02-CAP-B + R03-B) |
| `OFFLINE_CONTRACT_CHECKPOINT_UNQUALIFIED` | `navi` | DAG N09 (later wave) |
| `RESEARCH_CANDIDATE` | `save_solend` | DAG N10 support-proof dossier first |
| `DEPRIORITIZED_SEPARATE_GATE` | `marginfi` | keep separate; PR #655 owner intact |
| `VENDOR_CLAIM_UNVERIFIED` / no repo pins | `astralane_iris`, `0slot`; also `localshred_lite`, `orbitflare_shredstream` | DAG N11 benchmark-dossier PR set |
| Unbound hashes | `runtime_authority_sha256`, `policy_bundle_sha256`, `source_registry_sha256`, `campaign_manifest_sha256` | typed blockers in manifest; bind at an operator-authorized capture run |
| Credentials absent | `JUPITER_API_KEY`, `ZEROX_API_KEY` (names only; no values stored) | aggregator-comparator phase blocked; not required for this docs PR |
| `MISSING_OWNER` | prop AMMs (HumidiFi/SolFi/Tessera/BisonFi/GoonFi/Obric/ZeroFi) | DAG N01 first per-venue dossier PR |
| `BASELINE_NOT_ON_BRANCH` | `docs/roadmap/live-data-qualification-2026-11-21/LIVE_DATA_QUALIFICATION_BASELINE.json` | lives on `agent/live-data-preflight-2026-11-21`, not merged; reference budgets quoted with this blocker in runbook S6 |
| Stale pack pointer (fixed) | `CODEX_TRIGGER_RU.txt` said "Work in PR #661" | corrected to #664 in commit `694e2d2a` |
| Pack facts now stale (recorded, not edited) | pack §1 said "#660 remains open and draft" and pinned main 3030fc72 | pack text is a dated historical record; current truth (#660 MERGED ea204222, main ea204222) is recorded in the crosswalk + this report |

## 4. Human gates (exact dependencies listed, per acceptance)

1. **Campaign start authorization** — an operator-approved capture manifest (source profiles, quotas, operator/correlation groups, retention) is required before the first `CAPTURE_ONLY` run; merging this PR starts nothing.
2. **R06/QPR gate** — paper qualification only after exact R06/QPR-01/02/03 + campaign-authority PASS via `src/paper_shadow/` + `src/qualification_campaign/` (no custom runner).
3. **R08 composition audit** — `src/runtime/core_v1_dependency_resolver.py` `governed_rpc_transport` seam is simulation-composition only; not a market-data reader; not a campaign authorization.
4. **Independent prerequisite gates** — R02 capital proof, R03 unsigned-builder conformance, R05 full exact simulation (with R04 consumed by the existing candidate selector), MPR-05 installed 72-hour soak where applicable.
5. **Merge approval** — this PR stays DRAFT until human review; per AGENTS.md rule 11 it may be merged only after conflict/diff/provenance checks and on explicit user request.
6. **Future canary authorization** — separate human-approved, budgeted PR (see `RELAY_COST_POLICY_SPEC_V1.md` §4); `future_canary_enabled: false`.

## 5. Next implementation PRs (DAG summary, dependency order)

All 12 nodes have empty `depends_on` (independently startable, one per owner): **N01** humidi-fi-venue-dossier → prop-AMM family (one venue per PR); **N02** exp01-event-to-state-harness; **N03** stablecoin-anchor-proofs; **N04** pump-migration-event-dossier; **N05** openocean-schema-drift-refresh; **N06** jupiter-lend-capacity-qualification; **N07** project0-deployment-rebind; **N08** kamino-sdk-pin-qualification; **N09** navi-checkpoint-qualification (later wave); **N10** save-solend-support-proof; **N11** delivery-provider-benchmark-dossiers; **N12** clmm-dlmm-pin-prs (#660 lineage, do not duplicate). Paper gate **PG01** depends on N06/N07/N08 + R03 + R05 + installed-composition PASS + human authorization.

## 6. Replay / coverage receipts (fixture/replay vs live)

- Fixture/replay: r10 experiments A–D (byte-identical across two runs, receipts hashed); DIN-01 bounded-Solana replay (`replay_identical: true`, `network_reads: 0`, 11 deduplicated candidates).
- Live capture: **0 observations** (no capture run; none authorized by this PR).
- All percentages in future capture reports must show numerator and denominator; unknowns stay in their own population.

## 7. Verdict

**READY-FOR-REVIEW (docs-only).** The campaign is *prepared*, not started: crosswalk current against main ea204222 and all open PRs, manifest validates against the pack template with every safety flag false, runbook is complete and unexecuted, delivery evaluation is research-only with the tip-escalation prohibition explicit, replay determinism is receipted, and exact blockers + human gates + next bounded PRs are enumerated. Unknown remains UNKNOWN.
