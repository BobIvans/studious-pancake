# Production debt and external compatibility audit — 2026-07-22

## Executive conclusion

The repository is substantially safer and more testable than the historical bot,
but the supported product is still intentionally **not production ready**. The
active entrypoint is discovery/paper-shadow oriented and live mode is hard denied.
The main remaining problem is not a single bug. It is the absence of one fully
wired and externally attested vertical from provider quote through exact economic
settlement.

This audit aggregates the remaining work into four large delivery groups instead
of continuing with dozens of disconnected micro-PRs.

## Evidence reviewed

- Uploaded repository snapshot: 692 files, 487 Python files and 173 test modules.
- `src/resources/capabilities.json` and the supported `flashloan-bot` entrypoint.
- `src/resources/external_contracts.json` and provider conformance artifacts.
- Active paper/shadow composition, planner, compiler, simulation, reconciliation,
  submission, release and soak modules.
- Quarantined legacy execution, Jupiter, Jito and transaction-builder modules.
- Official documentation reviewed on 2026-07-22:
  - Jupiter Swap V2 `/build`: https://developers.jup.ag/docs/api-reference/swap/build
  - Jupiter instruction ordering: https://developers.jup.ag/docs/swap/build/common-instructions
  - Jupiter V1-to-V2 migration: https://developers.jup.ag/docs/swap/migration/metis-to-build
  - Jito low-latency send: https://docs.jito.wtf/lowlatencytxnsend/
  - Solana `simulateTransaction`: https://solana.com/docs/rpc/http/simulatetransaction
  - Solana `getFeeForMessage`: https://solana.com/docs/rpc/http/getfeeformessage
  - MarginFi v2 program docs: https://docs.marginfi.com/mfi-v2
  - MarginFi protocol addresses: https://docs.marginfi.com/protocol-design
  - MarginFi Rust SDK: https://docs.marginfi.com/rust-sdk
  - Kamino KLend SDK: https://github.com/Kamino-Finance/klend-sdk

## What is already strong

- Live mode is explicitly unavailable in the supported capability contract.
- Historical monolith, transaction builder, router and Jito executor are marked
  fixture-only/quarantined and are not imported by the supported launcher.
- A canonical planner, v0 compiler, exact simulation, compute-budget finalizer,
  economic reconciliation, permit-bound sender and finalized settlement model
  already exist as isolated modules.
- Extensive regression tests cover route identity, transport bounds, program
  attestation, dual-clock freshness, account lifecycle, Jito unbundling, rooted
  RPC quorum, CPI call graphs, release evidence and shadow-soak gates.
- Jupiter Swap V2 `/build` is represented correctly as an authenticated GET that
  returns raw instructions, resolved ALT data and blockhash metadata.
- The MarginFi mainnet program ID in the repository matches current official docs:
  `MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA`.

## P0 debt — canonical execution vertical

1. The supported runtime still describes circular arbitrage as detector-only.
2. Paper composition defaults to missing atomic dependencies.
3. No concrete production adapter supplies `AtomicVerticalRuntimeInputs` from real
   discovery evidence.
4. The exact-fee workflow exists but is not active in the supported composition.
5. The durable capital reservation coordinator is not wired to each real attempt.
6. Non-monotonic sizing exists as a library but does not own runtime amount search.
7. Jupiter `/build` is locally reviewed but remote schema freshness is unproven.
8. Jupiter credentialed API conformance is unproven.
9. Jupiter execution conformance is unproven.
10. Jupiter promotion evidence is absent.
11. The repository correctly tracks V2 `/build`, but legacy/quarantined files still
    contain obsolete `/swap/v1/*`, `/swap/v2/quote`, `/swap/v2/swap` and
    `/swap/v2/swap-instructions` assumptions.
12. Official Jupiter ordering requires compute budget, setup, custom pre-swap,
    swap, custom post-swap and cleanup ordering; this must be proven after adding
    MarginFi flash-loan and account-lifecycle instructions.
