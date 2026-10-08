# GPR-01 — reconciled V2.2 implementation base

The completed GPR-01 implementation is published with
`GPR-01_IMPLEMENTATION.md` and the additive V2.2 identity/transport delta.
The original QPR-01/#568, QPR-02/#569 and QPR-03/#570 owners remain unchanged.

Verified contract corpus:
- 92 research identities, including distinct Sui sSUI;
- 14 V2.2 first-campaign families;
- 9 unchanged DeepBook identifier refs;
- 4 non-token transport transformations;
- independent heat/execution_class/evidence_state;
- startup HARD_BOUND receipts and bounded verification work;
- USDT0/CCTP/Wormhole edges remain non-atomic research/rebalance relations.

Validation: 226 offline tests passed; mypy, lint and formatting passed.
Tests cover both the additive delta and prior QPR/exact graph compatibility.

The upstream reconciliation point is
`ad1cf6be8faf32e91bd935316aebe259270c8375`.
The exact implementation SHA is the commit introducing
`src/research_economic_graph`; use the verified publication receipt and Git refs
rather than embedding this file's own commit SHA.

GPR-02 and GPR-03 must start in separate branches/worktrees from the single
verified, published GPR-01 implementation commit. They share these published
contracts only. Each must produce independent tests and bounded real-data
findings before GPR-04+ is considered. No live execution authority is granted.
