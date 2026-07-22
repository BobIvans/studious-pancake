# Flashloan Bot production convergence audit — 2026-07-22

## Executive conclusion

The repository has accumulated many strong deterministic safety contracts, but it is still **not production ready**. The main remaining problem is no longer the absence of individual validators. The main problem is that many validators, evidence models and PR-specific gates are not composed into one supported, durable end-to-end runtime.

The safest path is to stop creating dozens of isolated contracts and converge the remaining work into four large vertical pull requests. Each vertical must deliver an executable or operational outcome, not only another standalone gate.

Live trading remains disabled. This audit does not authorize a signer, sender, Jito submission, RPC submission or real capital use.

## Evidence from the repository

- `config/capabilities.json` declares `product_state=not-production-ready` and hard-denies live mode.
- The supported entry point reaches bounded discovery and paper/shadow recording, but not a complete planner → compiler → exact simulation → durable lifecycle → finalized reconciliation path.
- MarginFi, Kamino liquidation and orderbook execution remain fixture-only or quarantined.
- Numerous PR-specific modules implement useful invariants but are not imported by the supported composition root.
- The repository contains both canonical provider adapters and legacy/quarantined implementations with stale API assumptions. Quarantine is appropriate, but it must be machine-enforced and eventually removed.
- Existing evidence/readiness gates do not replace real credentialed conformance, real paper execution, long soak evidence or finalized post-trade reconciliation.

## External compatibility findings

### Helius webhook management — concrete drift fixed in this PR

Before this PR, management scripts used the old `https://api.helius.xyz/v0` host, expected `webhookId`, placed the API key directly in the URL string, omitted request timeouts and recommended an insecure plain-HTTP public-IP webhook URL.

The current management contract used by this PR requires:

- `https://api-mainnet.helius-rpc.com/v0/webhooks`;
- canonical response field `webhookID`;
- a publicly reachable HTTPS delivery URL;
- an `authHeader` for production authenticity;
- explicit timeouts, bounded JSON parsing and sanitized failures.

The remaining Helius work is delivery-plane integration: authentication verification, deduplication, durable acknowledgement, replay-window handling, retry tolerance and supported-runtime composition.

### Jupiter Swap V2

The canonical adapter correctly pins authenticated `GET /swap/v2/build` and treats returned instruction buckets as untrusted execution evidence. Legacy `/swap/v1` paths and invented `/swap/v2/quote` paths must remain quarantined and must never be promoted into the supported execution path.

Remaining work includes credentialed conformance fixtures, response expiry, route identity, lossless account-meta/ALT parsing, exact second-leg finalization, protected account-wide quota capacity and scheduled schema drift checks.

### Jito Block Engine

The legacy client remains quarantined and still contains incompatible or unsafe semantics:

- a non-canonical `GET .../bundles/tip_accounts` path instead of a JSON-RPC `getTipAccounts` contract;
- status lookup tied to a legacy endpoint shape;
- multi-region shotgun submission of the same signed transaction;
- paper mode returning a fake successful bundle ID;
- an empty `start()` lifecycle method;
- bundle acceptance not yet durably separated from landing and economic settlement.

Do not repair this by activating the legacy module. Replace it with one canonical permit-bound sender adapter only after the paper vertical is complete.

### Solana RPC

Production execution still requires one coherent evidence policy across `getLatestBlockhash`, `isBlockhashValid`, `simulateTransaction`, `getFeeForMessage` and finalized `getTransaction`, including `minContextSlot`, supported transaction version, rooted independent RPC quorum and explicit stale/fork disagreement handling.

### MarginFi

MarginFi must stay fixture-only until the repository proves exact deployed program/group identity, IDL/source provenance, deployed binary attestation, complete account decoding, coherent slot-bound bank/oracle/user state, exact flash-loan instruction bytes/account metas and repayment from finalized actual evidence.

### Kamino

Kamino must stay read-only/fixture-only until the mainnet program, IDL/codegen, reserve/obligation decoders, oracle state and liquidation rules pass credentialed read-only conformance. Execution support must not be inferred from local fixtures.

### Token-2022 and LST assets

Exact economics must include mint owner/extensions, transfer fees, withheld fees, transfer hooks, asset restrictions, LST governance policy and actual post-transaction token balances. A nominal quote is not executable profit evidence.

## Structural production debt — detailed findings

### Composition root

