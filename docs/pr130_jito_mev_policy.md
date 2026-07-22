# PR-130 Jito MEV protection policy

This document records the first-production Jito policy added by PR-130.

## Policy

The first production Jito path must use:

- exactly one strategy transaction;
- Jito `sendTransaction` / `JITO_SINGLE` as the canonical live transport;
- optional `bundleOnly=true` revert-protection mode;
- one Jito tip in the same transaction as the strategy;
- a static, non-ALT tip account;
- no standalone tip transaction;
- no multi-transaction bundle for first live;
- no bundle acknowledgement or bundle status as economic settlement proof.

## Reason

Jito bundle acknowledgement is transport evidence only. It does not prove final
economic settlement. Multi-transaction bundles and standalone tip transactions
remain disabled until later evidence proves each independently replayable
transaction is safe under uncled-block rebroadcast/unbundling chaos.

## Current implementation boundary

- `src/submission/jito_mev_policy.py` provides deterministic policy evaluation.
- `src/submission/canonical_sender.py` exposes the policy in the redacted sender
  manifest and blocks live `JITO_BUNDLE` settings.
- `tests/test_pr130_jito_mev_unbundling_policy.py` covers the first-production
  happy path plus standalone tip, multi-transaction bundle, ALT tip account and
  bundle-status-as-settlement failures.

## Non-goals

- No live submission is enabled.
- No sender, signer, RPC, Jito endpoint or wallet mutation is added.
- Finalized settlement reconciliation remains PR-138.
