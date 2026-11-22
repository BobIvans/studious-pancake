# SCIP/LSP adoption decision (OCA-W0B2)

- **Date:** 2026-11-22 · **Base main:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`
- **Decision:** `NOT_ADOPTED_NO_REPRODUCIBLE_INDEXER` (selective-import gate not met). Zero adoption is a valid outcome per WORK_PACKAGE_MATRIX.json guardrails and PR #666 expansion §4 ("adopt functions, not tool piles").

## Measured basis

| Criterion | SCIP (scip-python et al.) | LSP (pyright/pylsp) |
|---|---|---|
| Reproducible offline indexer | No: scip-python requires an npm/Java-scip toolchain download; index regeneration per commit is not reproducible in the offline CI sandbox | No: LSP servers are long-running interactive processes, not batch indexers; determinism across runs is not guaranteed by the servers themselves |
| Deterministic same-SHA output | Not demonstrated by upstream (no checksum guarantee) | Not applicable |
| License path | Apache-2.0 (scip bindings) — acceptable | Mixed per server |
| Added value over current pipeline | Cross-file type resolution beyond stdlib-AST; not blocking: golden recall already 1.0 (W4) / 0.9286→1.0 measured with exact-ID+FTS+graph backend | Dynamic-dispatch resolution; current policy keeps those `AMBIGUOUS/UNRESOLVED` by contract (no same-name promotion) |
| Cost | 2+ new toolchains, lock/supply-chain surface (W12 gates), runtime per commit | Editor-infrastructure integration, no batch determinism |

## Remediation path (re-open gate when any of these holds)

1. A reproducible, offline, checksum-verifiable SCIP indexer for Python 3.13 becomes available → benchmark against the golden corpus (same SHA, same questions) with `benchmarks/intelligence` harness; adopt only if it closes a measured recall/precision gap ≥5 points without breaking determinism receipts.
2. OCA-W16 incremental engine needs compiler-grade dependency edges that stdlib-AST + tree-sitter cannot produce → selective SCIP import for the affected language, isolated HOME profile, license path re-review (W12).
3. A measured critical-omission > 0 on the golden set attributable to unresolved dynamic dispatch → evaluate LSP batch mode (`pyright --outputjson`) as a non-canonical *evidence feed* with provenance `COMPILER_RESOLVED_PROPOSED`, never auto-promoted to VERIFIED.

## Reproduction commands (for the reviewer)

```bash
# SCIP: attempt offline index generation (expected: fails without npm toolchain)
python -m pip install scip-python  # NOT executed in this lane; see decision above
# LSP batch probe (non-mutating, for future benchmark):
# pyright --outputjson <path>  # requires npm-installed pyright; not installed here
```

No packages were installed for this decision; the gate stays closed for exactly the reasons recorded above.
