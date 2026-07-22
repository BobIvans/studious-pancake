# Aggregated production-readiness implementation roadmap — 2026-07-22

## Purpose

This document turns the merged production-debt audits and the current parallel PR
queue into four large integration tracks. It deliberately uses stable track IDs
`AGG-1` through `AGG-4` because the repository currently has conflicting PR labels,
including two different open pull requests titled `PR-152`.

The authoritative detailed debt inventories remain:

- `docs/audits/PRODUCTION_DEBT_EXTERNAL_COMPATIBILITY_2026-07-22.md`;
- `docs/production_debt_aggregation.md`;
- `src/resources/production_debt_pr149.json`;
- `src/resources/production_debt.json`.

This roadmap does not enable paper execution, signing, submission or live trading.
The checked-in capability state must remain `not-production-ready` and live mode
must remain unavailable until all four tracks have accepted evidence.

## Why the next work must be aggregated

The repository already contains many strong isolated contracts and offline gates.
The remaining problem is integration: policy, provider admission, state snapshots,
planner, compiler, exact simulation, transaction proof, durable lifecycle,
observability, settlement and release evidence are not yet one supported vertical.

A new review-only gate is not sufficient when an equivalent gate already exists.
Each track below must wire existing contracts into the supported entrypoint and
produce real immutable evidence.

## Dependency graph

```text
AGG-1  Baseline, packaging and canonical runtime cutover
  |
  v
AGG-2  External contracts, rooted state and exact sender-free vertical
  |
  v
AGG-3  Durable paper runtime and real multi-day operational evidence
  |
  v
AGG-4  Permit-bound submission, finalized settlement and hardened release
```

## Parallel PR coordination snapshot

This snapshot is informational and must be refreshed before implementation:

| PR | Current role | Recommended treatment |
|---|---|---|
| #149 | bounded provider response parsing | Rebase and consume in AGG-2 across every active adapter. |
| #148 | evidence-bundle sealing | Use in AGG-3/4 as a consumer of real artifacts, not as a substitute for soak. |
| #155 | structured durable runtime | Combine with the exact-attempt vertical after AGG-1 stabilizes. |
| #157 and #164 | overlapping baseline/security truth | Compare scopes and select one canonical implementation or make the second an explicit follow-up. |
| #160 | Helius management-plane hardening | Keep; add delivery-plane auth, durable intake, dedup and gap recovery in AGG-2. |
| #161 and #163 | market/proof gate variants | Do not preserve parallel proof domains; integrate with merged kernels and AGG-2. |
| #165 | exact sender-free paper attempt | Treat as the likely nucleus of AGG-2, then wire it into AGG-3. |
| merged #158 | isolated release policy boundary | It is not a signer/sender implementation; AGG-4 may start only after AGG-3 evidence. |

## Coordination rules

1. One track owns one canonical integration branch and one reviewed file-owner map.
2. A gate-only PR may be an input, but it does not complete a track without active
   runtime wiring and real evidence.
3. Every branch must be synchronized with `main`; merge-commit CI is required in
   addition to isolated branch CI.
4. Do not introduce a sender, private key or live switch before AGG-3 is accepted.
5. Documentation review, local fixtures and schema models never grant an external
   provider an executable role by themselves.

# AGG-1 — Baseline, packaging and canonical runtime cutover

**Priority:** P0

**Goal:** one installed runtime and one durable attempt state machine, with no
parallel active execution domains.

## Owned surfaces

- `pyproject.toml` and installed-wheel package manifest;
- `src/cli.py` and `src/container_runtime.py`;
- `src/paper_shadow/`;
- `src/durability/`;
- strategy runtime, queue and tracker;
- lifecycle, journal, observability projection and outbox ownership.

## Required implementation

- Make source checkout and installed wheel expose the same supported capability
  graph. Decide explicitly which ingest/sender packages are product code and which
  are physically quarantined or removed.
- Create one composition root for discovery -> candidate -> capital reservation ->
  planning -> compilation -> exact simulation -> reconciliation -> durable outcome.
- Supply real `AtomicVerticalRuntimeInputs` instead of missing/default paper
  dependencies.
