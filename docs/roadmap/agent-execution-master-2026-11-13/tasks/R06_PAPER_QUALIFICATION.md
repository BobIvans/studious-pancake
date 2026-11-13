# Assignment — R-06 evidence-backed paper qualification

Copy/paste trigger: Do not start a 24-hour campaign just because an agent can run a loop. First inspect current QPR-01/02/03, DIN source profiles, campaign authority, source governance, current capability manifest, R-02 capital evidence, R-03 builders, R-04 candidates and R-05 exact simulation. If the existing campaign readiness owner does not return the exact required PASS, stop with BLOCKED and report the missing owner/evidence. Never bypass the campaign stop condition or invent a new authority.

## Entry gates
- Current main/config/source generation and release authority are consistent and recorded.
- Required live data providers have current approved profile, quotas, authentication and independent operator/correlation-group provenance.
- Asset identities and every route market are verified; quote/state snapshots are current and replayable.
- The selected lender resource has current R-02 capacity proof and the route has R-03 builder conformance.
- Exact full transaction/PTB simulation and economic reconciliation pass for the sampled amount; all account/gas/rent/tip/fee inputs are explicit.
- Paper lifecycle, journal, deduplication, durable receipt store, crash recovery and storage-pressure boundaries are healthy.

## Campaign behavior
- Run sender-free paper/shadow attempts only through the installed canonical paper service and existing campaign owner.
- Preserve every source observation, quote, rejected opportunity, route build, simulation, economics result, state transition and reason.
- Use no fake fills and no synthetic success to cover live-source failures. Fixture/replay mode must be clearly labeled and cannot count as a live campaign.
- Track candidate count, unique exact routes, lender/resource utilization, simulated net result distribution, rejected amounts, stale-state rate, quote age, RPC/provider latency, compute/message size, failure causes, and replay divergence.
- Keep a strict separation between gross profit, all-in simulated net result, unfilled/failed attempts and unavailable data.
- A 24-hour duration is a measurement window, not proof of profitability or production readiness.

## Stop conditions
Stop immediately on source-generation drift, independent quorum failure, stale/missing state, capacity disagreement, failed repayment coverage, unsafe signer/sender import, persistence corruption, unknown spend/cost, account setup requirement not authorized, or a QPR stop condition.

## Deliverables
Campaign manifest + authority/config/source digests; start/end timestamps and actual duration; live vs replay counts; deterministic replay; negative evidence; full verifier output and exact test count; per-strategy/per-provider report; blockers and next task. Keep live_enabled/sign_enabled/send_enabled false. No production promotion.
