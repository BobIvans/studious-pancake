# CODEX START HERE — GPR Parallel Radar R&D

This planning PR is stacked on QPR-03 PR #570 / head `7132f7341661368917bcc3cf1618a93de96327f8`.

The complete source-of-truth package is stored beside this file as:

- `GPR_PARALLEL_RADAR_RND_2026-10-06.zip`

Extract/read the complete archive before implementation. Inside it, start with:
1. `CODEX_START_HERE.md`
2. `MASTER_CONTEXT.md`
3. `QPR03_COMPATIBILITY.md`
4. `ARCHITECTURE_CONTRACT.md`
5. `IMPLEMENTATION_ROADMAP.md`
6. `SOURCE_MATRIX.md`
7. `ASSET_PLACEHOLDERS.json`
8. `WATCH_UNIVERSE_PLACEHOLDERS.json`
9. `ANOMALY_TAXONOMY.json`
10. `ACCEPTANCE_TESTS.md`

Also read the existing QPR-03 implementation handoff:
- `docs/roadmap/prequal-rnd-2026-10-06/implementation/QPR-03.md`
- `docs/roadmap/prequal-rnd-2026-10-06/implementation/handoff.md`
- `docs/roadmap/prequal-rnd-2026-10-06/implementation/handoff.json`

## Immediate implementation scope

Do **not** implement the full package in one code PR.

First re-check the unresolved review findings on PR #569/#570. Fix only findings that are still real and directly block this wave.

Then implement only:

**GPR-01 — Research Economic Graph + Verification Queue**

GPR-01 must:
- sit above the Solana-specific QPR-03 Candidate/SourceIntakePlane;
- provide chain-neutral research identities for Solana, Sui and TON;
- preserve QPR-03 provenance and negative evidence;
- materialize symbolic relationships only at the research layer;
- reject unresolved asset placeholders from exact graph promotion;
- rank candidates for bounded verification;
- feed exact Solana verification through existing QPR-02 authority;
- reuse existing UniversalArbitrageGraph / multihop / PR118 / route graph owners rather than duplicate them.

After GPR-01 passes, Solana GPR-02 and Sui GPR-03 may be implemented in parallel.

## Asset identity rule

The package intentionally contains **no mint addresses, Sui coin types or TON jetton addresses**.

Do not fill them from memory, ticker matching or external heuristics while implementing GPR-01. Every canonical address/type must be a separate evidence-backed onboarding step later.

## Safety boundary

No signer. No sender. No submission. No live capital. No production promotion.

Stop after GPR-01 and report:
- changed files;
- exact guarantees;
- unresolved QPR/base blockers;
- proof that the symbolic universe loads deterministically;
- proof that no placeholder can enter exact graph;
- recommended split for Solana GPR-02 and Sui GPR-03.