- Bind the exact final-message fee and durable native-capital reservation to every
  attempt, including every terminal failure and cancellation path.
- Make non-monotonic sizing own the runtime amount search rather than remain an
  isolated library.
- Unify lifecycle, journal, observability and outbox around one authoritative
  attempt state machine with a single-writer rule.
- Add a structured supervisor with bounded tasks, queues, file descriptors,
  provider calls, evidence sizes and per-stage deadlines.
- Remove or prove unreachable every compatibility placeholder in the canonical
  compiler/simulator facade.
- Prevent `Keypair`, sender and quarantined transaction-builder/router/Jito imports
  from entering discovery, strategy or paper runtime.
- Replace silent exception swallowing in any promoted path with typed outcomes,
  durable reasons and metrics.
- Continuously test Python 3.13, native wheels and the actual runtime image.

## Acceptance

- Source and wheel capability graphs are identical.
- One sender-free command executes repeated exact attempts through one supervisor.
- Every attempt has durable reservation, lifecycle, journal, observability and a
  terminal result.
- Restart, cancellation, queue saturation and a second writer leave no leaked
  reservation, tracker or outbox state.
- No sender/private-key surface is reachable from the supported paper runtime.

## Mandatory tests

- source/wheel import parity and `python -O` import smoke;
- restart at every stage and SIGTERM drain;
- queue overload and tracker cleanup;
- SQLite lock and second-writer fencing;
- static import/capability graph regression.

# AGG-2 — External contracts, rooted state and exact sender-free vertical

**Priority:** P0

**Depends on:** AGG-1

**Goal:** a real rooted candidate reaches deterministic exact simulation and
conservative reconciliation without a sender.

## Owned surfaces

- routing transport and provider adapters;
- external-contract registry and conformance artifacts;
- MarginFi/Kamino lending state and instructions;
- account lifecycle, exact economics and capital reservations;
- v0 compiler, ALT/blockhash finalization, exact simulator, CPI graph and
  reconciliation.

## Required implementation

### Jupiter Swap V2

- Prove remote schema freshness, credentialed `x-api-key` conformance and execution
  composition for `GET /swap/v2/build` with required `taker`.
- Preserve official instruction ordering: compute budget, setup, custom pre-swap,
  swap, custom post-swap and cleanup.
- Validate every program/account privilege and reject unknown instruction families.
- Treat `addressesByLookupTableAddress` as untrusted until ALT owner, deactivation,
  indexes and resolved keys are rooted and verified.
- Check `blockhashWithMetadata` against local slot/block-height freshness.
- Remove obsolete active assumptions for Metis `/swap/v1` and old V2 quote/swap
  endpoints.

### MarginFi and Kamino

- Pin exact official source revisions and reproduce deployed binary identity.
- Require IDL/account/instruction golden vectors before execution promotion.
- Capture bank/reserve, vault, oracle, mint and token-program identities in one
  coherent rooted snapshot.
- Derive health and flash-loan eligibility from decoded state with no neutral
  fallback.
- Count flash fee and repayment exactly once in an integer ledger.
- Populate Kamino supported combinations only from reviewed official/on-chain
  market-reserve evidence; never guess combinations.

### Account lifecycle and exact transaction proof

- Reserve ATA rent and own-SOL costs before borrow.
- Verify existing ATA PDA, owner, mint and token program.
- Model wSOL funding, `SyncNative`, close authority and cleanup destination without
  closing a pre-existing account.
- Resolve Token-2022 extensions and transfer-hook accounts before compilation.
- Obtain `getFeeForMessage` for the final blockhash-bound message.
- Preserve the exact same serialized message from final simulation to any future
  authorization permit.
- Compare planned instructions, top-level instructions and the CPI call graph.

### Data reliability

- Use rooted independent RPC quorum for every critical state read.
- Apply byte, content-type, redirect, decompression, JSON depth and node limits to
  every active provider response.
- Preserve provider expiry, request/response hashes, slot and block height through
  normalization and opportunity identity.
- Make Jupiter quota account-wide across discovery, retries and final build; total
  retry budgets may not outlive candidate freshness.
- Complete Helius delivery authentication, durable intake-before-200, persistent
  deduplication, retry idempotency and slot-gap backfill.
