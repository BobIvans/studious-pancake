# AGG-13 — non-atomic inventory and additional market classes

Implementation checkpoint for AGG-13 from the supplied mega-PR specification.

## Effect boundary

This change is **sender-free and default-off**. It does not load exchange trading
credentials, create accounts, sign, submit, bridge, withdraw, enable live trading,
or reinterpret delayed inventory settlement as an atomic flash-loan outcome.
Existing treasury, capital, provider-quota, signer and submission owners remain
authoritative.

## Implemented scope

### DATA-05 — NF-077, NF-078, NF-079, NF-080, NF-082

\`src.data_plane.external_datasets\` adds bounded contracts for CEX, derivatives,
indexed-chain, Sui/checkpoint and slow-factor observations:

- explicit LIVE / ARCHIVE / REFERENCE / SLOW_FACTOR provenance;
- event time, available-at time and revision identity;
- exact integer/scalar fields; binary-float money is rejected;
- source entitlement expiry, storage/redistribution rights and terms hash;
- quota leases delegated to the existing provider-plane authority;
- market-data access never grants trading authorization.

Provider-specific network collectors are not claimed in this checkpoint because
the current main generation does not contain accepted AGG-02/source entitlements.

### INV-01 — NF-288, NF-289

\`src.inventory.non_atomic\` adds a durable SQLite order/fill/position evidence
owner for inventory workflows. It is not a second treasury ledger: it stores
exchange order state and exposure only.

- idempotent order intent and fill receipts;
- exact signed quantities, cash deltas and fees;
- partial-fill, cancel-pending, unknown and terminal states;
- crash/restart persistence;
- cancel/fill race handling without discarding late fills;
- exchange reconciliation refuses to invent missing fill economics;
- recovery plans expose open position, remaining order and unknown status.

### INV-02..INV-05 — NF-290..NF-305

\`src.inventory.research\` provides fail-closed feasibility gates for funding/basis,
calendar, cross-venue, cross-chain, market-making, LP hedging, options parity,
volatility, complete sets, statistical baskets, RWA/tokenized instruments,
equity baskets, commodities, pre-IPO and fiat/P2P research.

The gate requires the relevant execution/settlement/session/redemption/compliance,
prefund, hedge, funding/margin and statistical evidence. Commodity, pre-IPO and
fiat/P2P remain RESEARCH_ONLY. Every AGG-13 hypothesis has
\`atomic_execution_allowed=false\`.

### NF-306 — portfolio allocator

A deterministic conservative allocator respects free capital minus the reserved
gas budget, venue capacity, per-candidate worst-loss budget and the portfolio tail
budget. Model output may shrink a reviewed exposure but cannot increase it.

### NF-307 — inventory qualification

The qualification contract requires restart/replay, partial-fill modelling,
actual reconciliation, disconnect recovery, funding-flip stress, margin shock and
instrument-access evidence. A positive qualification remains scope-bound and
\`live_authorized=false\`.

## Current dependency truth

AGG-13 declares AGG-02 and AGG-04 as package prerequisites. At final pre-PR\nsynchronization this branch is based on \`main@141dfa85a0efd42bcd3b90a632ed54a39a3a4511\`;\nAGG-02 is still open as PR #496 and AGG-04 as PR #497, so this checkpoint does\n**not** claim full AGG-13 completion.

Open blockers:

- \`AGG13_PREREQUISITE_AGG02_NOT_ACCEPTED\`
- \`AGG13_PREREQUISITE_AGG04_NOT_ACCEPTED\`
- \`AGG13_PROVIDER_SPECIFIC_COLLECTORS_UNQUALIFIED\`
- \`AGG13_EXCHANGE_TRADING_CONNECTORS_UNQUALIFIED\`
- \`AGG13_ACTUAL_FILL_RECONCILIATION_EVIDENCE_MISSING\`
- \`AGG13_MARKET_FAMILY_PRICING_MODELS_NOT_QUALIFIED\`
- \`AGG13_INVENTORY_CAMPAIGN_NOT_RUN\`

For the contracts/foundation in this PR:
\`implementation_status=IMPLEMENTED_OFFLINE\`,
\`operational_status=UNQUALIFIED\`.
The aggregate package remains \`IN_PROGRESS\` until prerequisite generations and
real external evidence are available.

## Focused acceptance cases

The focused tests cover:

- live/archive separation and trial expiry;
- public feed != order authorization;
- duplicate fill idempotency after restart;
- fill-ID conflict rejection;
- partial fill -> explicit open exposure and recovery plan;
- cancel race and missing-fill reconciliation -> UNKNOWN, not fabricated fill;
- cross-chain inventory cannot claim atomic execution;
- closed RWA session blocks feasibility;
- fiat/P2P remains research-only;
- gas reserve and tail-loss budget are preserved by allocation;
- inventory qualification cannot grant live authority.

## Rollback

Revert the AGG-13 commits. The modules are not wired into the installed atomic
runtime, do not migrate existing treasury/capital stores, and create no remote
resources. Any local AGG-13 inventory SQLite file is an inventory evidence
artifact, not an authority for existing atomic attempts.
