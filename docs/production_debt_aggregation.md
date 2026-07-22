# Production readiness debt aggregation and external contract boundary

This change converts the remaining production-readiness gap into one reviewed,
machine-readable inventory. It intentionally does **not** enable live trading,
add a signer, submit a transaction, or relabel documentation as execution proof.

## Why this exists

The repository already contains many narrow safety gates, but those gates do not
by themselves create an integrated production system. The active capability
matrix still says `not-production-ready`, live mode is unavailable, Kamino has no
supported combinations, and the installed wheel excludes broad ingest and sender
namespaces. A reviewer therefore needs one place that distinguishes:

- implemented policy or fixture gates;
- missing active runtime wiring;
- missing external-provider conformance;
- missing non-synthetic operational evidence;
- deliberate live-mode blocks.

The canonical inventory is `src/resources/production_debt.json`. The evaluator
is `src/production_debt.py`, and the command-line report is:

```bash
python scripts/production_debt_audit.py --check --json
```

`--check` validates inventory and repository consistency but succeeds while
reviewed debt remains open. `--require-ready` is a stronger release-side latch
and fails until no paper/live blockers remain.

## Three large follow-up batches

### 1. Canonical runtime, execution and durable state cutover

This batch owns source/wheel parity, one composition root, removal of parallel
legacy paths, exact simulation binding, canonical transaction proof, capital and
account lifecycle reservations, one durable lifecycle authority, rooted RPC
quorum, coherent slots and finalized settlement.

It should be completed as one integration PR after the currently parallel
policy/runtime/transaction PRs stabilize. Splitting the cutover into more small
review-only gates would preserve the present problem: many individually correct
contracts without one active vertical.

### 2. Provider and protocol conformance with pinned external truth

This batch owns credentialed and deployment-backed conformance for:

- Solana v0 RPC simulation, submission and finalized transaction evidence;
- Jupiter Swap V2 `/build` raw instruction composition;
- Helius webhook authorization, durable dedup and gap recovery;
- Jito bundle limits, tips, rate limits, ambiguity and unbundling safety;
- MarginFi v2 source/deployment/golden-vector proof;
- Kamino KLend source/deployment/supported-combination proof;
- OKX, OpenOcean and Odos discovery-only boundaries.

The registry additions in this change are all `disabled-unverified`. A pinned
review snapshot proves only that the repository reviewed an official contract;
it does not grant execution permission.

### 3. Real operational evidence, hardened deployment and reviewed canary

This batch owns repeated sender-free shadow/paper evidence, provider drift jobs,
finalized realized economics, hermetic image provenance, SLOs, isolated signer,
secret-incident drills, lineage quarantine and bounded canary approvals.

A canary may be proposed only after the first two batches are integrated and the
evidence is non-synthetic, immutable, current, redacted and reviewed by two
independent humans.

## External compatibility facts pinned by this change

The reviewed snapshots capture the following fail-closed assumptions:

- Jupiter Swap V2 `/build` returns composable instruction groups, lookup-table
  mapping and blockhash metadata, but requires credentialed schema and exact
  composition evidence before use.
- Jito bundle IDs are receipts, not landing proof; bundle/status polling,
  minimum tips, bounded rate limits and uncle/unbundling protection remain
  required.
- Solana v0 settlement requires explicit transaction-version support, lookup
  table provenance and finalized transaction/balance evidence.
- Helius may echo configured `authHeader` as `Authorization`; local durable
  dedup, configuration drift and gap recovery are still repository duties.
- MarginFi and Kamino program IDs are reviewed identities, not deployed-bytecode
  or instruction-layout attestations.

## Safety and non-goals

- Live remains unavailable.
- No provider is promoted to execution allowed.
- No network probe runs in CI.
- No secrets or credential values are stored.
- No sender, signer, wallet or transaction submission is added.
- The empty Kamino combinations registry is reported as a P0 blocker rather than
  populated with guessed market or reserve identities.