- Require WebSocket backfill and rooted catch-up after reconnect.
- Keep OKX, OpenOcean and Odos discovery-only until composability and execution
  conformance are proven.

## Acceptance

- One rooted candidate uses credentialed/admitted Jupiter and deployed-attested
  lending evidence.
- Every external input is bounded, fresh, identity-bound and replayable.
- One immutable v0 message passes semantic firewall, exact simulation, CPI proof
  and conservative economic reconciliation.
- The durable paper result records provider, state, plan, message, simulation and
  reconciliation identities.
- No documentation snapshot alone grants execution permission.

## Mandatory tests

- credentialed protected probes and schema drift;
- provider 429/5xx, malformed JSON, redirect and oversized response;
- rooted RPC disagreement, stale slot and blockhash expiry;
- ALT/account privilege mutation;
- Token-2022 transfer hooks and ATA/wSOL failures;
- exact fee/rent/capital insufficiency;
- process cancellation between every exact stage.

# AGG-3 — Durable paper runtime and real operational evidence

**Priority:** P0

**Depends on:** AGG-1 and AGG-2

**Goal:** real multi-day sender-free evidence, not another offline readiness model.

## Required implementation

- Connect the exact sender-free attempt to the structured repeated runtime.
- Run a minimum 72-hour sender-free soak covering candidate identity, provider
  evidence, rooted state, reservation, planning, transaction proof, simulation,
  CPI graph, reconciliation, observability and data lineage.
- Exclude fixtures and synthetic rows from profitability, readiness and release
  claims.
- Compare planned, simulated and reconciled integer economics for every terminal
  attempt.
- Define and monitor SLOs for provider quota, rooted lag, queue depth, event-loop
  lag, reconciliation backlog, reservation leakage and ambiguous attempts.
- Prove webhook/WebSocket dedup and gap recovery under duplicate storms, disconnects
  and backpressure.
- Prove restart/cancellation recovery at every stage.
- Seal immutable, redacted evidence against exact git, build, config and policy
  hashes; require two independent human reviews.
- Schedule provider-contract and remote-webhook configuration drift checks.

## Acceptance

- At least 72 hours with no skipped critical evidence stream.
- All terminal attempts are reconciled; gaps, duplicates and leaks are absent or
  inside a reviewed error budget.
- No transaction signature, signer, sender or private key appears in soak evidence.
- Performance/profitability reports use only allowed lineage and exact integer
  economics.
- The evidence bundle is reproducible from immutable artifacts.

## Mandatory tests and drills

- provider outage and quota exhaustion;
- webhook duplicate storm and WebSocket disconnect/backfill;
- queue saturation, event-loop lag and DB lock;
- process restart and cancellation matrix;
- clock jump and stale evidence;
- evidence redaction, lineage and manifest sealing.

# AGG-4 — Permit-bound submission, finalized settlement and hardened release

**Priority:** P0/P1

**Depends on:** accepted AGG-3 evidence

**Goal:** one tiny reviewed canary with no duplicate send and no realized profit
before finalized actual state.

## Required implementation

- Prove Jito remote schema freshness and execution conformance.
- For the first canary, use one strategy transaction with the tip in the same
  message. Treat `bundleOnly=true` as the documented query parameter.
- Treat every RPC/Jito response and bundle ID as transport acknowledgement only.
- Route null, unknown and timeout states into durable reconciliation without
  automatic resend.
- Make duplicate submission impossible for the same permit/message hash, including
  after restart.
- After blockhash expiry, create a new reviewed attempt and permit rather than
  mutating the simulated message.
- Wire finalized Solana `getTransaction` and account evidence into the supported
  lifecycle; reconcile repayment, token deltas, actual fee, tip, rent and cleanup.
- Book realized profit only from finalized actual state.
- Implement an isolated signer process that independently parses exact v0 bytes,
  verifies payer/signers/programs/policy/proof hashes, enforces durable anti-replay
  and returns only a signature.
- Test secret retrieval and rotation without environment/repository leakage.
- Produce workload-derived seccomp/AppArmor, non-root/read-only/tmpfs/egress
  evidence for the actual image.
- Generate SBOM, wheel hashes, image digest, pinned action SHAs and signed
  provenance; manage vulnerability exceptions with owner and expiry.
