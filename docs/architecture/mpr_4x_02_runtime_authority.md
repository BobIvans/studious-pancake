# MPR-4X-02 — canonical runtime authority and lifecycle cutover

## Dependency

MPR-4X-02 starts from accepted MPR-4X-01. MPR-4X-01 owns canonical schema and architecture reachability. This PR consumes that foundation and moves runtime composition/lifecycle semantics under one installed authority.

## Canonical runtime contract

The target is one active composition root and one semantic owner for runtime authority:

- active entrypoint: `flashloan-bot`;
- composition module: `src.cli_pr189:main`;
- sender-free paper service: `src.paper_shadow.durable_service_a3:build_installed_durable_paper_service`;
- lifecycle authority: `src.durability.unified_authority_pr02:UnifiedLifecycleAuthority`;
- capital authority: `src.economics.durable_reservations:DurableCapitalCoordinator`.

`src.runtime_authority` is the canonical contract owner. The historical `src.runtime_authority_pr01` module is reduced to a compatibility alias and must not retain independent runtime semantics.

## Required invariants

- exactly one active composition root;
- no second active runtime surface;
- every sensitive write binds `owner_id`, `fencing_token`, `lease_generation`, `boot_id`, `process_generation`, and `payload_hash`;
- `attempt_generation >= 1` and participates in reservation identity;
- semantic idempotency rejects equal keys carrying different command identities;
- terminal states never regress;
- terminal result and outbox visibility are atomic;
- capital availability comparison and reservation happen in one transaction;
- critical worker death closes readiness;
- queues are bounded;
- sender remains absent and live mode remains disabled.

## Initial cutover slice

This branch begins the migration by:

1. adding canonical `src.runtime_authority`;
2. moving the packaged runtime authority manifest to `src/resources/runtime_authority.json`;
3. converting `src.runtime_authority_pr01` into a thin compatibility alias;
4. adding focused architecture tests for composition uniqueness, safety boundary, capital identity, and alias ownership.

## Remaining work in this PR

- register the runtime authority schema in the canonical MPR-4X-01 schema registry;
- add exhaustive reachability/production-surface ownership checks;
- bind the installed wheel to the canonical runtime authority resource;
- verify lifecycle/outbox/capital transaction semantics against the concrete durable implementations rather than manifest declaration alone;
- add a mandatory MPR-4X-02 verifier and SHA-pinned GitHub Actions workflow;
- include the verifier in full repository verification;
- delete or quarantine any competing semantic owner discovered during cutover.

## Safety boundary

MPR-4X-02 does not load private keys, initialize a signer, submit transactions, enable Jito submission, or enable live trading. Runtime remains sender-free and live-disabled while the durable authority cutover is proven.
