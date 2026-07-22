# Roadmap PR-03 — Rooted provider admission vertical

This PR implements the first active integration slice of numeric roadmap PR-03.
It reuses the existing bounded Helius delivery inbox rather than creating a
second webhook authority.

## Active path

```text
bounded authenticated Helius delivery
→ durable `helius_event_inbox`
→ unresolved-gap guard
→ independent rooted RPC quorum
→ provider admission/drift/expiry validation
→ HMAC-SHA256 authenticated rooted evidence
→ atomic evidence + handoff + inbox-state commit
→ concrete `A3RootedProviderBatchSource`
```

## Evidence identity

Every admitted event binds:

- canonical Helius event and delivery identity;
- exact raw payload hash and immutable SQLite evidence reference;
- transaction signature and slot;
- cluster genesis and independently observed rooted slot;
- provider admission and endpoint identity;
- RPC quorum evidence hash with distinct endpoint/correlation groups;
- release and PolicyBundle identity;
- verifier trust-anchor identity and validity window.

The protected worker authenticates the canonical evidence envelope using
HMAC-SHA256. The secret is injected and never persisted. This is an ingestion
authenticity boundary, not the asymmetric release-qualification authority owned
by roadmap PR-05.

## Durability and duplicate semantics

Evidence insertion, provider handoff insertion and transition of the Helius
inbox row from `queued` to `verified` occur in one `BEGIN IMMEDIATE`
transaction. A duplicate event is accepted only when event, release,
PolicyBundle and evidence identities all match. Conflicting identity fails
closed.

Upstream RPC outage, quorum disagreement, stale evidence, provider drift and
unresolved slot gaps leave the event queued and write an audit record. A valid
event is not dead-lettered because a generic retry count was exhausted.

## Safety invariants

- no signer import;
- no sender or transaction submission;
- no live activation;
- no strategy execution inside the webhook acknowledgement path;
- A3 receives only authenticated durable handoffs;
- tampered stored evidence blocks at the A3 boundary.

## Remaining PR-03 scope

This slice does not complete all numeric PR-03 requirements. Follow-up work must
install the real HTTP server/supervisor composition, implement protected network
collectors and bounded rooted backfill, wire Jupiter Swap V2 `/build`, capture
coherent MarginFi program/bank/oracle/repayment evidence, and connect the handoff
to the final PR-02 transaction authority.
