# Recommended PR Sequence

| # | ID | PR | Priority | Campaign after? | Findings |
|---:|---|---|---|---|---|
| 1 | `QPR-01` | **Campaign Identity + Runtime/Release Authority Unification** | P0 | NO | AUTH-001, AUTH-002, CLI-001 |
| 2 | `QPR-02` | **Qualification Data Plane: Provider Profiles + Independent RPC Quorum** | P0 | YES_CAPTURE_ONLY | DATA-001, DATA-002, SLOT-001, RATE-001, OBS-001 |
| 3 | `QPR-03` | **Fast Source Intake Plane + Free Discovery Plugins** | P0 | YES | SRC-001, SRC-002, LIC-001, NET-001, ENV-001 |
| 4 | `QPR-04` | **Provider Contract Exactness + Documentation Drift Refresh** | P1 | YES | PROV-001, DEBT-001, DATA-002 |
| 5 | `QPR-05` | **Project0 / MarginFi Current Deployment Rebind** | P0 | YES_BUT_MARGINFI_BLOCKED_UNTIL_DONE | PROT-001, ORACLE-001 |
| 6 | `QPR-06` | **Continuous Qualification Capture + Holdout + Evidence Journal** | P0 | YES_24H | QUAL-001, QUAL-003, OBS-001, TIME-001 |
| 7 | `QPR-07` | **Campaign Persistence Authority then Active Store Cutover** | P0/P1 | YES | PERS-001 |
| 8 | `QPR-08` | **Venue Expansion: Raydium CLMM -> Meteora DLMM -> Orca -> Orderbooks** | P1 | YES_MULTI_FAMILY | VENUE-001, TOKEN-001, ORDERBOOK-001 |
| 9 | `QPR-09` | **Costs/Financing + Net Qualification** | P1 | YES_NET_ANALYSIS | QUAL-004 |
| 10 | `QPR-10` | **Proof Islands Cutover + Release-bound 72h Soak** | P0_PROMOTION | PROMOTION_ONLY | PROOF-001, QUAL-005, PERS-001 |

## Fastest usable checkpoint
После **QPR-01 + QPR-02** уже можно начать non-synthetic read-only capture. После **QPR-03** можно быстро расширять universe через бесплатные discovery sources. Campaign verdict остаётся BLOCKED, пока не выполнены QV gates.
