# HANDOFF TASK — OCA-W4C completion + campaign close-out (2026-11-22)

**For:** next coding agent, resuming the PR #666 implementation-stack campaign.
**Hard constraints:** NO merge of any PR. No CAPTURE_ONLY runs. No provider activation, credential checks, account/ATA creation, signing, sending, borrowing, spending, deployment or LIVE. Keep `sign_enabled=false`, `send_enabled=false`, `live_enabled=false`, `execution_authority=NONE` everywhere. One owner/worktree/PR per lane. Never force-push. Stop with the final report and await the user's decision.

## 0. Verified current state (2026-11-22)

- **origin/main:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54` (unchanged; nothing merged).
- **PR #717 (OCA-W4C, final stack):** branch `codex/oca-w4c-web3-strategy-intel-2026-11-22`, head **`3ef0f9f8`** (final correction round pushed). Worktree: `sp-worktrees/oca-w4c`.
  - Correction round applied and fixture-proven: cohort attribution rework (filter-before-metrics, config-generation binding, UNATTRIBUTED separate, adversarial contamination test), continuation cursor consumed-position tracking + unprocessed-remainder gate + multi-page test (≥3 pages, 30 refs exactly once), dependency-pin UTF-8 byte offsets + `_DEP_PIN_RE` missing `re.MULTILINE` (latent bug), MCP JSON-RPC boundary (-32600/-32602, required-key validation, survival test), docstring 11-tool correction.
  - Local verification at `3ef0f9f8`: 126 passed / 3 failed (pre-existing Windows-asyncio trio — see §6), packaging 8/8, black/flake8/mypy clean, `scripts/quality_gate.py` PASS.
  - **CI status at handoff: 30 checks pass, 3 PENDING** (`pr357`, `pr358`, `Repository verification` on run ids under PR #717 checks for head 3ef0f9f8). Correction-round comment posted: https://github.com/BobIvans/studious-pancake/pull/717#issuecomment-7083815535
- **PR #666 (design, actualized):** branch `codex/intelligence-operating-plane-design-2026-11-21`, head **`68474f43`**. Worktree: `sp-worktrees/pr666-actualize`. Main merged in; baselines refreshed; `WORK_PACKAGE_MATRIX.json` has `current_base_sha`, `implementation_delivery_crosswalk` (dependency-closed chains: chain_a [684,685,686,700,702,703], chain_b [689,690,704,707,709,706,713,717], independent [680,681,682,687,688], `not_yet_opened` map). Review round 1 fixes applied + pushed. **A fresh review verdict on `68474f43` has NOT yet been obtained.**
- **PR #718 (readiness audit):** branch `codex/oca-strategy-readiness-audit-2026-11-22`, head **`9d1c32f3`**. `READINESS_MATRIX.json` + verifier (exit 0) + report + receipt. `design_source.head` pinned to `68474f43` (bb38a1fe labeled historical).
- Other open implementation PRs (all based on main `0a0c8ad9` unless noted): #680 W0, #681 W0A, #682 W0C, #684 W0B, #685 W4, #686 W11, #687 W1, #688 W3, #689 W13, #690 W14, #704 W2, #706 W10, #707 W15 (merge of #690+#704), #709 W18 (stacked #707), #713 W20 (merge #709+#706), #700 W0B2 / #702 W4B / #703 W11B (chain A stack).
- Governance refs: **#683 = master dependency DAG (OPEN draft)**, **#679 = CAMPAIGN_START/WIN owner (OPEN)**.
- Worktrees existing: `sp-worktrees/{oca-w0,oca-w0a,oca-w0c,oca-w0b,oca-w4,oca-w11,oca-w1,oca-w3,oca-w13,oca-w14,oca-w0b2,oca-w4b,oca-w11b,oca-w2,oca-w10,oca-w15,oca-w18,oca-w20,oca-w4c,pr666-actualize,readiness-audit}`.
- **Interpreter:** `"C:\Users\ivans\Downloads\studious-pancake-main (IDE)\studious-pancake\.venv\Scripts\python.exe"` (3.13.x). tree-sitter + tiktoken installed locally only; pyproject `dev` profile carries the 4 pinned tree-sitter packages; `requirements*.txt/.lock` regenerated and committed via `scripts/lock_requirements.py`.

## 1. TASK A — finish PR #717 (do first)

1. `gh pr checks 717` — wait for the 3 pending checks. Expected: all green (the 3 previously failing tests — MCP smoke 11-tool count, packaging contract, requirements pins — are fixed and locally verified). If any fail:
   - Fetch the failed log (`gh run view <id> --log-failed`), fix in the `oca-w4c` worktree, re-run locally (`pytest tests/intelligence tests/test_pr025_packaging.py -q --disable-socket --allow-unix-socket`, `scripts/quality_gate.py`), commit, push. No scope creep.
2. **Fresh independent code+security review on the EXACT head `3ef0f9f8`** (a review agent was launched in the previous session but did NOT report before handoff — its findings are lost; re-run it). Adversarial checklist to give the reviewer:
   - diagnostics.py cohort rework is real: cohort defined before metrics, `excluded_config_mismatch` counts, UNATTRIBUTED separate, `test_no_cross_cohort_contamination` covers 2 strategies × 2 generations × routes + UNATTRIBUTED;
   - service.py cursor: `processed` counter, slot-exhaustion `break` leaves candidates unprocessed, `ranked_total` is global pre-slice length (no off-by-one), cursor binds task+SHA+budget+dimensions+must_include/exclude, multi-page test ≥3 pages / 30 refs exactly once;
   - extractors.py: `_DEP_PIN_RE` has `re.MULTILINE`, dep-pin/markdown/workflow all map char→byte offsets, non-ASCII byte-slicing fixtures compare to original bytes;
   - mcp_server.py: root/method/params/arguments validation, -32600/-32602, required-keys per TOOL_DEFINITIONS, exactly 11 tools, malformed-frame survival test;
   - security: read-only surface unchanged, history_query git args parameterized, secret exclusion intact, no runtime (non-dev) dependency added, extras == {analytics, service, dev};
   - hygiene: no uncommitted scratch (`fix_*.py` removed), `artifacts/` untracked acceptable.
3. Resolve every applicable finding (P0/P1 mandatory; P2 if cheap), re-run tests, push. Record exact SHA + CI + review verdicts in a correction-round receipt (`audit/W4C_CORRECTION_ROUND_RECEIPT.json`) and comment on the PR.

## 2. TASK B — close out PR #666 actualization

1. `gh pr checks 666` (docs-only; expect green) and obtain a **fresh independent review verdict on head `68474f43`** (round-1 verdict NEEDS_FIXES was addressed: dependency-closed crosswalk chains, 689 dedup, 7-operation enumeration, §3.7 placement, wording, dependency prose, `not_yet_opened` map — all pushed). The reviewer must confirm each round-1 P1/P2 is actually fixed in the final tree.
2. If clean: update the PR body with the actualization summary (merge of main, crosswalk, review verdict). Do NOT merge.

## 3. TASK C — PR #718 readiness audit close-out

1. `verify_readiness_matrix.py` already OK; `design_source.head` = `68474f43` done.
2. Add the audit summary row to `PARALLEL_EXECUTION_STATUS.json`-adjacent campaign docs only if the user asks; do not touch #683/#679 write scopes.

## 4. TASK D — next implementation PR (after A–C, still one lane at a time)

**Recommended: OCA-W12 license/SBOM gate** (`policy/licenses/`, `tools/license-audit/`, `.github/workflows/dependency-governance.yml`): deps W0/W0A satisfied; covers the 4 new tree-sitter pins (MIT) and the whole lock surface. Acceptance per matrix: path-level license ledger, SPDX + pinned identity, unknown license = BLOCKED, mixed-license tests, subprocess-not-a-GPL-exemption note, SBOM. Alternatives if the user redirects: W10-R (production caller wiring to lift the capture PARTIAL) or P0-3-R CLMM/DLMM capture owners.

## 5. TASK E — final report to the user (after A–C)

Deliver the 7-part report: (1) current main SHA; (2) #666 status + updated diff; (3) #717 status with fixes + fresh CI/review receipts; (4) dependencies + exact merge order (docs/audits first, then chain A #684→#685→#686→#700→#702→#703, then #689→#690→#704→#707→#709→#706→#713→#717); (5) readiness matrix summary (PR #718); (6) next implementation PR + owner + acceptance criteria; (7) remaining blockers + negative results (BLOCKED_AUTHORIZATION / MISSING_CAPTURE_OWNER / MISSING_PIN / LIVE_EVIDENCE_GATE; PRE_EXISTING_WINDOWS_ASYNCIO; #673+#676 `schema_registry.json` conflict; format_targets.txt EOF conflicts resolved by union).

## 6. Known pre-existing issues (do NOT re-litigate)

- 3 test failures on clean main `0a0c8ad9`: `tests/intelligence/test_pressure_manager.py::test_real_boundary_pauses_canonical_supervisor_and_persists_receipts`, `tests/intelligence/test_rpc_campaign.py::test_long_retry_after_never_shortened_or_immediately_retried`, `tests/intelligence/test_rpc_campaign.py::test_short_retry_after_retries_read_and_terminal_429_is_typed` — Windows ProactorEventLoop teardown; recorded in every receipt as `PRE_EXISTING_WINDOWS_ASYNCIO`.
- `config/format_targets.txt` EOF-append conflicts across lanes — resolve by union when merging.
- #673+#676 both touch `src/resources/schema_registry.json` — conflict flag recorded.
- tiktoken/tree-sitter are installed locally in `.venv` only; never add to `requirements.lock` runtime section by hand (use `scripts/lock_requirements.py`).

## 7. Verification commands (per lane)

```bash
PY="C:\Users\ivans\Downloads\studious-pancake-main (IDE)\studious-pancake\.venv\Scripts\python.exe"
$PY -m pytest tests/intelligence -q --disable-socket --allow-unix-socket
$PY -m pytest tests/test_pr025_packaging.py -q --disable-socket --allow-unix-socket
$PY -m black --check src/intelligence tests/intelligence
$PY -m flake8 src/intelligence tests/intelligence --count
$PY -m mypy --follow-imports=silent --ignore-missing-imports src/intelligence/repo_graph src/intelligence/universal_data_plane src/intelligence/performance_diagnostics src/observability/runtime_capture src/intelligence/operation_context
$PY scripts/quality_gate.py
$PY docs/roadmap/intelligence-operating-plane-2026-11-21/audit/strategy-data-source-readiness-2026-11-22/verify_readiness_matrix.py
```
