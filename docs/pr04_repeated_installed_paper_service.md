# PR-04 — Repeated installed sender-free paper execution service

## Scope

This change replaces the installed paper command's one-shot scheduling behavior
with a sequential supervisor around the existing durable A3 cycle authority.
It intentionally does **not** create a new lifecycle database or claim that the
provider, Jupiter, MarginFi, planner, compiler, simulator, and reconciliation
vertical is already complete.

## Active runtime behavior

`flashloan-bot run --mode paper` now:

1. creates the existing durable SQLite A3 service;
2. installs SIGINT/SIGTERM shutdown handling;
3. executes one durable cycle at a time;
4. emits each committed cycle report;
5. starts another cycle only when `ready_for_next_cycle` is true;
6. stops fail-closed on a blocked or indeterminate cycle;
7. stops on signal or on the configured cycle limit.

The scheduler is configured once at startup through:

- `FLASHLOAN_PAPER_MAX_CYCLES` — `0` means no numeric limit;
- `FLASHLOAN_PAPER_IDLE_DELAY_SECONDS` — delay between admitted cycles.

The default A3 composition still has no concrete B3 provider batch, so it emits
a durable blocked report and exits after one cycle. This is honest fail-closed
behavior until PR-02 and PR-03 supply the canonical lifecycle/provider inputs.

## Safety invariants

The supervisor rejects any cycle report where:

- `sender_imported` is true;
- `submission_allowed` is true;
- `live_enabled` is true.

Cycles never overlap, so one process cannot acquire concurrent ownership through
this scheduling layer. `asyncio.CancelledError` is not swallowed.

## Deliberate boundary

This PR establishes the repeated installed-service control loop and active CLI
cutover. Remaining roadmap PR-04 work includes the typed real batch source,
production composition factory, outbox worker, queue budgets, provider-backed
wallet observations, wheel/container parity, and end-to-end captured-mainnet
paper outcome. Those dependencies must converge on PR-02/PR-03 rather than
creating a second authority here.