13. Jupiter `addressesByLookupTableAddress` must remain untrusted until each ALT
    owner, deactivation slot, index and resolved key is validated.
14. Jupiter-provided blockhash metadata must be checked against local slot and
    block-height freshness policy before final simulation.
15. MarginFi source identity remains marked unresolved despite an official program
    address and public source repository.
16. A deployed MarginFi binary hash has not been reproduced and matched with
    `solana-verify` evidence.
17. MarginFi IDL/account layouts/instruction metas are not promoted to complete
    execution evidence in the active capability registry.
18. Bank configuration, liquidity vault, oracle and token-program identities must
    be captured in one coherent rooted snapshot.
19. Health and flash-loan eligibility must be derived from decoded on-chain state,
    not neutral/default values.
20. Flash-loan fee and repayment must be counted exactly once in the typed ledger.
21. Missing ATA creation must reserve payer rent before borrowing.
22. Existing ATA owner, mint and token-program identity must be verified.
23. wSOL funding, `SyncNative`, close authority and cleanup destination must be
    explicit and must never close a pre-existing account.
24. Token-2022 extensions and transfer-hook account expansion must be resolved
    before compilation and simulation.
25. Exact message fee must be obtained from `getFeeForMessage` for the final
    blockhash-bound message, not estimated from a quote.
26. The same serialized message must flow from final simulation to any permit.

## P0 debt — submission and settlement

27. Jito registry evidence currently proves only local artifacts and a read-only
    `getTipAccounts` probe shape.
28. Jito remote schema freshness and execution conformance remain unproven.
29. The first-live policy should remain one strategy transaction with the tip in
    the same message; multi-transaction bundles require separate chaos evidence.
30. `bundleOnly=true` is a query parameter for Jito single-transaction send and
    must not be moved into an unrelated JSON config object.
31. A successful Jito JSON-RPC response is transport acknowledgement, not economic
    settlement.
32. Bundle status cannot replace finalized Solana transaction/account evidence.
33. Unknown, invalid, null or timed-out status must enter durable reconciliation,
    not automatic resend.
34. Duplicate submission must remain impossible for the same permit/message hash.
35. Blockhash expiry must create a reviewed new attempt with a new permit rather
    than silently mutating the already simulated message.
36. Finalized settlement code exists but is not wired to the supported runtime.
37. Repayment proof, token deltas, native fee/tip/rent deltas and cleanup outcomes
    must be compared against simulation and reservation evidence.
38. Profit must be booked only after finalized actual state proves it.
39. The legacy Jito executor still contains an unimplemented gRPC fallback and
    several exception-suppression paths; it must never be reactivated.
40. The legacy Jito bundle handler still contains placeholder templates and no
    real local SVM bundle simulation.

## P1 debt — data plane and reliability

41. Rooted RPC quorum logic exists but is not the active source for every critical
    state read.
42. Provider response bounds, redirect policy, decompression bounds and JSON depth
    must cover every active provider adapter.
43. Provider-native expiry, request/response hashes, slot and block height must
    survive normalization and opportunity identity.
44. Jupiter quota ownership must be account-wide and shared across discovery,
    retry and final build calls.
45. Retry budgets must include the total candidate deadline; retries may not
    outlive quote/blockhash freshness.
46. Webhook authentication, persistent deduplication and slot-gap backfill are not
    yet one active ingestion contract.
47. WebSocket reconnects need bounded backfill and rooted catch-up before data can
    re-enter strategy evaluation.
48. Queue overload must reject or displace deterministically and emit durable
    evidence; it must not silently drop high-value state transitions.
49. Risk-critical modules still contain silent `pass` exception handling in legacy
    or non-active ingestion code. Any promoted path must replace this with typed
    outcomes and metrics.
50. `rpc_multiplexing` still contains placeholder future processing and a
    placeholder quote mint in quarantined code.
51. `tx_builder` still contains placeholder setup pubkeys in quarantined code.
52. `transaction_simulator` retains compatibility placeholders for removed shadow
    shapes and must not become the active canonical implementation accidentally.
