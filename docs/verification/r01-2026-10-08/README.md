# R-01 verification: PASS_WITHOUT_REMERGE

Verified main `103c13795f1d2ac1fa88cf02bba1e9bb2e2477cf` against assignment PR #583
at `e059b1551dd575e25f54979fbe73316bbd0ce316`. No reconciliation code was changed.

The refreshed GPR branch is 0 ahead / 53 behind main; UXE is 0 / 71; QPR is
1 / 90. The only QPR-only commit is merge `476c3782a813323b6bb279fe08cb834bf80035c0`
(#571). Its second parent is already an ancestor of main. All 36 introduced
paths remain present; its GPR source and tests are byte-identical to main.
Only the start/context documents subsequently changed. Disposition:
`ALREADY_EQUIVALENT`; no cherry-pick or repeated merge.

The receipt records live GitHub API base/merge metadata for #568–#583 separately
from the unchanged historical `RECONCILIATION_RECEIPT.json`. #579–#582 are merged
into main. The historical receipt's `merged=false` remains a creation-time fact.
Seventeen QPR, GPR, DIN, asset resolver, Dynamic Universe, capital graph and
runtime owner modules loaded successfully. The owner diff matrix records current
hashes and the narrow DIN changes since RCN-00; existing graph and campaign owners
are retained. Provider truth #566, Dynamic Universe #576 and storage pressure #577
remain in main's ancestry.

Current checks (not copied from older receipts):

- PR #583 `offline/verify_bundle.py`: PASS, 27 disabled candidates, 17 signatures,
  10 upstream pins. Run from a temporary Git archive of that exact PR head;
  assignment docs were not merged into main.
- Focused QPR/GPR/DIN/Dynamic Universe/capital/Jupiter/Kamino tests: 352 passed.
- Full `python scripts/verify_repo.py`: exit 0, 5331 passed, 1 deselected;
  dependency audit, quality gates, package smoke and authority checks passed.

`RECEIPT.json` includes exact heads, API results, owner hashes and log digests.
Full logs are retained locally in `/tmp/r01-focused.log` and
`/tmp/r01-full-verifier.log`. No account creation, signing, sending or production
promotion occurred. R-02 may proceed, but requires its own actual protocol-state
and decoder evidence. This verification does not qualify live capital.
