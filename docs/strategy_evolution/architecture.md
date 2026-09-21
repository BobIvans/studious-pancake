# Strategy Evolution architecture

PR-353 adds `src/strategy_evolution` as a sender-free research layer. It is not
an execution plane.

The flow is:

```text
admitted evidence
  -> EVO research contract
  -> ResearchCandidate
  -> replay / walk-forward qualification
  -> at most VERIFIED_SHADOW
```

Allowed states are exactly `DISABLED`, `RECORDED_OFFLINE`,
`SHADOW_CANDIDATE`, `VERIFIED_SHADOW`, and
`REJECTED_WITH_EVIDENCE`. No live synonym is accepted.

The shared immutable kernel carries explicit chain/domain identity, event and
observation time, finality, integer base units, cost/value/capacity bands,
scenario IDs, evidence digests, config digest, code SHA and typed blockers.
Candidate IDs are domain-separated canonical-JSON SHA-256 digests.

The only bridge to the canonical execution-facing domain is
`shadow_opportunity_adapter`. It accepts only an already
`VERIFIED_SHADOW` candidate, creates the existing canonical
`src.strategy.domain.Opportunity`, and does not enqueue, sign or submit it.

## Compatibility / migration

PR-353 adds no writer migration to existing canonical stores. The new config
schema is `pr353.strategy-evolution.config.v1` and is additive. Readers must
ignore the package entirely when absent. Rollback is therefore config-first and
backward-compatible with the pre-PR-353 repository.
