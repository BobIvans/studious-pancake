# PR-210 — Measured sender-free runtime qualification gate

This PR starts the Pass 6 corrective package **PR-210 — Measured Sender-Free Runtime Qualification**.

The goal of this slice is not to start the runtime. The goal is to make the qualification evidence contract fail-closed before any later PR claims that sender-free paper/shadow evidence is production-grade.

## Boundary

`src/pr210_measured_sender_free_qualification.py` is offline and side-effect free. It does not import or start providers, wallets, signer code, RPC/Jito clients, webhook listeners, databases or live sender modules.

The report always keeps these capabilities disabled:

- `live_capability_allowed() == False`
- `signer_capability_allowed() == False`
- `sender_capability_allowed() == False`

## Evidence contract

The validator accepts `pr210.measured-sender-free-qualification.v1` evidence and requires:

- a materialized release artifact digest;
- one installed entrypoint and one composition-root id;
- materialized artifacts for the shadow trace, replay bundle, chaos report, event-store export and installed-artifact manifest;
- a trace that reaches the required sender-free stages from installed entrypoint start through deterministic replay;
- terminal outcomes for every admitted candidate, with zero `UNKNOWN` outcomes;
- derived counters backed by unique source event ids, not caller-supplied totals;
- continuous signed checkpoints proving at least 72 hours of soak and bounded checkpoint gaps;
- readiness behavior proving dead/stale workers fail workload readiness even if the management listener is alive;
- restart/replay evidence with zero leaked reservations, zero leaked claims and zero unexplained balance deltas.

## Findings addressed by this gate

This slice turns PR-210 findings into machine-checkable failure codes:

- F-244: contradictory qualification counters;
- F-245: provider/chaos counts exceeding total cycles;
- F-246: self-reported soak duration;
- F-247: non-materialized qualification artifacts;
- F-248: dataclass-only tests that do not prove installed composition-root trace.

## Deliberate non-goals

This PR does not:

- run a 72-hour soak;
- start `flashloan-bot paper`;
- run provider network calls;
- query Solana RPC;
- construct or simulate a transaction;
- access wallets or private keys;
- sign or submit bytes;
- migrate production DB state;
- claim production paper readiness.

## Remaining full PR-210 work

Later PR-210 implementation must wire this contract to the installed composition root from PR-206…PR-209, derive metrics from the durable event store, materialize and re-hash real qualification artifacts, execute restart/replay and chaos drills, and produce an immutable 72-hour sender-free soak bundle.
