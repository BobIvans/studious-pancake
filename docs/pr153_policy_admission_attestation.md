# PR-153 — Unified immutable policy, provider admission and attestation gate

This PR starts the PR-153 work as a review-safe policy/admission contract. It does
not connect to live trading, transaction construction, signing, provider calls, RPC,
or runtime CLI enablement.

## Scope

The patch adds `src/pr153_policy_admission.py`, a side-effect-free evaluator for one
immutable policy bundle. It models the minimum conditions required before a provider
can be admitted with the `executable` role:

- active local contract;
- `contract_execution_allowed = true`;
- no contract drift;
- required credentials present;
- credentialed API conformance;
- execution composition conformance;
- promotion evidence;
- operator approval;
- verified on-chain program attestations.

Any missing condition forces the provider to `disabled` when the requested role is
`executable`.

## Safety boundary

This patch deliberately avoids:

- provider/RPC calls;
- route discovery;
- transaction build/simulation;
- signer or `Keypair` imports;
- sender or Jito submission;
- CLI/runtime readiness changes;
- environment-variable live enablement.

The evaluator always returns:

```text
runtime_live_enabled = false
supported_command_can_submit = false
```

Even a fully verified bundle can only become:

```text
ready-for-policy-review
```

## Acceptance mapping

| PR-153 requirement | Gate evidence |
|---|---|
| no false provider promotion | `assert_no_false_provider_promotion(...)` |
| execution role requires local active contract | `local_contract_active` |
| execution role requires allowed contract | `contract_execution_allowed` |
| execution role requires no drift | `drift_free` |
| execution role requires credentials | `credentials_present` + `missing_credentials` |
| execution role requires conformance | credentialed API + execution composition booleans |
| execution role requires promotion evidence | `promotion_evidence` |
| execution role requires approval | `operator_approved` |
| execution role requires attestation | `ProgramAttestation.verified` |
| live remains unavailable | result live/submission flags are always false |

## Suggested verification

```bash
python -m pytest tests/test_pr153_policy_admission.py -q
python -m compileall -q src tests
```

## Deferred work

Runtime wiring into `ProviderRegistry`, CLI status, readiness surfaces, scheduled drift
probes, and real on-chain attestation fetching remain future integration work. This PR
only provides the immutable admission contract and regression tests for the forbidden
states.
