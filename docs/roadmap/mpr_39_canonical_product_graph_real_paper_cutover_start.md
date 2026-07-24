# MPR-39 — Canonical Product Graph, Installed Runtime and Real Paper Cutover

This draft PR starts **MPR-39** from the master production-ready closure pack.

## Objective

Replace the current split runtime and recorded-only installed command with one installed, continuously operating, sender-free paper/shadow product graph. Remove every alternate source execution authority.

## Initial scope captured for follow-up implementation

- Make the installed console script the only supported product launcher.
- Retire alternate CLIs and historical direct launchers such as source-only runtime paths.
- Remove or quarantine source-based production launch instructions.
- Define one runtime composition root owning provider gateway, webhook intake, trusted time, opportunity detector, queue/tracker, risk/admission, capital reservation, compiler/simulator, paper settlement, durable state, outbox, readiness, metrics and logging.
- Replace recorded-only source behavior with strict pluggable source ports.
- Add a continuous bounded sender-free paper service with supervision, bounded queues, backpressure, shutdown deadline, restart generation and dependency heartbeat.
- Fix canonical cycle identity so deterministic replay identity is distinct from unique execution-cycle identity.
- Bind cycle evidence to actual immutable artifacts and make reports environment-independent.
- Enforce source/wheel/container capability parity and sender-free import boundaries.
- Keep recorded inputs as deterministic test/replay adapters only.

## Safety boundary

This start slice does **not** enable:

- live trading;
- signer/private-key access;
- transaction submission;
- Jito submission;
- unrestricted live mode;
- production-ready promotion.

It only opens the isolated review branch and records the implementation target.
