# PR-196 — External protocol conformance and rooted data plane

This slice implements the first sender-free foundation of the 7-PR roadmap PR-196.

## Purpose

PR-196 must prove that read-only external data and provider instruction bundles match current deployed contracts before any sender-free transaction kernel can consume them.

## Implemented boundary

- Versioned, expiring, reviewer-owned evidence envelope.
- MarginFi / Project 0 SDK and deployed-program attestation gate.
- Jupiter Swap V2 `/swap/v2/build` route parser that rejects legacy `percent` and requires exact `bps` sum of 10,000.
- Rooted multi-RPC quorum model with independent source-group and state-hash agreement.
- Provider registry roles: `execution_composable`, `discovery_only`, and `forbidden`.
- Helius duplicate-delivery normalization with deterministic idempotency and gap-backfill marker.
- Protocol report that remains sender-free: live execution, signer, sender and submission all remain disabled.

## Deliberately absent

- No network calls.
- No trading wallet or signer.
- No RPC/Jito submission.
- No generated credentialed artifacts.
- No modification to `config/format_targets.txt` while parallel branches are moving.

## Follow-up work for full PR-196

- Real credentialed read-only probes.
- Current MarginFi/P0 deployed account vectors and independently decoded golden vectors.
- On-chain ALT/programdata checks at adequate context slots.
- Durable Helius inbox implementation integrated with the PR-195 lifecycle authority.
- Drift job artifacts, expiry policy and signed provider-registry generation.
