# PR-224 production platform, operations and verifiable cutover gate

This slice starts **PR-224 — Production Platform, Operations and Verifiable
Cutover** from the mega-roadmap as a narrow reviewable gate.

The roadmap assigns PR-224 the final infrastructure, operational truth and
deployment cutover boundary after PR-219 through PR-223. This slice does not
perform that cutover. It defines the evidence contract that a real production
release must satisfy before cutover review can proceed.

## Covered boundary

The validator blocks cutover unless evidence proves all of the following:

- digest-pinned runtime and signer release set;
- deny-by-default network with allowlisted egress gateway;
- signer separated from runtime by network, mounts and user identity;
- no example secrets, plaintext keys or shared `/tmp` state;
- seccomp/AppArmor validated by measured traces, including SQLite WAL and
  archive operations;
- one authenticated management API with readiness that blocks empty or dead
  runtime states;
- materialized deployed-state validator, SLO drills and rollback rehearsal;
- accepted upstream PR-219 through PR-223 gates before PR-224 review;
- tiny canary auto-stop preserved, unrestricted live still forbidden.

## Non-goals

This PR does not:

- enable live trading;
- enable signer or sender execution;
- perform deployment cutover;
- rotate secrets;
- build or publish OCI images;
- rewrite seccomp/AppArmor policy;
- run real drills against infrastructure.

It only adds a deterministic acceptance contract and focused tests for the
PR-224 production-cutover boundary.
