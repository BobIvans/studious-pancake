# MPR-TD-03 capacity and storage baseline

**Recorded:** 2026-08-02 UTC
**Status:** blocked at Phase 0; no runtime or persistence implementation was attempted.
**Branch:** `codex/mpr-td-03-capacity-storage-operations`

## Exact accepted base

The repository initially had no configured remote. The requested repository was configured as
`origin`, and `git fetch origin main --prune` resolved the accepted `main` branch to:

```text
f837394449b3921c8f502543aaf3f2694274093a
```

This SHA is the exact base for this branch.

## Dependency gate

MPR-TD-01 is represented by merge commit `f837394449b3921c8f502543aaf3f2694274093a`
(PR #458). Its only non-merge commit is `51b5043`, titled `docs: record MPR-TD-01
current-main baseline and overlap inventory`. That baseline explicitly states that MPR-TD-01
is **not complete**, stopped at Phase 0, and did not perform its semantic-owner, schema,
type, entrypoint, or historical-module cutovers.

No MPR-TD-02 merge or implementation commit is present in the fetched `origin/main` history.
Searches of all fetched refs and the working tree found no MPR-TD-02 canonical failure and
verification evidence or requested verifier. Therefore the accepted base does not provide
the two completed prerequisite Mega PRs required by this work.

This triggers the request's hard stop: MPR-TD-01 and MPR-TD-02 are not both present as
completed accepted foundations. Proceeding would require MPR-TD-03 to invent package,
schema, type, failure, verification, runtime, and persistence authorities that this Mega PR
is expressly forbidden to absorb.

## Open pull-request overlap inspection

The GitHub REST API was queried for all open pull requests, and their changed-file lists were
searched for runtime supervision, async ownership, transport, provider, paper/shadow,
simulation, execution, persistence, durability, observability, SQLite, recovery, benchmark,
and deployment paths.

| PR | Branch | Relevant current ownership | Disposition |
| --- | --- | --- | --- |
| #443 | `mpr-43-unified-persistence-recovery` | Introduces `src/durability/mpr43_unified_persistence.py` and a persistence/recovery verifier. | **Hard-stop overlap:** unresolved PR changes the same database authority. Do not merge or duplicate it blindly. |
| #298 | `roadmap-pr-198-durable-runtime-supervision` | Adds paper/shadow durable runtime supervision. | Runtime supervision and shutdown overlap; owner remains unresolved. |
| #275 | `roadmap/pr-200-continuous-paper-shadow` | Adds a continuous sender-free paper/shadow harness. | Load/runtime overlap; no implementation was reused. |
| #428 | `mpr-next-09-continuous-installed-paper-shadow-soak` | Adds installed continuous shadow-soak producer and verification. | Installed benchmark/soak overlap; no implementation was reused. |
| #173 | `pr-154-durable-data-reliability-supervisor` | Adds data-plane durability supervision. | Durability and async ownership overlap; no implementation was reused. |
| #199 | `integration/canonical-paper-vertical-a2-supported-runtime` | Changes the supported paper runtime. | Active runtime overlap; canonical owner unresolved. |
| #149 | `pr-146-bounded-response-parsing` | Changes `src/routing/transport.py`. | Canonical HTTP transport overlap; no implementation was reused. |
| #233 | `pr-194-proof-critical-scheduling` | Changes provider quota and scheduling. | Backpressure/provider overlap; no implementation was reused. |
| #440 | `mpr-41-trusted-provider-data-plane` | Adds a provider data-plane authority. | Provider ownership overlap; no implementation was reused. |
| #442 | `mpr-45-operational-truth-release-gates-slo-soak` | Adds soak/fault/recovery verification. | Qualification evidence overlap; no implementation was reused. |
| #217 | `pr-190-canonical-config-identity` | Changes execution, paper/shadow, observability, and container runtime. | Broad runtime overlap; no implementation was reused. |
| #439 | `mpr-44-enforced-deployment-supply-chain` | Changes deployment qualification tooling. | Deployment evidence overlap outside this Mega PR. |
| #445 / #446 | Mega-PR roadmap branches | Roadmap-only runtime/durability/provider and paper qualification documents. | No implementation to reuse. |

PR #443 independently triggers the request's hard stop for an unresolved pull request
changing the same database authority.

## Canonical-owner assessment

The accepted tree contains `src/routing/transport.py` and historical runtime, paper/shadow,
durability, observability, and persistence implementations. `src/persistence/` currently
contains only `__init__.py` and `async_writer_pr200.py`; the requested accepted semantic
connection, pragma, maintenance, backup, and recovery authorities are absent. The existing
MPR-TD-01 baseline also says its canonical cutover was not performed.

Consequently, this baseline cannot truthfully designate accepted canonical runtime,
transport, and persistence owners for the requested modifications. Historical modules and
open PR #443 must not be promoted into a second persistence architecture merely to continue.

## Blockers and debt ledger

| Blocker | Required resolution | Definition-of-Done effect |
| --- | --- | --- |
| MPR-TD-01 merged only a Phase-0 document that explicitly says its required cutovers are incomplete. | Complete and accept MPR-TD-01 on `main`. | Semantic installed ownership, schemas, strict interfaces, and canonical owners are unavailable. |
| MPR-TD-02 is absent from fetched `origin/main`. | Complete and accept MPR-TD-02 on `main`. | Failure/reason, deadline, cancellation, and verification foundations cannot be assumed. |
| Open PR #443 changes unified persistence and recovery authority. | Merge, close, or issue an explicit ownership disposition. | SQLite connection and recovery authority work must not begin. |
| Runtime/transport/paper/provider/qualification overlaps remain open. | Resolve the listed PRs against accepted semantic owners. | Capacity measurements would not qualify a stable accepted runtime. |
| No accepted canonical persistence authority can be confirmed. | Establish it through the prerequisite functional cutover. | Creating the requested SQLite factory would risk a parallel persistence architecture. |
| Product requirements do not provide accepted RPO/RTO targets. | Product owner must define acceptance targets after a real recovery baseline. | RPO/RTO acceptance cannot be claimed or fabricated. |
| No authoritative production image or credentials were supplied. | Artifact and external-profile owners must supply them when applicable. | Image and external profiles remain blocked, not passed. |
| No long-run duration or realistic recovery fixture has elapsed or been qualified in this stopped phase. | Run after dependency and ownership gates clear. | Leak, capacity, backup, restore, replay, and recovery results cannot be claimed. |

Because the dependency and ownership hard stops occur before implementation, no capacity
manifest, query catalog, retention policy, database evidence, benchmark timing, RPO, RTO,
resource count, or successful qualification result was generated. Creating those artifacts
with green defaults would violate the explicit prohibition on fabricated evidence.

## Definition of Done status

MPR-TD-03 is **not complete**. Phase 0 established the exact base and inspected open-PR
ownership, then stopped. Phases 1 through 11, all checkpoint implementations, installed-wheel
capacity profiles, operational SQLite changes, recovery drills, and final evidence remain
undone and blocked.

The branch remains sender-free because no runtime code changed. Private-key loading, signer
initialization, transaction signing, Solana RPC submission, Jito submission, and live mode
were not added or enabled. No benchmark, backup, restore, RPO, RTO, production-image, or
production-readiness claim is made.
