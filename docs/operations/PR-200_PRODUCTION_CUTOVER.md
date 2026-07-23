# PR-200 — production sandbox, operations and cutover gate

This document is a fail-closed operations boundary for PR-200. It does not mark
this repository production-ready and it does not enable live submission. It
makes production promotion impossible until the release has a signed cutover
unit, sandbox isolation, readiness evidence, backup/restore proof, rollback
proof and fault-injection results.

## Current state

`config/production_cutover_manifest.json` is intentionally set to:

```json
{
  "promotion_state": "blocked_pending_evidence",
  "live_trading_enabled": false
}
```

The validator accepts that blocked state only when every production cutover
requirement is still a promotion blocker:

```bash
python scripts/verify_pr200_production_cutover.py --json
```

## Required cutover unit

A future production candidate must publish a single signed release manifest that
binds all of these items:

- runtime wheel digest;
- digest-pinned runtime image;
- SBOM/provenance digest;
- generated config digest;
- capability/reachability manifest digest;
- MarginFi/P0/Jupiter program, IDL and schema hashes;
- database schema/event-chain fingerprint;
- 24–72 hour sender-free shadow campaign report;
- fault-injection report;
- backup/restore drill report.

Until those artifacts exist and match the signed release unit, the only valid
state is blocked.

## Isolation requirements

The runtime and signer are separate trust domains.

- Runtime image must be digest-pinned, read-only and egress allowlisted.
- Runtime may use only approved provider, RPC, Jito and telemetry egress.
- Signer must run as a separate process/service.
- Signer must not share runtime filesystem, internet egress or plaintext private
  key environment variables.
- Generated production keys are forbidden; production key material must come
  from an external secret provider or signer service handle.

## Readiness and liveness

Liveness is process health only. Readiness must close when the system cannot
safely trade or safely prove sender-free evidence. The readiness probe must be
distinct from liveness and must block on at least:

- dead strategy;
- stale rooted data;
- degraded DB/control plane;
- release/emergency latch;
- signer unavailable;
- outstanding `UNKNOWN` attempt;
- exhausted provider budget.

## Mandatory fault-injection matrix

Before promotion, a release must pass deterministic drills for:

- crash after state row but before event row;
- crash after provider accepts submission but before DB acknowledgement;
- duplicate attempt creation across processes;
- clock jump, suspend and reboot;
- disk-full or read-only DB;
- corrupt WAL or torn journal tail;
- duplicate and lost webhooks;
- provider 429/5xx across replicas;
- DNS resolving to private or link-local addresses;
- strategy task failure;
- SIGTERM with non-empty queue;
- blockhash expiry before signing or sending;
- Jito ACK without chain record;
- landed failed transaction;
- oversized v0 message;
- malicious allowed-program instruction;
- unknown Token-2022 extension;
- backup during WAL writes.

Every drill must include the expected invariant and a replayable evidence
artifact.

## Backup, restore and rollback

Production rollback is drain-only. The old writer must never write over the new
lifecycle schema.

A rollback candidate is allowed only after:

1. admission is disabled;
2. outstanding signed intents are zero;
3. outstanding `UNKNOWN` attempts are zero or reconciled;
4. backup from the running system restores into a clean environment;
5. restored DB passes integrity, schema fingerprint and event-chain checks;
6. the new DB remains the source of truth after rollback.

## Operator command

```bash
make pr200-production-cutover
```

The command validates that PR-200 is still a blocked gate, not a live promotion.
