# Actual main and retained blocked evidence
## GitHub state — 2026-10-08
- `main` audited at `8e222fcddb7fd3bc6e5720d9585e5d5903812294` (merge PR #585).
- PR #584 `R-01: verify reconciliation without remerging legacy branches` merged into main at 02:01:29 UTC.
- PR #585 `R-02: retain real read-only observations and pinned-state blockers` merged into main at 02:01:49 UTC. Upstream R&D PR #583 remains an open draft on main and is not an ancestor of the main commit; its docs were accessed by Codex through Git archive and may not be present under main path.
- **Do not rerun R-01 or re-merge legacy branches.** Verify main/R-01 on every new implementation worktree.

## Canonical recorded source of truth
- `docs/verification/r02-2026-10-08/README.md`
- `docs/verification/r02-2026-10-08/RECEIPT.json`
- `docs/verification/r02-2026-10-08/CAPTURE.json`
- `docs/verification/r02-2026-10-08/INITIAL_CONNECTIVITY.json`
- `docs/verification/r02-2026-10-08/capture_prerequisites.py`

### Actual read results, not new claims
- Jupiter: Solana genesis `5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d`; finalized slot `454401538`. FlashloanAdmin PDA `ALXWtv2P4GqH1B7Lq731joag52yRBRqmHV4naiXPTYWL`, owner `jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS`; 93 bytes; status true, fee 0, no active flash amount. **Not proof of reserve liquidity**.
- Kamino: executable program `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD` observed at same slot; **no market/reserve snapshot and no bytecode attestation**.
- NAVI: Sui GraphQL checkpoint `331514367` (digest in INITIAL_CONNECTIVITY.json); subsequent read timed out. No NAVI pool object state observed.
- P0: no wallet-specific query; on-chain existing marginfi account and authority unknown. No account created.
- `qualified_edges=[]`; 27 previous catalog candidates disabled; signing/sending false.
- #585 documented 35 focused passing tests and canonical offline verifier 5,339 passing on its own code. **These are historical results, NOT this R&D's test run.**

## Existing internal owners (do not duplicate)
- `src/qualification_campaign/` profiles/transport/credentials/governed source evidence; `src/gpr_sui_shadow/` Sui GraphQL (no legacy JSON RPC); `src/solana_parallel_radar/` admission.
- `src/economics/flash_capital_graph/graph.py` owns actual `FlashCapitalEdge` and lender whitelist.
- `src/lending/jupiter_lend.py` existing pinned admin + instruction contract; `src/lending/agg03_financing_ports.py` Jupiter financing snapshot; `src/lending/kamino.py` + `kamino_real_conformance.py` existing shadow and proof.
- `src/providers/marginfi/` Project0 historic shadow source, `src/lending/protocol_registry.py` genesis/deployment admission.
- `src/economics/non_monotonic_sizing.py`, `src/execution/exact_simulation.py` already own sizing & simulation. New reader connects to existing owners, never introduces second graph, transaction kernel or authority.
