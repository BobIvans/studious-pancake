# PR-143 — Atomic policy/config governance and privacy-safe evidence envelopes

This PR adds an additive, side-effect-free governance primitive for the third
deep-audit PR-143 scope.

## Scope

The third deep audit defines PR-143 as the policy/evidence identity layer:

- one immutable `PolicyBundle`;
- no hot direct environment reads for behavior decisions after startup;
- attempt-level binding to the exact policy hash;
- canonical encoding instead of ad-hoc JSON hashing;
- domain-separated evidence envelopes;
- big-integer and money-safe encoding;
- atomic config activation;
- rollout/governance states;
- privacy-safe typed diagnostics;
- central data classification/redaction;
- exception-safety and evidence-retention controls.

## What this patch adds

- `src/policy_governance_pr143.py`
  - `PolicyBundle` requiring complete policy component references;
  - `EvidenceEnvelope` with domain, schema version, cluster genesis and payload;
  - canonical JSON subset helper that rejects binary floats and encodes huge
    integers as tagged decimal strings;
  - duplicate-key rejecting JSON parser;
  - `HashRef` domain checking to prevent cross-domain SHA substitution;
  - `fingerprint_secret_locator(...)` that changes when `env:KEY_A` becomes
    `env:KEY_B`, without hashing or logging secret values;
  - `AttemptPolicySnapshot` and `validate_attempt_policy(...)`;
  - `TypedDiagnostic` and `safe_diagnostic_from_exception(...)`;
  - central classification/redaction helpers;
  - static guards for hot `os.getenv` decisions and raw `str(exc)` persistence;
  - `GovernanceRecord` and `AtomicPolicyActivator` for activation/rollback.

- `tests/test_pr143_policy_governance.py`
  - complete PolicyBundle requirement;
  - secret locator fingerprint collision prevention;
  - cross-domain hash substitution rejection;
  - attempt policy binding and policy-change invalidation;
  - huge integer canonicalization and float rejection;
  - duplicate JSON key rejection;
  - nested secret/URL/Bearer redaction;
  - safe diagnostics without raw exception text;
  - static guards for hot env and raw exception persistence;
  - governance approval/dual-approval and rollback tests.

## Safety / non-goals

- No live trading.
- No paper/live execution enablement.
- No signer or sender path.
- No private key handling.
- No RPC/Jito/Helius/MarginFi/Jupiter network call.
- No active runtime rewiring in this slice.
- No attempt to replace every existing hash call in one PR while parallel work is
  still changing main.

## Follow-up integration

Later integration can route `RuntimeConfig`, provider policy, attempt creation,
simulation reports, permits, release manifests and durable evidence through this
module. This first slice provides the common contract and regression tests.
