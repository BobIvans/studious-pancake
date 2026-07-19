# PR-016 Phoenix Legacy / OpenBook V2 shadow orderbook architecture

PR-016 adds a canonical, shadow-only orderbook domain for Phoenix Legacy spot and OpenBook V2. Registry entries are centralized in `docs/registry/orderbook_venues.json`; business logic must load `VenueProgramSpec` instead of scattering program IDs. Both venues are explicitly distinct from Phoenix perpetuals and Serum/OpenBook V1.

Pinned maintainer sources checked on 2026-07-19: Phoenix Legacy SDK (`Ellipsis-Labs/phoenix-sdk`), `phoenix-common` docs.rs program/state docs, OpenBook V2 (`openbook-dex/openbook-v2`, release page showing v1.2 / 9344744), and Solana RPC/token docs for `getMultipleAccounts`, `accountSubscribe`, `simulateTransaction`, versioned transactions, SPL Token accounts, and Token-2022 transfer fees. The current registry deliberately marks fixture markets shadow-only and requires opt-in read-only mainnet verification before adding live mainnet market allowlists.

Snapshots are binary bytes with owner, discriminator, data length, source slot, context slot, observed time, decoder version, lot/tick config, taker fee source, L2 bids/asks, and raw account SHA-256 hashes. A snapshot with slot skew beyond profile policy rejects as `SLOT_INCONSISTENT`.

The shared quote engine consumes sorted L2 depth only: asks ascending for buy-base, bids descending for sell-base. All amounts are integer base units/lots and exact `Fraction` VWAPs. Base lots, quote lots, ticks, and taker fees round conservatively; dust, insufficient depth, unknown fees, and unrepresentable thresholds fail closed.

Venue account lifecycle is separate from detection and has no sender. Phoenix requires a validated seat; OpenBook V2 requires a validated OpenOrders account. Missing accounts return explicit preparation plans and `VENUE_ACCOUNT_NOT_READY`; they are not hidden mutations in opportunity planning.

Orderbook instructions are IOC/taker-only raw `Instruction` values, followed by fixture-proven settlement where required. Post-simulation proof must show no residual order and no locked funds; missing evidence is `ORDERBOOK_POSTCONDITION_UNPROVEN`.

The orderbook-AMM planner composes `MarginFi start/borrow -> CLOB IOC/settle -> AMM -> repay/end` or `MarginFi start/borrow -> AMM -> CLOB IOC/settle -> repay/end` through the existing PR-008 compiler and PR-013 simulation/reconciliation models. Execution profiles gate account counts, serialized-size budget, CU limit, depth level count, Token-2022 support, ALT policy, and slot skew before expensive simulation.

Live remains disabled until PR-018. PR-016 never signs, submits, sends a Jito bundle, loads secrets, or bypasses `LIVE_GATE_NOT_OPEN`.