1. Many PR-specific safety modules are additive but not connected to `src/cli.py` or the supported paper composition.
2. The supported runtime does not execute one canonical candidate through every paper stage.
3. Capability declarations and active imports can drift unless validated together.
4. Legacy modules remain numerous and require stronger import/packaging quarantine.
5. Strategy-specific paths can bypass shared lifecycle/economic contracts unless the composition root owns all stages.
6. Runtime builders need dependency injection for providers, clock, RPC, persistence and metrics.
7. Environment flags must never activate a quarantined sender.
8. Healthy-idle must be distinguishable from a fully exercised paper cycle.

### Market and route evidence

9. Discovery evidence must preserve requested/received time, slot, block height, provider identity and raw response hash.
10. First-leg discovery and exact second-leg finalization need separate quota budgets.
11. Cross-provider prices need normalized decimals, token programs and transfer-fee semantics.
12. Route plans require deterministic identity and program allowlisting.
13. Every account meta, lookup table and instruction bucket must be preserved losslessly.
14. Provider expiry must be native where available and bounded locally otherwise.
15. Slippage, price impact and exact-out semantics must be candidate-specific.
16. Meta-aggregator liquidity must not be counted as independent executable evidence.
17. Assembled transactions and composable raw instructions are different artifact classes.
18. Final build must remain in the same slot/blockhash/economic context as simulation.

### Protocol state

19. MarginFi complete state is not authoritative in the supported runtime.
20. Kamino remains fixture-only.
21. Oracle confidence, staleness and fallback policy need final composition.
22. Program and IDL drift checks are not scheduled release blockers.
23. Account-version migrations require explicit rejection or decoder promotion.
24. Flash-loan repayment must be proven from actual CPI/account evidence.
25. Borrow, fee and repayment amounts must remain integer exact.
26. Protocol account ordering and signer/writable flags require golden-byte tests.
27. LST/Token-2022 policy must be applied before sizing and before final compilation.
28. Protocol state from different slots must never be silently combined.

### Exact economics and capital

29. Capital reservations must be durable across processes and restarts.
30. Available SOL must reserve network fee, priority fee, Jito tip, rent and ATA/wSOL lifecycle.
31. Transfer fees and flash fees must be counted exactly once.
32. Profit thresholds must be net of all predicted and actual costs.
33. Non-monotonic sizing needs bounded deterministic search.
34. Concurrent candidates need authoritative exposure and position limits.
35. Unknown cost components must block execution rather than default to zero.
36. Predicted, simulated and actual economics must be stored separately.
37. Reconciliation must attribute every delta or enter manual review.
38. Daily loss, drawdown and cooldown policy must be durable and restart-safe.

### Compilation and simulation

39. One canonical compiler must own instruction ordering.
40. Compute-budget ownership must be singular and final-message specific.
41. ALT ownership, authority, deactivation and completeness need final-time checks.
42. Message size must use actual serialized v0 transaction bytes.
43. Blockhash/context freshness must be revalidated after expensive work.
44. Exact simulation must be repeated after compute-budget finalization.
45. CPI call graph and MarginFi repayment must be parsed, not inferred.
46. Simulation logs/return data need bounded parsing and redaction.
47. Simulation success does not imply submission or economic success.
48. Compiler/simulation ambiguity must latch to rejection or manual review.

### Submission and settlement

49. No supported live sender exists, which is currently the correct fail-closed state.
50. Submission intent must be durable before network I/O.
51. Ambiguous transport outcomes must never trigger blind resend.
52. Bundle acceptance, landing, confirmation and finalized economics are separate states.
53. A submitted signature needs durable polling/reconciliation ownership.
54. Finalized `meta.err`, balances, token balances, loaded addresses, logs, return data and compute units must be parsed.
55. Missing/conflicting evidence must become manual review, not success.
56. Settlement workers need bounded leases and takeover semantics.
57. Proven blockhash expiry is required before rebuild eligibility.
58. Rebuild needs a new attempt identity while preserving logical opportunity identity.

### Webhook and streaming

59. Helius management drift is fixed here, but delivery authentication still needs active composition.
60. Webhook retries and duplicate deliveries require durable idempotency keys.
61. Delivery bodies need byte/depth/node limits before parsing.
62. Acknowledgement should occur only after durable intake or explicit rejection.
63. WebSocket disconnect, gap detection and backfill need one state machine.
64. Stream events require slot/root ordering and stale-event policy.
65. Tunnel URLs are development-only and cannot be production evidence.
66. Remote webhook config must be compared against canonical expected fields.

### Persistence and recovery

