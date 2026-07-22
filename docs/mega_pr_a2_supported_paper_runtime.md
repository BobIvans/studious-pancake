# MEGA-PR A2 — Supported sender-free paper runtime

This PR continues MEGA-PR A2 after the merged exact-attempt runtime bridge.

The uploaded workplan says A2 must complete the supported sender-free paper runtime: the installed CLI should repeatedly execute the merged exact-attempt vertical from captured, reviewed evidence, keep network-live and sender modes unavailable, use one SQLite lifecycle/outbox authority, and make JSONL diagnostic only rather than authoritative state.

## What this PR wires

This PR adds a recorded-evidence profile to the supported CLI path:

```bash
flashloan-bot run \
  --mode paper \
  --paper-profile recorded-evidence \
  --recorded-evidence-manifest fixtures/paper/a2-recorded-evidence.json \
  --paper-runtime-db .runtime/supported-paper-runtime.sqlite \
  --max-paper-cycles 10 \
  --json
```

The default paper mode remains fail-closed and unchanged:

```bash
flashloan-bot run --mode paper
```

## New active runtime surface

`src/paper_shadow/a2_supported_paper_runtime.py` introduces:

- a reviewed recorded-evidence manifest;
- strict report-hash verification for `ExactAttemptRuntimeReport` payloads;
- live/sender/signer/submission rejection;
- one SQLite authority for `paper_cycles`, `paper_cycle_records` and `paper_outbox`;
- idempotent replay of the same cycle/report;
- failure on the same `cycle_id` with different report hash;
- batch stopping when a cycle is not ready for the next cycle;
- machine-readable `SupportedPaperRuntimeSummary`.

## Why this is still sender-free

This PR does **not**:

- import private-key material;
- sign;
- submit transactions;
- call Jito/RPC/Jupiter/Helius/MarginFi providers;
- poll settlement;
- enable live/canary mode;
- treat JSONL as authoritative lifecycle state.

The recorded-evidence profile is a deterministic replay/persistence boundary for captured exact-attempt runtime reports. It is the supported runtime seam that later B2/provider work can feed with real protected fixtures and that later D2 soak/release work can execute from an installed wheel.

## Safety invariants

```text
live_enabled = false
sender_reachable = false
signer_reachable = false
jsonl_authoritative = false
```

## Verification

```bash
python -m pytest tests/test_a2_supported_paper_runtime.py -q
python -m compileall -q src tests
```

## Remaining A2 work

This does not claim full paper readiness yet. Follow-up A2/B2/D2 work must still:

- generate reviewed captured provider/RPC/MarginFi/Jupiter evidence;
- build the exact-attempt manifest from active producer commands;
- prove installed-wheel/source parity for this runtime path;
- run restart/crash injection at every durable boundary;
- prove reservations are released or preserved correctly under every terminal path;
- remove or demote JSONL from any remaining authoritative lifecycle role.
