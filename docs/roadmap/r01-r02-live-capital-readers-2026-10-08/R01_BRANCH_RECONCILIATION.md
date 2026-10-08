# R-01 — verify existing reconciliation, then close remaining differences

R-01 is FIRST. PR #579 has already implemented the broad reconciliation. The next implementation must **verify**, not replay, that merge.

## Current decision
1. Pull and pin latest upstream main; do not assume 103c137 is still HEAD.
2. Read RECONCILIATION_RECEIPT.json plus PR #579 files and GitHub merge/base targets for #568–#582.
3. Compare the three named legacy branches to main. At audit time GPR and UXE were **behind-only**; QPR was one commit ahead. Inspect that QPR commit's parent, actual patch, files and merge ancestry. Mark UNIQUE_USEFUL / ALREADY_EQUIVALENT / EMPTY_OR_METADATA / CONFLICTING_UNSAFE. Cherry-pick only a genuinely useful delta with independent tests; no blanket merges or force push.
4. Build an owner/diff matrix over: src/qualification_campaign/**; src/solana_parallel_radar/**; src/gpr_sui_shadow/**; src/research_economic_graph/**; src/assets/resolution/**; src/discovery/dynamic_universe/**; src/economics/flash_capital_graph/**; src/runtime/runtime_entrypoint.py; src/market/native_cpmm_capture.py; src/paper_shadow/native_cpmm_qualification.py; requirements*.lock; config/runtime_authority* and resource authority maps.
5. Verify main retained #566 provider truth, #576 Dynamic Universe, #577 storage pressure, and #579 QPR/GPR authority, without dual authority owners or weakened gates.
6. The recorded receipt can be stale; **report actual GitHub merged state separately** rather than rewriting historical evidence to look as though it was contemporaneous.
7. Only after R-01 gates pass create R-02 implementation PR(s) targeted at main.

## Repeatable commands
~~~bash
git fetch origin --prune
git checkout main
git pull --ff-only origin main
git rev-parse HEAD
git merge-base --is-ancestor rnd/gpr-parallel-radar-2026-10-06 main
git merge-base --is-ancestor rnd/universal-source-execution-slumlord-2026-10-07 main
git log --left-right --cherry-pick --oneline main...codex/qpr-03-campaign-source-intake
git diff --stat main...codex/qpr-03-campaign-source-intake
python scripts/verify_repo.py
~~~

NOTE: if old refs only exist under origin/*, use the remote-tracking name. Do not confuse symmetric three-dot diff with patch equivalence or merge ancestry; inspect both git diff and git log plus GitHub merged base.

## Acceptance
- Document current main SHA, current exact ahead/behind counts, PR target branches, QPR unique-commit disposition and proof.
- All named R-01 owners exist and load. No duplicate graph or qualification authority and no silent relaxations to source/campaign quota, evidence, replay, live, storage or economic gates.
- Run focused tests for QPR, GPR, Dynamic Universe, DEX reader admission, and capital graph; then full canonical verifier. Log actual result; never copy historical pass counts as a new test run.
- sign/send false. No code merge needed if existing RCN-00 passes: write R-01 PASS_WITHOUT_REMERGE receipt.
- If a blocker remains: stop R-02 mutation and deliver a minimal R-01 fix PR on main, with issue/evidence.
