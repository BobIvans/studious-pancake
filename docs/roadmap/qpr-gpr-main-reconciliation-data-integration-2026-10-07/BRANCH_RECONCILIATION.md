# BRANCH_RECONCILIATION — RCN-00 (blocking priority, before external APIs)

## Objective and invariants

Recover QPR-01/02/03 + GPR-01/02/03 and UXE R&D into a **new PR whose base is the current `main`**. Preserve PR #566 cleanup, PR #576 implemented Dynamic Universe and PR #577 storage safety. Never mark a PR `merged` as proof that its patch reached `main`. No force-push to `main`, no automatic merge, no suppression of tests or safety gates.

**Source branch:** `rnd/gpr-parallel-radar-2026-10-06` (observed head `0f13b51cf772abbdfe14356009d82c002caa0ac4`).  
**Baseline current `main` observed:** `72406c0e8a945fe07859807aa5107a8d10043fde`.  
**Source's common ancestor with main at audit:** `ac6297e3f174d073c524099f599490edfe30f7b1`.  
These are *snapshot pins*, not perpetual source of truth. Always re-fetch and record fresh SHA before changing code.

## Phase 0: immutable evidence and ancestry audit

```bash
git fetch --prune origin main \
  codex/prequal-rnd-master-2026-10-06 \
  codex/qpr-01-campaign-authority \
  codex/qpr-02-qualification-data-plane \
  codex/qpr-03-campaign-source-intake \
  rnd/gpr-parallel-radar-2026-10-06 \
  impl/gpr02-solana-radar-2026-10-06 \
  impl/gpr03-sui-shadow-2026-10-06 \
  rnd/universal-source-execution-slumlord-2026-10-07
git rev-parse origin/main origin/rnd/gpr-parallel-radar-2026-10-06
git merge-base origin/main origin/rnd/gpr-parallel-radar-2026-10-06
git log --oneline --graph --decorate --all -100
git diff --stat origin/main...origin/rnd/gpr-parallel-radar-2026-10-06
git diff --name-status origin/main...origin/rnd/gpr-parallel-radar-2026-10-06
```

Record a `RECONCILIATION_RECEIPT.json` with: timestamp, both fetched refs, merge-base, included PRs + merge commit SHA, target base SHA, candidate conflict files, checked tests and final GitHub PR URL. For each merged PR, verify either merge commit ancestry **or** equivalence of its intended changed content plus tests. Branch history can contain merges, squash or follow-up edits; do not equate raw commit equality with content correctness.

Expected provenance:
- QPR chain: #568 `fd152c3`, #569 `8baeb411`, #570 `4a89d0e1` (these are their original GitHub merge SHAs; confirm ancestry).
- GPR: #571 `476c3782`, #572 `ffd126b6`, #573 `baef8d09`.
- UXE doc package: #575 `0f13b51c` (16 docs, no `src`).
- Main-owned PRs: #566, #574, #576, #577. Note #567 was NOT merged.

## Phase 1: integration sandbox from latest main

Use an isolated clean worktree when available; if environment has no remote auth or worktree support, stop with an explicit blocked receipt rather than claiming a remote PR or merge.

```bash
git switch main
git pull --ff-only origin main
git switch -c codex/rcn00-restore-qpr-gpr-2026-10-07
git merge --no-ff --no-commit origin/rnd/gpr-parallel-radar-2026-10-06
# inspect index, conflict markers, delete-vs-modify, renamed paths
git status --short
git diff --check
```

Do **not** follow these commands blind if local dirty state exists: stash/commit only with permission, or use a separate worktree. If the whole-branch merge imports unexpected commits or incompatible runtime changes, abort and instead construct a path/commit-level recovery plan with exact changed file provenance. Avoid replaying QPR-01, QPR-02, QPR-03, GPR-01, GPR-02, GPR-03 as separate cherry-picks if the canonical radar branch already contains them: that duplicates commits and obscures conflicts. Refrain from auto-resolving with `-X ours` / `-X theirs` across the whole repository.

### Six *shared changed paths* needing manual semantic review

The comparison of `ac6297` → `main` and `ac6297` → radar produced exactly these candidates; overlap is **not** proof of a real Git conflict:

| Path | Required resolution |
| --- | --- |
| `src/runtime/runtime_entrypoint.py` | Keep current main hard-disable/authority checks; reintegrate QPR campaign attestation without enabling live sends or bypassing release gates |
| `src/market/native_cpmm_capture.py` | Preserve QPR independent rooted snapshot/direct-state proof; preserve main post-PR #577 durable/retention semantics |
| `src/paper_shadow/native_cpmm_qualification.py` | Preserve typed exact-state failure and campaign generation receipts; reconcile current main promotion/cost gating |
| `requirements.lock` | Regenerate via existing pinned lock workflow; no manual mixing versions or removing hashes |
| `requirements-dev.lock` | Same; keep current CI/dev needs and new QPR/GPR imports |
| `config/requirements-lock.json` | Refresh canonical digest/index to match lock files and installed CI command |

