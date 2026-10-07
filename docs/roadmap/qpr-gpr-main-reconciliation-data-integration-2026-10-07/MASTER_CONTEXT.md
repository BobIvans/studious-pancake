# MASTER_CONTEXT — проверенный audit-to-execution контекст

**Repository:** https://github.com/BobIvans/studious-pancake  
**Audit date:** 2026-10-07  
**Observed `main` HEAD:** `72406c0e8a945fe07859807aa5107a8d10043fde` (volatile; refresh before implementation).  
**Observed integration source branch HEAD:** `rnd/gpr-parallel-radar-2026-10-06` → `0f13b51cf772abbdfe14356009d82c002caa0ac4`.  
**Common merge base seen in GitHub compare:** `ac6297e3f174d073c524099f599490edfe30f7b1`.

## Confirmed GitHub PR destinations

| PR | Subject | Original target | Merged | Main implication |
| --- | --- | --- | --- | --- |
| #566 | Provider Truth Cleanup | `main` | yes | Retire Odos runtime, require authenticated Hermes, preserve independent RPC operators |
| #567 | Master QPR handoff | `main` | **no** | Do not mistake old PR for the merged integration |
| #568 | QPR-01 authority | `codex/prequal-rnd-master-2026-10-06` | yes | Not automatically in main |
| #569 | QPR-02 governed data-plane | `codex/qpr-01-campaign-authority` | yes | Not automatically in main |
| #570 | QPR-03 source intake | `codex/qpr-02-qualification-data-plane` | yes | Not automatically in main |
| #571 | GPR-01 research graph | `codex/qpr-03-campaign-source-intake` | yes | Not automatically in main |
| #572 | GPR-02 Solana | `rnd/gpr-parallel-radar-2026-10-06` | yes | On radar integration branch |
| #573 | GPR-03 Sui | `rnd/gpr-parallel-radar-2026-10-06` | yes | On radar integration branch |
| #575 | UXE R&D | `rnd/gpr-parallel-radar-2026-10-06` | yes | 16 documentation files, **zero src files** |
| #576 | Dynamic Universe implementation | `main` | yes | 19 source files and tests already in main |
| #577 | Verified storage-pressure management | `main` | yes | Retain current protections on integration |

Evidence: [PR 568](https://github.com/BobIvans/studious-pancake/pull/568), [569](https://github.com/BobIvans/studious-pancake/pull/569), [570](https://github.com/BobIvans/studious-pancake/pull/570), [571](https://github.com/BobIvans/studious-pancake/pull/571), [572](https://github.com/BobIvans/studious-pancake/pull/572), [573](https://github.com/BobIvans/studious-pancake/pull/573), [575](https://github.com/BobIvans/studious-pancake/pull/575), [576](https://github.com/BobIvans/studious-pancake/pull/576), [577](https://github.com/BobIvans/studious-pancake/pull/577).

## Measured divergence, not inference

GitHub compare `main...rnd/gpr-parallel-radar-2026-10-06`: **diverged, 135 commits ahead on radar branch, 40 behind current main**, compared at the audit timestamp. Comparing each side against the merge base shows 205 changed paths on radar and 150 on main; **six overlapping paths** are conflict-review candidates (not necessarily text merge conflicts):

- `config/requirements-lock.json`
- `requirements-dev.lock`
- `requirements.lock`
- `src/market/native_cpmm_capture.py`
- `src/paper_shadow/native_cpmm_qualification.py`
- `src/runtime/runtime_entrypoint.py`

Direct file fetch on `main` returned 404 for `src/qualification_campaign/cli.py`, `src/solana_parallel_radar/cli.py` and `src/gpr_sui_shadow/campaign.py`; all three exist on radar branch. This is an **ownership gap**, not just a missing README.

## Existing code that MUST be preserved

From QPR/GPR source branch:
- `src/qualification_campaign`: QPR-01 authority, QPR-02 provider governance/independent quorum, QPR-03 source intake and raw/negative evidence.
- `src/research_economic_graph`: asset/repr research identity, verified graph, evidence-aware verification queue.
- `src/solana_parallel_radar`: GPR-02 bounded Solana radar, 0x/Jupiter guarded quote, exact state.
- `src/gpr_sui_shadow`: GPR-03 research-side Sui, checkpoint/object verification.

From current main:
- `src/assets/resolution` and `src/asset_mint_registry_pr117.py`: dynamic mint/coin-type identities.
- `src/discovery/dynamic_universe`: bounded live discovery incl. TON read-only.
- `src/strategy/relation_generators`, `src/research/correlation_ledger`, `src/economics/flash_capital_graph`: relation, residual, financing graphs.
- Existing `MarketObservationV2`, `ShadowMarketGraphIngest`, `UniversalArbitrageGraph`, paper/size/cost/durability owners.
- PR #566 provider-truth constraints and PR #577 storage-pressure admission/retention logic.

PR #576's `IMPLEMENTATION_REPORT.md` explicitly says the selected branch lacked QPR owner and external provider SDK bridges; it describes a **library/diagnostic implementation**, not production-integrated capture. Therefore do not implement parallel identity, journal, quotas, shadow-market truth, or promotion owners.

## Precedence when resolving conflicts

1. Current `main` **fail-closed** runtime, PR #566 Pyth authentication/retired Odos, PR #577 pressure protection, dependency/security lock updates; preserve by default.
2. Restore QPR/GPR semantics and files from actual stacked integration history, preserving exact evidence authority and independent operator requirement.
3. Adapt PR #576 owners to restored QPR/GPR through typed ports/adapters; do not turn discovery into execution evidence or duplicate graph/persistence owners.
4. Treat UXE (#575) as a **specification backlog** pending implementation/verification, not live providers.
5. Every conflict resolution must include changed behavior, old/new tests, and one explicit evidence trail.

## Mission / finish line

**RCN-00:** integration PR based on the latest `main` that retains both generations' behavior and passes focused QPR/GPR/main tests. **DIN:** activate governed API sources in small sequential PRs, demonstrate real bounded reads with physical receipts and reproducible replay, and advance to 24h paper qualification **without** enabling wallet signing or sending.

Do not merge these docs alone as evidence of RCN-00 completion.