67. Lifecycle, evidence, reservations and outbox records need one transactional boundary.
68. Optimistic concurrency/version checks must prevent dual owners.
69. Crash points need deterministic recovery tests at every external side effect.
70. Verification must never leave generated files in the source tree.
71. Schema migrations need rollback/forward compatibility and backup evidence.
72. Provider payload/log retention and redaction policies are required.
73. Manual-review records must remain queryable until resolved.
74. Replay must use immutable evidence, not mutable provider calls.

### Security and supply chain

75. Raw private keys must not be read by the general application process.
76. Signer authorization needs wallet, message hash, policy hash, expiry and revocation.
77. Secrets must never enter URLs, logs, exceptions or evidence bundles.
78. Provider errors need central sanitization.
79. Dependencies, Docker base, actions and generated artifacts need pinned provenance.
80. SBOM, signatures and vulnerability exceptions require release evidence.
81. Egress allowlists should prevent unexpected RPC/provider destinations.
82. Parser fuzzing is needed for JSON, instruction data and account bytes.
83. Broad exception handlers in active boundaries should be narrowed and classified.
84. Credential rotation and signer revocation runbooks must be tested.

### Observability and operations

85. Every candidate/attempt needs one trace ID across all stages.
86. Metrics need bounded cardinality and stable rejection codes.
87. Provider freshness, quota and circuit state need dashboards.
88. RPC quorum disagreement and rooted lag need alerts.
89. Reservation leakage, stuck reconciliation and manual-review backlog need alerts.
90. Health endpoints must represent dependency and active-mode truth.
91. Operator actions need immutable audit evidence.
92. Runbooks must cover provider outage, RPC fork, secret leak, stuck state and bad deployment.
93. Deployment needs non-root, read-only filesystem, resource limits and controlled egress.
94. Rollback and data export must be exercised before canary.

### Testing and evidence

95. Focused unit tests are extensive, but supported-runtime end-to-end tests remain the key gap.
96. Credentialed read-only conformance must run separately from deterministic CI.
97. Golden fixtures require provenance, hashes and refresh policy.
98. A 72-hour real paper/shadow soak must use one pinned build.
99. Chaos tests must cover 429/5xx, malformed bodies, clock jumps, RPC disagreement, disconnects and crashes.
100. Evidence bundles must reference immutable artifacts from the exact build.
101. Canary gates need hard notional, loss, wallet, provider and transaction-count caps.
102. Finalized reconciliation and rollback must be demonstrated before scaling.

## Consolidated roadmap: four large PRs

The machine-readable source of truth is `config/production_debt_pr149.json`. It contains 36 acceptance-driven items grouped into four vertical epics.

### Mega PR A — Supported paper execution vertical

Deliver one complete sender-free path:

`discovery → exact candidate economics → canonical compilation → exact simulation/CPI evidence → durable lifecycle → finalized paper reconciliation → metrics`

Standalone gates should be absorbed only when they become active in the supported composition root.

### Mega PR B — Protocol and provider conformance

Deliver current external contracts and authoritative state adapters for Helius, Jupiter, Jito, Solana RPC, MarginFi, Kamino, Token-2022/LST assets, programs and ALTs. PR-149 starts this vertical by fixing Helius management and adding the compatibility gate.

### Mega PR C — Durability, security and operations

Deliver transactional lifecycle/reservations/outbox, isolated signer authorization, redacted observability, SLOs, hermetic deployment, supply-chain evidence, incident runbooks and deterministic chaos recovery.

### Mega PR D — Soak evidence and limited canary

Deliver scheduled drift checks, replay baselines, one immutable evidence bundle, 72-hour soak, hard canary caps, operator acknowledgement, finalized reconciliation and tested rollback. The code must still default to live disabled; activation is a separate reviewed operational action.

## PR-149 acceptance

- current Helius host and canonical `webhookID`;
- API keys are not interpolated into URL strings;
- explicit timeouts and bounded JSON parsing;
- allowlisted create/update fields;
- public HTTPS delivery URL required;
- production `authHeader` required and redacted from written artifacts;
- offline compatibility gate detects stale Helius/Jupiter pins and reports quarantined Jito debt;
- 36 unique acceptance-driven debt items in four large epics;
- live trading remains disabled;
- focused tests pass without network access.

## Explicit non-goals

- no live sender;
- no signing;
- no transaction or bundle submission;
- no MarginFi or Kamino promotion;
- no activation of the legacy Jito client;
- no claim of production readiness;
- no claim that standalone contracts constitute end-to-end evidence.