Also inspect `src/resources/runtime_authority*`, `src/resources/schema_registry.json`, `src/provider_governance`, `src/market/streams.py`, `src/durability`, `src/assets/resolution`, `src/discovery/dynamic_universe/promotion.py` for *semantic* integration even when no text conflict appears.

### Redundant owner guardrails

- Do not instantiate a second `CampaignManifest`, `SourceIntakePlane`, `ProviderGovernance`, `RecoverableStreamJournal`, `ResearchEconomicGraph`, `VerificationQueue`, `MarketObservationV2`, `ShadowMarketGraphIngest`, `UniversalArbitrageGraph`, PR118 amount grid or persistent parquet store.
- Integrate current main `ExistingQPRReadiness` with the restored canonical `src.qualification_campaign.cli.report`; missing/incomplete campaign receipts must remain blocked, never silently converted to PASS.
- Dynamic registry resolver may supply typed `AssetIdentity` for a research edge; it must not upgrade QPR exact verification on identity alone.
- Existing QPR Solana `SourceIntakePlane` is chain-specific: **do not relax its public-key/chain validation to force Sui into it**. Add chain-neutral outer research adapters for Sui.

## Phase 2: inventory invariants

Required files after RCN-00 integration **in the PR head**:

```text
src/qualification_campaign/cli.py
src/qualification_campaign/identity.py
src/qualification_campaign/profiles.py
src/qualification_campaign/rpc.py
src/qualification_campaign/sources.py
src/research_economic_graph/graph.py
src/research_economic_graph/verification.py
src/solana_parallel_radar/cli.py
src/gpr_sui_shadow/campaign.py
src/assets/resolution/resolver.py
src/discovery/dynamic_universe/universe.py
src/strategy/relation_generators/generators.py
src/research/correlation_ledger/ledger.py
src/economics/flash_capital_graph/graph.py
```

Verify QPR/GPR test files are present and `tests/test_dynamic_*.py` continue to run. Restore GPR-02/03 raw and negative evidence/summary bundles as provenance without silently overwriting historical records. Avoid committed secrets and additional large captured data blobs unless the repo's original evidence policy requires them.

## Phase 3: validation before a PR

Minimum focused commands (adapt exact dependency bootstrap to project lock instructions; do not relax those instructions just to get green):

```bash
python -m pytest -q tests/test_qpr01_campaign_identity.py tests/test_qpr02_data_plane.py tests/test_qpr03_source_intake.py
python -m pytest -q tests/test_gpr01_research_economic_graph.py tests/test_gpr01_v22_delta.py
python -m pytest -q tests/test_gpr02_solana_parallel_radar.py tests/test_gpr03_sui_shadow.py
python -m pytest -q tests/test_dynamic_asset_resolution.py tests/test_dynamic_correlation_ledger.py tests/test_dynamic_flash_capital.py tests/test_dynamic_promotion_campaign.py tests/test_dynamic_relations.py tests/test_dynamic_universe.py tests/test_ton_radar_dynamic_universe.py
python -m pytest -q tests/test_pr_a_provider_truth_cleanup.py tests/test_native_cpmm_qualification.py tests/test_pr136_rooted_rpc_quorum.py
git diff --check
```

Then run canonical repository qualification/CI targets, hash-lock dependency validation and security scans per workflows (do not claim unspecified commands passed). Explicitly prove:
- Missing/different RPC operator groups never produce independent QPR quorum.
- `FLASHLOAN_PYTH_API_KEY_REFERENCE` stays mandatory for Hermes; no key => no HTTP.
- Odos remains retired from runtime although historical replay fixtures may exist.
- Signer/sender/broadcast unreachable; research/discovery cannot promote itself.
- `READ_ONLY_REAL_DATA_CAMPAIGN_V1` is a separate bounded read-only pass, not a production proof.
- PR #577 storage pressure blocks ingestion when limits cannot be safely reclaimed.

## Phase 4: PR publication / reconciliation receipt

Push integration branch; create a **new PR targeting `main`**, do not choose a previous QPR or radar branch as base. PR body includes:
- source and target SHA and exact PR history;
- list of recovered and preserved owners;
- conflict dispositions for six paths;
- tests and all negative/rejected test results;
- remaining external credentials/provider profile needs;
- explicit `sign_enabled=false` and production blocked;
- no claim of merge before actual GitHub main SHA/PR merged state re-check.

**Gate:** DIN-00 begins only from the reconciled `main` or a verified integration PR head where all QPR/GPR owners and inherited main owners actually coexist.
