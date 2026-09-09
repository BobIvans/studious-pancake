# MPR-2621 — LST NAV / atomic-exit arbitrage

## Status

- MPR-2621: `NEW_PROPOSED_EXTENSION`
- MPR-2620: `RESERVED_PREDECESSOR_UNOBSERVED`
- accepted base: `main@d23f82e20d10345926742352739b1a6ca3f7a859`
- sender/signing/live: disabled
- circular-arbitrage profile: unchanged
- liquidation profile: unchanged

## Why this is separate from the legacy LST path

`src/ingest/lst_unstake_arbitrage.py` is retained only as source/behavior inventory. It owns raw `aiohttp`, keypair/Jito-shaped dependencies, shared mutable sizing state, float SOL economics and historical route-label assumptions. MPR-2621 does not import or call it.

The new authority is `src/mpr2621_lst_atomic_exit.py`. It accepts already-governed immutable evidence only and has no network, signer or sender dependency.

## First strategy direction

`BUY_DISCOUNTED_LST_THEN_ATOMIC_EXIT_TO_SOL`

1. borrow bounded SOL;
2. acquire one exact qualified LST with guaranteed atomic output;
3. consume no more LST than was guaranteed acquired;
4. use one independently qualified mechanism that returns active SOL in the same transaction;
5. repay exact flash principal/fee obligation;
6. account lender/acquisition/exit/network/priority/tip/rent/failure costs exactly once;
7. require final-message and final-simulation identities plus decoded account deltas;
8. require conservative positive surplus above the strategy floor.

Caller/Jupiter `expected_profit_lamports` is diagnostic only and never authorizes the trade.

## Mechanism taxonomy

Potential same-transaction SOL exit mechanisms are explicitly modeled as:

- `DEX_SWAP_LST_TO_SOL`
- `SANCTUM_ROUTER_LST_TO_SOL`
- `STAKEDEX_WITHDRAW_SOL`
- `PROTOCOL_LIQUID_UNSTAKE`

The following cannot inherit same-transaction flashloan-exit authority:

- `STAKE_ACCOUNT_WITHDRAW`
- `STAKE_ACCOUNT_DEACTIVATION`
- `PROTOCOL_DEPOSIT_SOL_FOR_LST`
- `LST_TO_LST_POOL_SWAP`

A label such as `Sanctum` is not authority. Exit proof must match the capability's exact program-id tuple and account-evidence hash.

## Capability matrix

No wildcard all-LST capability is shipped by this PR. The implementation supports the following qualification states for each exact mint/pool generation:

| Dimension | Required binding |
| --- | --- |
| mint | exact mint identity |
| token semantics | token program, decimals, modeled Token-2022 extensions |
| staking protocol | exact protocol and pool program |
| deployment | pool/program generation, cluster, genesis |
| conversion | one explicit mechanism |
| economics | exact integer/rational rooted NAV state and fee components |
| liquidity | rooted immediate active-SOL capacity |
| route | exact program ids and account-evidence hash |
| provenance | evidence hash and source/SDK pins |
| status | must be `reviewed_executable` |

The test fixture is not a production capability and does not authorize any real mint.

## Current Sanctum/Stakedex source review

Implementation deliberately does not hardcode a static historical LST list. Current upstream review confirms the active `igneous-labs/stakedex-sdk` workspace exposes separate deposit/withdraw interfaces, including `stakedex_withdraw_sol_interface`; the exact deployed program/account/layout generation must still be refreshed and independently qualified before a real capability can move to `reviewed_executable`.

## N01–N72 disposition

Implemented offline in this PR: numbering truth; separate strategy boundary; exact capability identity; mechanism taxonomy; delayed-unstake rejection; integer/rational NAV; epoch/freshness gates; immediate-liquidity cap; bounded sizing; immutable request-local candidate; route/program/account binding; fee separation; exact final-simulation delta requirements; retry/ambiguity boundary; per-LST shadow identity; sender/signer/live false; legacy execution quarantine.

Explicitly downstream / blocked external: current deployed Sanctum/Stakedex/Jupiter golden vectors; governed provider observations; exact installed compiler/firewall composition; accepted MPR-2610 durable per-asset ledger integration; real multi-epoch shadow campaign; installed wheel/image reachability proof; canary prerequisites; any real signing/submission.

No requirement is satisfied by fabricated live evidence.

## T01–T30

`tests/test_mpr2621_lst_atomic_exit.py` maps T01 through T30 directly and covers the sender-free positive staged path plus failure cases for stale NAV, delayed unstake, unsupported token semantics, route spoofing, size/liquidity bounds, fee accounting, exact simulation, residual assets, recursive retry and per-LST shadow isolation.

## Canary blockers

Before any LST canary, at minimum the exact mint/pool generation still needs:

1. current deployed program/account/layout evidence;
2. governed current route observations and source pins;
3. exact compiler/firewall integration on the accepted runtime;
4. exact final-message simulation with raw account evidence;
5. MPR-2610 per-asset durable economics integration;
6. real sender-free shadow evidence across at least one epoch transition and pool-update events;
7. accepted signer/canary/release prerequisites from their canonical owners.

MPR-2621 itself never flips live or canary capability.
