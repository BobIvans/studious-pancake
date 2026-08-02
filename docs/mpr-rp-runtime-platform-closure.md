# MPR-RP — Runtime and platform residual closure in four workstreams

This change compresses audit PR-053 through PR-057 into four review authorities
without reassigning earlier PR ownership.

## MPR-RP-01 — Qualified platform and command dependency admission

Aggregates PR-053 and PR-057. It adds an authoritative supported-platform policy,
canonical platform/native-distribution identity, deterministic native known-answer
probes, command-specific dependency manifests, typed dependency blockers and the
`flashloan-bot runtime-admission` evidence surface. Inspection remains dependency
light; a missing safety authority disables the affected runtime path instead of
activating a weaker placeholder.

Repository completion does not claim that external x86_64/aarch64 qualification
has already occurred. The policy and evidence surfaces are now executable, while
production admission still requires materialized runner evidence for every listed
architecture and native wheel set.

## MPR-RP-02 — Immutable bootstrap and reversible process ownership

Aggregates PR-054. `BootstrapContext` captures argv, absolute working root,
selected environment bindings, release/config/policy generations, platform
identity and invocation correlation exactly once. Legacy paper arguments become
typed invocation-local overrides rather than writes to `os.environ`. CLI logging
and signal handlers are owned and restored, and active path resolution consumes
the immutable root.

## MPR-RP-03 — Instance-scoped local resource ownership

Aggregates PR-055. `RuntimeInstanceIdentity`, `LocalResourceManifest` and
`LocalResourceLease` bind state, companion keys, runtime roots, temp paths and
management endpoints to environment/release/deployment/instance/generation.
Acquisition is transactional, collisions become typed startup blockers, and
cleanup is inode/token-bound so an old generation cannot delete a replacement.

This authority composes with durable database writer fencing and does not replace
distributed leader election.

## MPR-RP-04 — External desired-state convergence

Aggregates PR-056. The installed `flashloan-external-resources` command provides
plan, apply, status and reconcile surfaces. A sealed plan binds desired state to a
complete remote inventory fingerprint; apply persists mutation intent before the
remote side effect, performs independent readback, records terminal evidence and
supports idempotent replay. Ambiguous adoption, duplicates, incomplete discovery
and concurrent inventory drift block mutation. Legacy source scripts no longer
perform direct network mutations.

## Verification

- `scripts/verify_mpr_rp_runtime_platform_closure.py`
- `tests/runtime/test_mpr_rp01_platform_dependency_admission.py`
- `tests/runtime/test_mpr_rp02_bootstrap_reentrancy.py`
- `tests/runtime/test_mpr_rp03_instance_resources.py`
- `tests/external_resources/test_mpr_rp04_desired_state.py`
- `tests/runtime/test_mpr_rp_closure_gate.py`

Live execution, signer loading and sender transports remain disabled by the
existing product contract.