- Rehearse emergency stop, ambiguous settlement and rollback in the real topology.
- Require tiny capital, two-human approval and automatic safety latches for canary.

## Acceptance

- Network runtime never receives private key material.
- Duplicate send remains impossible through timeout, restart and unknown status.
- Receipt/status is never treated as settlement; only finalized actual evidence
  closes an attempt and books PnL.
- The actual image has reviewed sandbox and supply-chain evidence.
- Canary requires two independent approvals, bounded capital, kill switch and a
  tested rollback path.

## Mandatory tests and drills

- signer isolation and authorization replay;
- exact Jito request shape and same-message tip;
- ambiguous status restart and blockhash expiry;
- finalized account-delta reconciliation;
- secret rotation and incident response;
- container sandbox and egress enforcement;
- emergency stop and rollback rehearsal.

## External compatibility facts that must remain pinned

### Solana

- Read v0 transactions with explicit `maxSupportedTransactionVersion=0`.
- Bind ALT provenance, blockhash validity and exact `getFeeForMessage` result to the
  final message.
- `sendTransaction` acknowledgement is not confirmation or settlement.

### Jupiter

- Swap V2 `/build` is an authenticated GET with required `taker` and returns raw
  instruction groups, ALT mapping and blockhash metadata.
- Those fields remain external evidence requiring local semantic and freshness
  validation.

### Helius

- Webhook `authHeader` is delivered as the `Authorization` header.
- Deliveries may be duplicated; exhausted retries can lose events. Durable intake,
  idempotency, gap recovery and remote configuration monitoring are repository
  responsibilities.

### Jito

- Bundles are ordered, same-slot and all-or-nothing, but a returned bundle ID is
  only a receipt.
- The documented minimum bundle tip is 1000 lamports and the default documented
  rate limit is one request per second per IP per region.

### MarginFi and Kamino

- Program/source identities are review inputs, not deployed-bytecode or
  instruction-layout proof.
- Kamino mainnet KLend program ID is
  `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD`; supported combinations must be
  evidence-backed.

## Definition of done

Production promotion remains impossible until all of the following are true:

- all four tracks are complete in dependency order;
- the supported entrypoint and installed wheel expose one canonical capability
  graph;
- every external execution role has current credentialed, deployment, execution
  and promotion evidence;
- real sender-free soak is accepted before sender wiring;
- finalized actual state is the only source of realized PnL;
- actual build/image evidence and two independent human approvals authorize a
  tiny canary.

## Codex-ready template for each integration PR

```text
Mission: complete AGG-N as one integration PR.
Use the merged production debt inventories and this roadmap as authoritative scope.
Do not create another standalone review-only gate when an equivalent contract exists.
Wire existing contracts into the supported entrypoint and produce real immutable evidence.
Keep live, signing and submission disabled unless implementing AGG-4 with accepted AGG-3 evidence.
Implement every owned requirement or leave an explicit machine-readable blocker.
Add integration, restart, fault-injection, wheel/source and merge-commit tests.
Before review: rebase on current main, require behind_by=0, run scripts/verify_repo.py,
wheel/image smoke and merge-commit CI.
```

## Official references

- Solana `getTransaction`: https://solana.com/docs/rpc/http/gettransaction
- Solana `simulateTransaction`: https://solana.com/docs/rpc/http/simulatetransaction
- Solana `getFeeForMessage`: https://solana.com/docs/rpc/http/getfeeformessage
- Jupiter Swap V2 `/build`: https://developers.jup.ag/docs/api-reference/swap/build
- Jupiter instruction ordering: https://developers.jup.ag/docs/swap/build/common-instructions
- Helius webhook FAQ: https://www.helius.dev/docs/faqs/webhooks
- Helius create webhook: https://www.helius.dev/docs/api-reference/webhooks/create-webhook
- Jito low-latency transaction send: https://docs.jito.wtf/lowlatencytxnsend/
- MarginFi v2: https://docs.marginfi.com/mfi-v2
- Kamino KLend: https://github.com/Kamino-Finance/klend
- Kamino KLend SDK: https://github.com/Kamino-Finance/klend-sdk
