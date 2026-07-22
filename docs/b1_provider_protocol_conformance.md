# B1 provider/protocol conformance readiness gate

Roadmap workstream: **MEGA-PR B — Provider/protocol conformance and
reliable data plane**.

This is the first safe B1 slice. It does not perform live trading, signing,
submission, or provider promotion. It turns the existing external-contract
registry and read-only conformance machinery into a single active readiness
surface that the canonical paper vertical can consume before it accepts external
provider evidence.

## Why this exists

The production-ready workplan says the next work should wire existing contracts
into the active runtime rather than add another disconnected audit module. It
also defines MEGA-PR B as the workstream that replaces review-only documentation
snapshots and legacy adapters with promotable, bounded, credentialed and
replayable external adapters used by MEGA-PR A.

B1 therefore answers one narrow question:

> Can Jupiter, MarginFi and Jito currently feed the sender-free paper vertical?

The answer is expected to be **no** until protected credentialed conformance,
remote freshness, deployment attestation, execution conformance and promotion
evidence exist.

## Added contract

`src.external_contracts.provider_protocol_b1.evaluate_b1_provider_protocol_readiness`
produces a deterministic report for the default B1 providers:

- `jupiter`;
- `marginfi`;
- `jito`.

The report includes:

- contract ID;
- registry status;
- promotion state;
- execution permission;
- local artifact integrity;
- conformance probe state;
- required and missing credential environment variables;
- evidence blockers;
- whether the provider may feed the paper vertical.

## CLI integration

The existing `flashloan-contracts` entrypoint gains:

```bash
flashloan-contracts provider-readiness
flashloan-contracts provider-readiness --provider jupiter
flashloan-contracts provider-readiness --enable-online
flashloan-contracts provider-readiness --require-ready
```

Default mode does not require credentials and does not perform network I/O. It
returns a JSON report and exits zero for diagnostics. `--require-ready` exits
non-zero while the paper vertical is blocked.

## Safety boundary

- No live trading.
- No signer/sender path.
- No provider promotion.
- No fake success.
- No public network calls unless `--enable-online` is explicitly supplied.
- No secrets are printed by the B1 report.
- Review snapshots remain review-only and do not become execution evidence.

## Follow-up

A later MEGA-PR B implementation should wire this readiness surface to protected
credentialed probes, immutable redacted fixture generation, active admission,
drift revocation, and the MEGA-PR A paper runtime dependency factory.
