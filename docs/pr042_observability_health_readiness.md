# PR-042 — Observability, health/readiness, SLO and runbooks

PR-042 adds the first operator-facing health surface for the fail-closed
runtime. It does **not** enable paper, shadow execution, signing, bundle
submission or live trading.

## Boundary

The runtime now exposes local, standard-library-only HTTP endpoints:

- `GET /health` — process liveness only;
- `GET /ready` — dependency-aware readiness;
- `GET /status` — redacted operator status;
- `GET /metrics` — minimal Prometheus-compatible gauges.

The container healthcheck uses the same `/health` endpoint that operators can
inspect. `/ready` is intentionally stricter and remains false while the runtime
is safe-idle or while a critical dependency is unavailable.

## Dependency states

Dependency rows use the PR-042 state taxonomy:

- `ok`;
- `degraded`;
- `disabled`;
- `unavailable`;
- `unknown`.

A critical dependency in any state other than `ok` blocks readiness. The
safe-idle container declares the execution pipeline and RPC dependency as
critical but disabled/unavailable because no detector, planner, RPC, simulator,
signer or sender is active.

## Sensitive-field policy

All JSON responses are sanitized through the existing PR-017 redactor before
they are returned. Secret-looking keys and values, wallet material, signed
transactions, bearer tokens and private paths are redacted or digested.

The status payload also carries explicit safety facts:

```json
{
  "live_enabled": false,
  "submitted": false,
  "signing_enabled": false,
  "material_redaction": "enabled"
}
```

## Docker behavior

The runtime image keeps the same non-root user and fail-closed command:

```bash
flashloan-bot container
```

The Docker healthcheck is now:

```bash
flashloan-bot-healthcheck --url http://127.0.0.1:8080/health
```

This checks local process health only. It must not be interpreted as market,
paper, shadow or live readiness.

## Readiness examples

Healthy process but not ready:

```json
{
  "ok": false,
  "status": "not_ready",
  "reasons": [
    "execution_pipeline:disabled:safe idle: detector, route planner, final simulation, signing and submission are not active"
  ]
}
```

This is expected before the complete paper/shadow pipeline and durable recovery
layers are connected.

## Initial SLO signals

`/metrics` exposes:

- `flashloan_health_status`;
- `flashloan_readiness_status`;
- `flashloan_dependency_status{dependency,kind,state}`.

Later PRs can add provider quota histograms, simulation latency, route counts,
reconciliation classifications and alert exporters without changing the PR-042
endpoint contract.

## Runbook drills

### Quota exhausted

1. Confirm `/ready` has a provider/quota dependency blocker.
2. Confirm `/health` remains healthy.
3. Keep live disabled and reduce quote pressure.
4. Resume only after the dependency row returns to `ok`.

### RPC stale

1. `/ready` must be false with an RPC stale/unavailable reason.
2. Do not promote candidates from stale slots.
3. Rotate or repair RPC outside the process.
4. Require a fresh readiness row before paper/live promotion.

### Reconciliation indeterminate

1. Treat indeterminate reconciliation as a readiness blocker.
2. Do not retry blindly.
3. Preserve the trace/candidate/message IDs for replay.
4. Clear the blocker only after durable evidence is classified.

### Low SOL reserve

1. Confirm capital/reserve dependency is blocking readiness.
2. Do not lower protected reserve through an emergency shortcut.
3. Refill wallet or lower attempt size through reviewed policy.
4. Require `/ready` to become `ok` before new candidates are admitted.

### Jito ambiguous

1. Treat ambiguous bundle status as a readiness blocker.
2. Do not submit a replacement until durable lifecycle recovery resolves it.
3. Preserve bundle/message IDs in redacted logs and evidence.
4. Resume only after ambiguity is reconciled.

## Non-goals

- no RPC calls from the health server;
- no provider polling;
- no automatic alert delivery;
- no live permit or sender changes;
- no promotion from `/health`;
- no secret exposure in logs or status responses.
