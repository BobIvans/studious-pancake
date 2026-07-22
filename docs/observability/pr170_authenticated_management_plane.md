# PR-170 authenticated management plane and truthful readiness

PR-170 starts the management-plane hardening programme described in the
snapshot-9 continuation audit. The first production-safe slice is deliberately
offline and side-effect-free: it defines the admission, authentication,
ingress-limit and signed-state contracts that the existing health server can be
migrated to without enabling trading.

## Debt addressed

The current runtime health path uses stdlib `http.server` and exposes
`/health`, `/ready`, `/status` and `/metrics` from one listener. The container
runtime also writes an unsigned JSON state file in `/tmp`. The PR-170 policy
makes the following rules machine-testable:

- non-loopback bind is denied unless an authenticated proxy/service identity is
  present;
- operator status, readiness and metrics require bearer-token identity when
  configured;
- public liveness is topology-minimal and does not reveal pid, wallet, provider,
  program or route information;
- admin mutation is disabled by default;
- fallback runtime state is owner-only `0600`, regular-file only, MACed,
  generation-fenced and policy-bundle-bound;
- stale generation, tampering, wrong policy bundle and open file mode fail
  closed;
- ingress limits are explicit and reviewable.

## Non-goals

- No live trading.
- No signer, sender or wallet access.
- No network listener replacement in this first slice.
- No mutation/admin API enablement.
- No claim that PR-170 is fully complete.

The next PR-170 integration slice should wire this policy into the runtime
listener, replace the raw stdlib server for production deployments, and separate
liveness/readiness/metrics/operator/admin surfaces at the process or service-mesh
boundary.
