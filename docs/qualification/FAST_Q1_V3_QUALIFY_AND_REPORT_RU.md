# FAST-Q1 v3 — bounded installed qualify-and-report

This slice executes the V3 fast route without adding a second runtime.

Canonical public command:

```bash
flashloan-checks qualify-and-report inspect \
  --repo-root /clean/checkout \
  --output-root /outside/checkout/runs \
  --request-id job-001 \
  --expected-sha <exact-git-sha> \
  --profile offline_sender_free
```

Use `check` instead of `inspect` when a blocked domain verdict should return
the PR-189 blocked exit code.

## Fixed child plan

The runner invokes the installed `flashloan-bot` only with reviewed argv:

1. `status --json`
2. `capabilities --json`
3. `config doctor --json`
4. `runtime-admission --command flashloan-bot.run --mode paper --json`
5. exactly one `paper-shadow --journal-path <run>/paper-shadow.jsonl --json`
   only when all four preflights pass.

There is no shell plan, YAML command injection or model-generated argv.

## Durable outputs

Every request directory contains:

- `baseline.json`
- `run_manifest.json`
- raw `*.stdout.bin` and `*.stderr.bin`
- per-step `*.record.json`
- optional `paper-shadow.jsonl`
- `qualification_receipt.json`
- `BLOCKERS_RU.txt`

The manifest checkpoints after each step. Same request ID + same input digest
reuses and verifies the finished receipt. Changed inputs conflict. Incomplete
runs are not retried automatically.

Creating a `STOP` file inside the request directory before the next child step
causes a fail-closed cancellation.

## Meaning of success

`sender_free_pass=true` means only that this bounded diagnostic paper pass
completed under the fixed offline profile. The receipt always keeps:

- `qualified=false`
- `release_authorized=false`
- `live_authorized=false`
- `transactions_sent=0`

A `BLOCKED` result is valid evidence and should drive the next single blocker,
not be rewritten into PASS.

## Reuse

This current-main implementation supersedes the old draft concepts in #545 and
#547: it reuses #547's receipt/idempotency discipline and #545's conditional
paper-shadow idea, while keeping the canonical PR-189 `flashloan-checks`
authority.
