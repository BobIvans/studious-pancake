# MEGA-PR-01 — canonical sender-free paper platform

This checkpoint replaces the default blocked paper dependency seam with one
installed, bounded, sender-free composition root.

## Runtime contract

`flashloan-bot run --mode paper` is intercepted by the installed CLI and runs
`src.canonical_paper.cli`. The root `arb_bot.py` wrapper delegates to the same
installed CLI target. The canonical platform:

1. loads a bounded recorded provider/economic batch;
2. verifies exact compiled-message/simulation hash equality;
3. verifies integer-exact flash repayment;
4. checks rooted slot coherence;
5. applies conservative fees, rent, tip and safety buffer;
6. commits one terminal cycle and per-candidate decisions to SQLite under WAL +
   `synchronous=FULL`;
7. reads the report back and verifies its content hash.

The package ships one deterministic recorded fixture so a clean installed wheel
can execute a positive `paper_accepted` cycle without network access. A custom
recording can be supplied for integration and regression runs.

## Commands

```bash
flashloan-bot run --mode paper --json
python arb_bot.py run --mode paper --json
flashloan-bot run --mode paper \
  --recording /path/to/recorded.json \
  --db-path /var/lib/flashloan-bot/canonical-paper.sqlite3 \
  --json
```

## Safety boundary

This checkpoint does not import or enable a wallet, private-key loader, signer,
sender, RPC/Jito submission or live execution path. The report structurally
requires `live_enabled=false`, `signer_loaded=false`, and `sender_loaded=false`.

## Remaining MEGA-PR-01 work

This is a material implementation checkpoint, not the full roadmap completion.
The remaining merge blockers include replacing the recorded source with admitted
rooted provider adapters, converging all lifecycle/projection stores on the same
system of record, deleting unreachable legacy/proof-island modules from the
wheel, container readiness wiring, crash/restore drills, capital reservation and
full clean-wheel/container qualification.
