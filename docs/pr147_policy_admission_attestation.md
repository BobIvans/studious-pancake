# PR-147 — Unified immutable policy, provider admission and on-chain attestation graph

This PR implements the first low-conflict slice of the snapshot `(9)` PR-147
roadmap: one immutable policy/admission truth and no runtime promotion to
`EXECUTABLE` without decisive evidence.

## Implemented slice

- Adds `src/policy_admission_pr147.py`.
- Defines `ImmutablePolicyBundle`, binding runtime config, secret locator identity,
  provider contracts, credential availability, program attestations, asset/mint
  registry, freshness policy, build/release identity and operator approval.
- Defines `ProgramAttestation` and `MintAttestation` for current deployment/mint
  truth.
- Defines `ProviderPolicyEvidence` and `ProviderAdmissionDecision`.
- Requires execution admission to have:
  - active local contract;
  - no drift;
  - credentials present;
  - `contract_execution_allowed=true`;
  - credentialed API conformance;
  - execution composition conformance;
  - promotion evidence;
  - current policy approval;
  - fresh evidence;
  - required on-chain program attestation.
- Adds domain-separated hashes for policy bundles, provider evidence and admission
  decisions.
- Adds `PolicyRuntimeTruth` so architecture tests can reject impossible states.
- Adds focused tests for the current Jupiter-style blocked state without changing
  active provider/routing behavior in this slice.

## Why this is fail-closed

The roadmap requires that runtime execution role cannot be promoted from a local
capability flag alone. This slice creates the reusable admission contract that
fails closed unless every required proof bit is present. A later integration PR
can wire this contract into `ProviderRegistry`, CLI status, capabilities,
readiness and release gates without mixing that behavior change into this first
reviewable policy primitive.

## Safety / non-goals

- No active ProviderRegistry behavior change in this slice.
- No DEX route planning changes.
- No transaction simulation changes.
- No signing.
- No live sender.
- No provider/RPC/Jito/MarginFi/Jupiter network calls.
- No paper execution enablement.
- No automatic credential probing in this slice.

## Follow-up required for full PR-147

Later PR-147 work should wire this policy bundle into active ProviderRegistry,
CLI status, capabilities, readiness, release gates, provider request behavior and
drift jobs. It should also replace any remaining direct runtime provider truth
planes with this single policy/admission identity.