53. Replay tests must include provider 429/5xx, malformed JSON, stale slots,
    blockhash expiry, partial RPC disagreement and process restart.
54. Chaos tests must prove that reservations, journal states and dedup identities
    survive cancellation between every stage.

## P1 debt — release and operations

55. Current readiness/release modules mostly validate offline evidence packages;
    real immutable artifacts must feed them.
56. Real shadow soak evidence is not present merely because soak validators exist.
57. A minimum multi-day sender-free soak must cover route, planner, simulation,
    reconciliation, provider drift and queue/backpressure streams.
58. The production seccomp profile is documented as a stub and needs workload-based
    syscall capture and review.
59. Secret-manager references exist, but runtime key retrieval and rotation must be
    tested without repository/env leakage.
60. Signing keys must be isolated from discovery, strategy and post-processing
    processes.
61. Container non-root/read-only/tmpfs controls must be verified against the actual
    production image, not only configuration text.
62. SBOM, wheel hashes, image digest and action SHAs need actual generated and
    reviewed evidence.
63. Reproducible-build gaps need either bit-for-bit proof or an explicit reviewed
    variance document.
64. Dependency vulnerability results need a reviewed exception/expiry workflow,
    not permanent suppression.
65. Operational SLOs need alert thresholds for provider quota, rooted lag,
    reconciliation backlog, reservation leakage and ambiguous attempts.
66. Emergency stop and rollback rehearsal must be demonstrated against the real
    deployment topology.
67. Live canary must use tiny bounded capital, one transaction shape, explicit
    operator acknowledgement and automatic safety latches.
68. Data-lineage policy must exclude fixtures/synthetic rows from all profitability
    and release claims.
69. The package supports Python 3.13 only; the deployment image and native wheels
    must be continuously verified for that exact interpreter/platform combination.
70. Open parallel PRs must be synchronized with `main`; green isolated tests do not
    prove merge-commit compatibility.

## Four large delivery groups

### 1. `EXECUTION_VERTICAL` — P0

Aggregate Jupiter promotion, MarginFi attestation, account lifecycle, exact
fee/rent/capital sizing, v0 compilation, exact simulation and economic
reconciliation into one sender-free paper vertical.

**Acceptance:** a real rooted candidate reaches a deterministic reconciled paper
outcome with one immutable message hash and zero sender imports.

### 2. `SUBMISSION_SETTLEMENT` — P0

Aggregate permit issuance, Jito/RPC sender selection, same-message tip policy,
ambiguous status recovery and finalized actual settlement.

**Acceptance:** no duplicate submission, no paid standalone tip, no acknowledgement
counted as settlement, and no profit recorded without finalized account evidence.

### 3. `DATA_RELIABILITY` — P1

Aggregate bounded provider transport, quota/deadline scheduling, rooted RPC quorum,
webhook/WebSocket gap recovery, persistent dedup and durable backpressure.

**Acceptance:** every external input is bounded, fresh, identity-bound and replayable;
partial failures produce explicit durable outcomes.

### 4. `RELEASE_OPERATIONS` — P1

Aggregate signer isolation, hardened container, supply-chain evidence, real soak,
drift monitoring, operator acknowledgement, canary and rollback rehearsal.

**Acceptance:** production promotion is impossible without immutable evidence from
the actual built image and actual operational rehearsal.

## PR-149 implementation in this branch

This PR adds a deterministic offline audit that:

- reads the capability and external-contract registries;
- distinguishes honest/quarantined debt from active unsafe exposure;
- rejects stale Jupiter endpoints in active components;
- rejects active imports of quarantined execution modules;
- rejects `NotImplementedError` in active capability paths;
- validates Jupiter, Jito and MarginFi contract identity/probe shape;
- reports missing promotion evidence as production blockers;
- exposes deterministic JSON and SHA-256 output;
- exits successfully for integrity review while remaining not-production-ready;
- optionally returns a non-zero result when production readiness is required.

This is deliberately an inventory and regression boundary. It does not enable
trading, network access, signing or submission.
