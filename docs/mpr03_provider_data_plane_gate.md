# MPR-03 — Rooted provider and authenticated data-plane gate

This document describes the safe continuation slice for **MPR-03 — Rooted
provider and authenticated data plane** from the V4 production-readiness roadmap.

The goal of this slice is not to turn on live execution. The goal is to make the
provider/data-plane acceptance contract machine-checkable before any installed
runtime can claim that provider data, Helius deliveries, rooted quorum evidence
or asynchronous persistence are production-ready.

## Boundary

`src/mpr03_provider_data_plane.py` is offline and side-effect free. It does not:

- open HTTP, JSON-RPC or WebSocket connections;
- start webhook listeners;
- read provider credentials;
- import signer, sender, wallet or private-key code;
- submit transactions;
- enable live trading.

The module always keeps these capabilities disabled:

- `live_capability_allowed() == False`
- `signer_capability_allowed() == False`
- `sender_capability_allowed() == False`

## Evidence schema

The validator accepts `mpr03.rooted-provider-data-plane.v1` evidence with these
required sections:

- artifact hashes for provider registry, transport policy, quota authority,
  rooted quorum, ingress policy, webhook queue, async writer and backfill policy;
- bounded transport policy: pinned DNS resolution, post-connect peer IP checks,
  TLS verification, redirect controls, total deadlines, response limits, gzip
  bomb rejection, duplicate-key/NaN JSON rejection and retry classification;
- signed provider registry with unique provider IDs and registry-backed
  independence rather than caller-created labels;
- cross-process quota authority with authority-owned clock, transactional
  reservation, retention and retry-storm negative evidence;
- rooted quorum with unique providers, independent groups, minContextSlot,
  request-response binding, slot-skew and evidence-age bounds;
- Helius ingress with mandatory policy, constant-time auth comparison,
  atomic audit+delivery+event commit, ACK-after-commit semantics, conflict
  quarantine and a durable queued/claimed/processed/DLQ work queue;
- durable async writer with descriptor-hash binding, mismatch rejection,
  authority-computed byte size, no assert-only invariants and crash reconciliation;
- required negative drills for DNS rebinding, gzip bombs, duplicate JSON keys,
  NaN, malformed schema, retry storms, duplicate quorum endpoints and crash
  points around webhook enqueue/claim/processing and async writer failure.

## Findings addressed by this gate

This slice turns the MPR-03 findings into explicit fail-closed diagnostics:

- malformed provider payloads must not become generic 500s;
- DNS rebinding/private-IP routes must be denied before connect and after connect;
- quota must not trust caller wall-clock or unbounded bucket storage;
- rooted quorum must not pass with duplicated endpoints or caller-defined groups;
- webhook receipt must commit audit identity and durable events in one transaction;
- work queues need claim leases, retry limits and DLQ;
- async writer idempotency must bind operation IDs to immutable descriptors;
- accepted ingress work must not be cancelled during shutdown.

## Remaining full MPR-03 work

This PR is not a full provider-plane cutover. Remaining work includes wiring the
contract into the single installed runtime from MPR-01, replacing compatibility
ingress constructors, implementing the shared hardened transport, migrating
Helius deliveries onto the durable work queue, adding real provider registry
signatures and proving backfill/replay from captured provider fixtures.
