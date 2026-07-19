# PR-007 runtime vertical slice

The production entrypoint (`arb_bot.py`) builds `ArbitrageApplication` with safe defaults: legacy production detectors are disabled with machine-readable reasons until real detectors are implemented. `live` mode is rejected during startup before producer or consumer tasks are launched.

Runtime flow is intentionally structural and shadow-only:

1. a strategy detector publishes an immutable `Opportunity`;
2. `OpportunityQueue` applies TTL, finite priority ranking, bounded backpressure, and pending duplicate checks;
3. `OpportunityConsumer` claims the opportunity in the process-local lifecycle tracker;
4. the application-level shadow handler records a terminal `shadow_not_executed` result with `executed=false` and reason `execution_backend_out_of_scope`.

No transaction compiler, signer, RPC sender, Jito sender, fake signature, fake PnL, or fake simulation result is part of this path.

## Legacy execution quarantine

Legacy modules under `src/ingest/` and `src/legacy_arb_bot.py` retain historical send-oriented code for future reference. They are quarantined from the new runtime: `arb_bot.py`, `src/application.py`, and `src/strategy/**` must not import legacy send routers, Jito executors, signers, or transaction builders. Tests enforce this boundary. Future PRs will replace this quarantine with a new compiler/simulator/cost-policy execution stack rather than re-enabling legacy sends.
