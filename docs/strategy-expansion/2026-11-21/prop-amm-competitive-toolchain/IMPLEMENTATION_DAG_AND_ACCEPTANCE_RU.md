# Implementation DAG: Prop AMM competitive stack

## Owner crosswalk

| Component | Existing owner / reuse | This pack may add | Must not add |
|---|---|---|---|
| Feed source governance | PR #664 / existing source catalog + transport | Provider-specific evidence profile and adapter contract | New source registry or general capture runtime |
| Market observations | Existing MarketObservation and state-generation boundary | Prop AMM enrichment fields only after schema review | Parallel market model |
| CLMM/DLMM exact state | PR #660 | Prop AMM-specific state account closure only | Raydium/Meteora duplicate decoder |
| CPMM route | Merged PR #659 | Differential route fixtures only | Duplicate CPMM kernel |
| Quote comparison | Existing R13 normalization | Prop AMM route metadata/source adapter | New quote kernel or router graph |
| Simulation | pmm-sim external harness | Pinned build/test harness and corpus | Production dependency or trade authority |
| Funding | R02 FlashCapitalGraph / R03 builders | Venue-specific evidence only | Duplicate lender graph or unsigned builder |
| Sizing/resource locks | PR118 / ConflictScheduler | Additional exact resource declarations | New scheduler/reservation service |
| Paper/shadow | Installed canonical composition + MPR05 | Strategy evidence and replay report | New parallel runner |
| Submission | PR130 + MPR04 | Future adapter contract and qualification evidence | Sender activation or cross-relay fan-out |

## Ordered implementation phases

### Phase 0 — source and architecture lock
- Rebase this branch to current main before implementation.
- Verify status of #664 and #660 and their latest accepted file ownership.
- Create an owner map from actual source imports and composition root. Any mismatch stops the phase.
- Pin the current Solana toolchain and repository dependency set.
- No API calls to vendors, no subscriptions, no secrets.

### Phase 1 — read-only source A/B
- Start with existing approved provider profile.
- Add LocalShred Lite only as an optional feed profile after terms and endpoint access are approved.
- Compare against current Yellowstone/Geyser source using same region/hardware and synchronized timestamping.
- Record drops, completeness, reordering, slot drift, replay and time-to-usable-state.
- Add DoubleZero / OrbitFlare / Triton / Helius / GetBlock only after written plan terms and a bounded trial approval.
- Never subscribe to all feeds simultaneously just because a trial exists; use an explicit one-feed-at-a-time or bounded A/B budget.
- No API key or endpoint token in repo.

### Phase 2 — parser conformance
- Test sol-parser-sdk in isolated workspace or minimal adapter crate.
- Confirm Solana SDK/Yellostone/Agave compatibility, licenses and Rust edition.
- Compare protocol parser coverage to repo decoders. This package must not assume that parser supports Prop AMM variants not listed upstream.
- Benchmark against existing decoder. Adopt only if measurable end-to-end useful benefit exceeds CPU and dependency costs.

### Phase 3 — pmm-sim integration harness
- Pin pmm-sim commit and all floating dependencies to immutable SHAs.
- Import fixtures from exact account-state capture (labeled fixture or approved capture).
- Produce direct/single/multi/benchmark matrix for each supported Prop AMM version.
- Run pmm-sim local caller-profile differential tests (Jupiter/DFlow/OKX/Titan synthetic profiles) on the same pinned snapshot; research only, not production identity bypass. Never send synthetic caller identity on mainnet.
- Keep build/test environment isolated from production runtime until SDK conflicts and supply-chain checks pass.

### Phase 4 — direct instruction builder
- Audit and pin 1000xsh/swaps.
- Generate per-venue account-plan, instruction bytes and account-meta fixtures.
- Add direct path one venue/version at a time. No "Prop AMM" omnibus route flag.
- For HumidiFi's ignored min_amount_out, prove a same-transaction post-balance guard or block use.
- Compare direct construction against Jupiter /build for instruction ordering, account closure, ALT, CU, token-program and output floor.

### Phase 5 — current Jupiter V2 differential routing
- Pin /order and /build endpoint schema and rate terms.
- Compare Jupiter output and direct venue-builder output at identical amount/state generation.
- Preserve correlation when Jupiter aggregator sources and a direct DEX use the same underlying pool.
- Reuse R13 normalization, pool lineage and ConflictScheduler; don't add new global route graph.

### Phase 6 — relay contract only
- Retain PR130 JITO_SINGLE policy.
- Implement pure data model / offline conformance tests for a future provider-neutral sender contract only if current submission owner approves it.
- Helius Sender/Astralane/Syncro get separate capability and pricing profiles.
- No cross-provider fan-out, no provider-specific signature variants, no auto tip escalation. Provider-native internal multi-path routing may be evaluated as a single product endpoint.
- No sender endpoint or credentials in this pack.

### Phase 7 — sender-free shadow/paper
- Use installed canonical paper/shadow composition.
- Only exact-state, exact-size route and R02/R03/R05 evidence can be admitted.
- Capture-only and replay output remain distinct from real live-source evidence.
- Do not claim PAPER_QUALIFIED until R06/QPR exact requirements pass.
- MPR05 installed 72-hour soak remains a separate gate.

## Acceptance criteria

- [ ] Every upstream source has immutable URL, repo commit/release or official product doc and verified license/terms status.
- [ ] No mutable Git branch in dependency lock; every library pin includes commit/tag and Cargo.lock digest.
- [ ] All source/feed metrics use matched region/time windows and include loss, completeness, root/fork, replay and useful-state latency.
- [ ] Parser events are canonical, amount/base-unit precise and provenance-bound.
- [ ] pmm-sim route output is compared against actual state and independent quote/reference vectors.
- [ ] All venue instruction variants include program id/account layout/state hash and exact min-out / post-balance guard evidence.
- [ ] Jupiter V2 and direct instructions are compared on the same amount and state generation.
- [ ] Flashloan borrow, all swaps, output guard and repayment are one atomic transaction plan.
- [ ] Lender capacity/fee is R02-proven; builder semantics are R03-proven; exact simulation/economics is R05-proven.
- [ ] Route splitting is justified by capacity or price impact and uses existing shared-resource reservations.
- [ ] Relay ACK, block-engine ACK or bundle id is never reported as finalized settlement.
- [ ] Caller profile benchmark matrix covers direct, Magnus and local simulated Jupiter/DFlow/OKX/Titan per AMM/version/amount/snapshot.
- [ ] Real aggregator route is built through its official API/program; simulated caller identity is never sent.
- [ ] Provider tip matrix distinguishes fixed on-chain recipient, native multipath, off-chain billing and rebate eligibility.
- [ ] No cross-provider fan-out unless billing, duplicate behavior, exact-byte forwarding and idempotency are independently proven.
- [ ] Offline tests, replay, typed rejects, compute and packet benchmarks pass.
- [ ] send_enabled=false, sign_enabled=false, live_enabled=false, borrow_enabled=false; provider activation flags false.
- [ ] No secrets, wallet creation, ATA creation, account mutation, fee transfer or subscription.
