# MPR-2613 guarded production operations

Status: **NEW_PROPOSED_EXTENSION / IMPLEMENTED_ONLY / BLOCKED_INTEGRATION**

MPR-2613 is not presented as a recovered historical task. It is the newly proposed post-release guarded-operations layer defined after the MPR-2601..2612 roadmap.

## Current base

- repository: `BobIvans/studious-pancake`
- base at branch creation: `d23f82e20d10345926742352739b1a6ca3f7a859`
- base meaning: merged MPR-2611 / PR #482
- accepted MPR-2612 release decision: **not found at implementation start**

Production activation therefore remains `BLOCKED_INTEGRATION`. The code may be reviewed and verified before 2612 exists, but it cannot materialize an operable envelope from an unaccepted release.

## Ownership / collision boundary

MPR-2613 consumes and does not replace the accepted owners for runtime/lifecycle/capital, provider governance, human intervention, rollback/release, protocol conformance, vertical execution, soak, signer/submission, canary, finalized economic ledger, qualification and the future MPR-2612 final release gate.

The existing `src/operations/operator_readiness.py` remains offline evidence/readiness logic. MPR-2613 does not convert it into a production supervisor. The new module owns only guarded post-release envelope/state/admission semantics.

## Implemented slice

`src/operations/mpr2613_guarded_operations.py` provides:

- immutable operating-envelope identity for the fixed v1 scope `circular_arbitrage + MarginFi + Jupiter`;
- release/tree/wheel/image/config/policy/schema/profile binding through opaque accepted-release evidence;
- cluster/wallet/payer/program/provider/credential/signer/submission generation binding;
- exact integer monetary caps and positive resource caps;
- durable states `LATCHED`, `DORMANT`, `SHADOW_ONLY`, `DRAINING`, `DEGRADED`, `ACTIVE`;
- initial `DORMANT` state and writer-generation fencing;
- monotone automation rule: automatic transitions may reduce authority only;
- explicit external authorization hash requirement for upward transitions;
- current-state admission that rechecks release/config/policy/profile/cluster/wallet/provider/signer/submission identity;
- rooted/protocol/candidate/firewall/final-simulation/conservative-economics gates;
- hard-latch, finalized reserve, realized loss, fee, tip, rent and unresolved-exposure gates;
- maximum additional principal calculation that can shrink below, but never exceed, the reviewed envelope cap;
- durable monotone SLO/error-budget accounting and downshift recommendations.

## Deliberately absent

This slice does not sign, submit, resend, clear latches, load credentials, promote capital tiers, accept a release, create real trades, implement a second provider controller, replace the finalized ledger, or auto-merge.

The following remain for later MPR-2613 completion after the real 2612 owner exists:

- adapter from the accepted MPR-2612 release-decision schema into `AcceptedReleaseIdentity`;
- integration with accepted MPR-2610 finalized economic counters and balance authority rather than caller-supplied test facts;
- runtime hooks immediately before signer/submission admission;
- durable drain/restart/failover/rollback orchestration using accepted lifecycle owners;
- backpressure priority queues protecting reconciliation/finality/control traffic;
- incident/alert delivery authority and alert-failure production blocking;
- backup/restore drills and restore-to-DORMANT fencing;
- installed staging end-to-end operate -> degrade -> drain -> restart -> restore -> shadow evidence;
- full T01-T30 and O01-O72 evidence matrix.

## Safety invariant

Automation may reject, shrink, degrade, drain, latch, or fall back to shadow. It may not increase principal/loss budget, add scope, promote a tier, clear a latch, accept a release, or self-promote back to a higher-authority state.
