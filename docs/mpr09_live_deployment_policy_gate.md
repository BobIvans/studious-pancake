# MPR-09 live configuration, credential lifecycle and deployment sandbox gate

This document describes the first additive slice for **MPR-09 — Live configuration, credential lifecycle and enforceable deployment sandbox**.

The V6 post-MPR audit assigns MPR-09 to findings **F-281...F-296**. The target is not to enable live trading. The target is to make unsafe live/deployment evidence impossible to mark ready until the installed artifact can prove rooted configuration authority, durable credential lifecycle and an enforceable sandbox.

## Scope

This PR adds an offline deterministic evidence evaluator:

- `src/mpr09_live_deployment_policy_gate.py`
- `tests/test_mpr09_live_deployment_policy_gate.py`

No workflow is added in this slice. The V6 audit identifies completion/release truth and workflow hardening as MPR-08 territory, so this PR avoids increasing the mutable Actions surface before that package is complete.

## Covered findings

The gate turns these MPR-09 findings into stable blockers:

- F-281: live authority cannot use `processed` or `confirmed` as the authoritative commitment.
- F-282: production/live RPC transports must be TLS-only, `https://` and `wss://`.
- F-283: unknown clusters are rejected; production evidence is scoped to the signed registry identity.
- F-284: protocol program IDs cannot self-authorize through runtime config.
- F-285/F-290: credential generations must be content/version-bound and change on rotation.
- F-286: production secret-file roots cannot be fail-open.
- F-287: revocation and active credential generation must be durable and cross-process.
- F-288: leases must bind monotonic elapsed time, trusted UTC and boot/generation identity.
- F-289: secret consumption must be serialized and must not expose reusable raw strings.
- F-291: mounted Docker secrets must be consumed by the application through the supported schema.
- F-292: typed runtime mode must be configured; legacy boolean flags cannot be the deployment authority.
- F-293: egress claims require measured topology enforcement and denied-destination probes.
- F-294: canonical state must live on persistent volumes with non-root write/restart proof.
- F-295: the sandbox profile must be loaded and attested by hash.
- F-296: readiness must measure workload/durable-state readiness, not only management liveness.

## Safety boundary

This PR does not:

- enable live trading;
- read private keys or secret values;
- construct, sign, simulate or submit transactions;
- call Solana RPC, Jupiter, Jito, Helius, MarginFi or Kamino;
- inspect Docker, AppArmor or host networking;
- migrate production configuration or deployment files.

A ready report still emits:

```text
live_execution_allowed=false
signer_access_allowed=false
provider_network_allowed=false
```

## Evidence model

The evaluator accepts already-materialized evidence objects for three boundaries:

1. `LiveRuntimeConfigEvidence` — authoritative commitment, TLS endpoints, cluster identity and signed protocol registry identity.
2. `CredentialLifecycleEvidence` — content-bound secret generations, durable revocation, safe leases, serialized consumption and fail-closed file roots.
3. `DeploymentSandboxEvidence` — typed secret/config mount, egress enforcement, durable volume proof, AppArmor profile attestation and readiness separation.

The top-level envelope also requires `mpr08_completion_ledger_accepted=true`, because the audit says MPR-09 starts after MPR-08 freezes completion/config/release identity.

## Focused verification

The focused tests cover the complete ready path and fail-closed probes for:

- missing MPR-08 ledger;
- processed live authority;
- HTTP/WS RPC;
- unknown cluster and self-authorized MarginFi program;
- rotation/revocation/root-policy failures;
- unsafe lease and max-use consumption;
- missing mounted-secret consumption and typed runtime mode;
- unenforced egress and non-durable volumes;
- missing AppArmor/readiness attestation;
- reachable live/signer/provider surface;
- placeholder digests and malformed RPC URLs.

Local preparation before opening the PR:

```bash
PYTHONPATH=. python -m py_compile \
  src/mpr09_live_deployment_policy_gate.py \
  tests/test_mpr09_live_deployment_policy_gate.py
PYTHONPATH=. python -m pytest -q tests/test_mpr09_live_deployment_policy_gate.py
# 13 passed
```

## Remaining full MPR-09 work

This is not the complete MPR-09 implementation. Later slices should wire measured collectors into the installed artifact after MPR-08, replace unsafe live configuration paths, persist credential generation/revocation state, implement the production secret mount contract, enforce egress at the running-container boundary, ship and attest the AppArmor profile, and change deployment healthchecks to readiness-aware checks.
