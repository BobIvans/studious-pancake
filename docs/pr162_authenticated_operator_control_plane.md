# PR-162 — Authenticated operator control plane and separation of duties

This PR starts the PR-162 work as a review-safe, side-effect-free control-plane
gate. It does **not** enable live trading, privileged recovery, signing,
submission, provider calls, RPC calls, GitHub API calls, or runtime CLI mutation.

## Scope

The patch adds `src/pr162_operator_control_plane.py`, a pure evaluator for the
minimum evidence required before production operator actions can be trusted:

- authenticated principal evidence, not caller-supplied `OperatorIdentity` text;
- RBAC role bindings and explicit permissions;
- multi-party separation of duties for request, review, approval and final arm;
- cryptographic approvals bound to request/policy/release/scope hashes;
- durable approval lifecycle evidence that survives restart;
- break-glass governance that cannot disable message verification, wallet reserve,
  ambiguity latch, or finalized settlement;
- protected deployment-environment evidence.

The evaluator always returns:

```text
runtime_live_enabled = false
supported_command_can_mutate = false
```

Even with complete evidence, the best possible state is only:

```text
ready-for-manual-control-plane-review
```

## Safety boundary

This patch intentionally avoids:

- changing `src/live_canary/controller.py`;
- changing `src/live_canary/models.py`;
- changing trading economics;
- changing signer/recovery code;
- changing CLI behavior;
- creating environment variables that can enable live;
- trusting plain operator strings as production human identity.

## Acceptance mapping

| PR-162 requirement | Gate evidence |
|---|---|
| Arbitrary string cannot become production human principal | `AuthenticatedPrincipal` requires production authentication method |
| Every privileged action has explicit permission | `OperatorPermission` + role mapping |
| Request/review/arm are separate identities | `SeparationOfDutiesPolicy` |
| Approval is cryptographically bound | `CryptographicApproval` hashes + signature + chain |
| Expired/revoked principal cannot approve | `valid_at()` checks |
| Restart cannot fabricate approvals | `DurableApprovalLifecycle` evidence |
| Protected environment prevents self-review | `ProtectedDeploymentEnvironment` |
| Break-glass pages and audits | `BreakGlassGovernance` |
| No single env variable enables live | package-level hard blockers |
| Audit can reconstruct actors | package hash + durable lifecycle + principals/approvals |

## Suggested verification

```bash
python -m pytest tests/test_pr162_operator_control_plane.py -q
python -m compileall -q src tests
```

## Deferred work

Runtime wiring into the canary controller, actual OIDC/mTLS/WebAuthn/GPG/Sigstore
verification, GitHub protected-environment API collection, durable database
persistence, and break-glass alert delivery are follow-up work. This PR only adds
the fail-closed contract and tests for the evidence shape.
