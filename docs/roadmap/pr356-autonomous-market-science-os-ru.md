# PR-356 — Autonomous Market Science & Unified Resource Economy OS

## Current-head truth

Implementation base: 654553d430fc0752a9567e3d9e334914352044ce, the main head observed after merged GitHub #538.

Reconciled predecessors: #534 PR-355 core, #535 corrective completion, #536 evidence seal,
#537 PR-353 semantic hardening, and #538 Market Data Layer Evolution. A root AGENTS.md was
not present during current-head reconciliation.

## Scope disposition

This PR uses the prompt's allowed minimum-correct-end-to-end-vertical rule rather than creating
hundreds of empty functions. All 68 internal packages and all 544 provisional requirements are
represented in machine-readable registries. 108 requirements have concrete PR-356 contracts,
45 are reconciled through existing/evidence owners, and 391 stay explicit NOT_RUN. No permanent
NF range is allocated. W2F-044 is the canonical measure_reaction_gap owner; W3F-043 is only a
consumer alias.

## Implemented verticals

W2 adds versioned topology, deferred-constraint research, visible versus reallocatable liquidity,
reallocation race/cost evidence, information visibility/reveal timelines, reaction-gap semantics,
and cross-chain finality-class research. Current Morpho/Euler deployment and fork conformance are
not claimed.

W3/W4 add frozen campaign/holdout contracts, mature/censored/missing label preservation, CAMP-01
reachable-capacity comparisons, BENCH-02-style evidence, seven deterministic fail-closed red-team
fixtures, and replication bundles. CAMP-01 and BENCH-02 remain BLOCKED_EXTERNAL for real fork truth.

W5 adds typed hypothesis identity, novelty/negative-result checks, symbolic-unit validation,
causal downgrade, effect-free strategy-program feasibility/obligation checks, and counterexample
memory. DISC-01 is contract-implemented but no empirical symbolic law is claimed.

W6 adds a seeded deterministic synthetic ecology, competitor/crowding measurements, bounded
self-play research helpers, reality-gap downgrade rules, and untrusted-remote-artifact sandboxing.
ECO-01 is fixture-tested synthetic only; no held-out Solana ecology calibration is claimed.

W7 adds StrategyEvidenceCard/ResourceClaimVector contracts, dependency/common-exposure research,
scenario/capacity surfaces, a bounded exact conflict/resource portfolio solver, tail-loss constraint,
canonical feasibility recheck marker, and immutable AllocationProposal outputs with
execution_right=false.

## Registry and evidence

config/pr356_registry.json contains 68 packages, 16 MarketPacks, 8 campaigns, 10 benchmarks,
10 red-team cases, 30 W5/W6/W7 challenges, 124 preregistered hypothesis IDs, and 58 upstream/tool
dossier IDs. Upstream rows remain REFERENCE_ONLY_REVERIFY: no source copy, fresh license claim,
remote mutation, or paid-resource use is asserted.

## Safety boundary

production_ready=false, live_enabled=false, signer_access=false, submission_access=false,
wallet_access=false, remote_mutation=false, automatic_promotion=false, and
automatic_capital_increase=false. MarginFi remains PAUSED. Slumlord remains REQUIRED for
low-capital qualification. Synthetic/replay/fixture evidence cannot become realized PnL or live
authority. MERGED != QUALIFIED != AUTHORIZED_LIVE.

## Verification and blockers

The dedicated PR-356 workflow compiles the new surfaces, runs scripts/verify_pr356.py, focused
tests, and predecessor PR-353/354/355 plus Market Data Evolution gates. scripts/verify_repo.py also
invokes the PR-356 verifier.

Honest blockers remain: current Morpho/Euler pins plus fork evidence, real-source acquisition beyond
existing repo fixtures, held-out real Solana competition ecology, a real federated-agent task,
second-environment independent replication, the 391 NOT_RUN provisional functions, and any
live/finalized/profitability evidence.

Rollback disables PR-356 consumers first, stops optional research delegation, quarantines invalid
claims/topologies, detaches consumers, and restores prior frontier selection while preserving
receipts and negative knowledge. No fund/transaction recovery is needed because the PR has no
execution effects.


## Corrective completion after GitHub #539

Foundation #539 merged at main `67e87a45683bccd2f5ae8f282d0b20493e9780b3`.
The corrective completion closes the remaining 391 provisional requirement
contracts without inventing empirical success.

Current code/research-scope truth:

- 544/544 requirements have an exact owner disposition;
- 499 are concrete callable PR-356 contracts;
- 45 are satisfied by existing canonical owners;
- 0 remain NOT_RUN at the implementation-contract layer;
- all 68 packages are CONTRACT_IMPLEMENTED or SATISFIED_BY_EXISTING;
- the three #539 review findings are fixed;
- an isolated-process replication gate and integrated receipt chain are added;
- `roadmap_code_research_scope_complete=true`;
- `external_qualification_complete=false`.

External/factual blockers remain explicit rather than converted to PASS: current
Morpho/Euler deployment and fork evidence, new primary real-source acquisition,
held-out real Solana ecology calibration, remote federation evidence, and any
live/finalized/profitability evidence.

Therefore code/research implementation closure does not change the original
effect boundary: `MERGED != QUALIFIED != AUTHORIZED_LIVE`.
