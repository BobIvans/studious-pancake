# ROADMAP-PR-020+021: Studious research owner

This change implements the offline model slice of the combined PR-020+021 strategy. SCE owns jobs, reviewed profiles, cancellation and local context. Studious owns availability selection, lender arithmetic, clearing and campaign trials. No signer, sender, RPC fetch, new market scheduler or new capital authority is introduced.

The registered command is `python -I -X utf8 scripts/run_research_qualification.py --request <operator-file>`. `--catalog` lists actual callable owners and mode gaps. The request pins a clean Git commit, exact dataset/config SHA-256, run ID and external output root. Run-directory creation claims the ID before effects. Complete repeats verify manifest, request and trial digests; incomplete repeats require reconciliation and do not execute again. Reports distinguish process completion, partial campaign, useful domain calls and qualification.

Datasets are JSONL `occ.research-observation.v1`, exclusively labelled `OFFLINE_FIXTURE`. Every record binds an installed `NormalizedObservation`, payload hash, anchor and declared upstream families. The derived temporary SQLite index delegates revision/availability selection to `select_as_of`, avoids a total record cap and accounts for future, superseded, missing, stale and duplicate opportunities. A shared upstream is never an independent corroborating vote. The installed generation cache key contract is exposed for consumers; this synchronous campaign does not claim network cache/quota qualification.

Five pack evaluators are executable:

| Pack | Checked model | Remaining qualification |
|---|---|---|
| circular_triangular | Supplied leg continuity, same domain, quote times, lender terms, exact repayment, complete declared common-unit costs | Protocol decoding, price impact and real opportunity discovery |
| liquidation_swap | Point-in-time eligibility/oracle/collateral assumptions plus supplied route | Actual account/oracle decoding and liquidation instruction evidence |
| peg_wrapper | Supplied redemption entitlement, delay and liquidity plus route | Real claim rights and conversion adapter |
| intent_clearing | Existing finite lot solver plus independent fill/limit/access/time/conservation verifier | General optimality, solver access and native settlement |
| capital_timeline | Supplied cross-chain/basis/funding timeline and cashflows, capital lock, availability and settlement failures | Real financing, venue, hedge and funding cashflows |

Costs must be integer atomic units in one explicitly declared asset/decimals. All eight mandatory families (borrow, dex, network, priority, tip, failure, slippage, latency) must be present; unknown costs block net qualification. Conversion from another asset must be performed by a qualified upstream owner before this contract. Borrow fee must equal repayment minus principal and carry `included_in_quote=true`: it is already included in required repayment. Other rows with that flag are included in the supplied gross quote, and all remaining rows are subtracted exactly once.

`instructions_supported`, entitlement and settlement fields are fixture assumptions; they do not attest protocol support or execution rights. Delayed redemption is directed to a capital model; future cashflows never repay an atomic flashloan. Every trial includes whether the handler ran. Failed invocations remain in the ledger but do not establish a useful campaign. A campaign with zero valid domain evaluations is `INVALID_CAMPAIGN`.

The config freezes seed, input identity and criteria/holdout digests. The holdout digest is a binding; a holdout partition or benchmark is not evaluated by this command. `MODEL_REPLAY_COMPLETED` proves finite model work, including negative outcomes. Every receipt retains `live_enabled=false`, `transactions_sent=0`, `release_authorized=false` and model limitations.

Validation commands:

```sh
python -m pytest -q tests/market_data_evolution tests/lending tests/mechanism_discovery tests/test_pr148_market_economics_kernel.py tests/test_agg01_financing_contracts.py tests/test_market_scale_replay_entrypoint.py --disable-socket --allow-unix-socket
python scripts/quality_gate.py
python scripts/verify_market_data_evolution.py --json
```

The tests include a nonempty Hypothesis stateful lender-arithmetic corpus; it is not protocol-runtime qualification. Real acquisition/PAPER, Dell installed behavior, broader V5 lifecycle qualification, usefulness ablations and semantic closure of source criteria remain open in the linked SCE ledger. Existing PR-010..019 owners must be integrated separately.
