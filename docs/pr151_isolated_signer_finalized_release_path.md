# PR-151 — Isolated signer, finalized settlement and reviewed release path

This PR starts the PR-151 release-path work as a review-safe, side-effect-free gate.
It does **not** enable live trading, signing, transaction submission, polling, resend,
or canary execution.

## Scope

The patch adds `src/pr151_isolated_release_path.py`, a pure evaluator that models the
minimum evidence required before a future reviewed canary can even be considered:

- isolated signer boundary evidence;
- durable cryptographic authorization requirements;
- finalized settlement reconciliation requirements;
- Jito canary safety requirements;
- hermetic release and production sandbox requirements;
- operator approval and ambiguity/kill-switch controls.

The evaluator always returns:

```text
runtime_live_enabled = false
supported_command_can_submit = false
```

Even when all evidence is present, the best possible state is only:

```text
ready-for-manual-release-review
```

## Safety boundary

This patch deliberately avoids:

- importing `Keypair`;
- signing;
- submitting transactions;
- polling transaction status;
- resending under ambiguity;
- opening a Jito bundle path;
- changing CLI runtime behavior;
- adding any environment variable that can enable live mode.

## Acceptance mapping

| PR-151 requirement | Gate evidence |
|---|---|
| network runtime does not receive keypair | `network_runtime_imports_keypair == false` |
| signer has no general network access | `signer_has_general_network_access == false` |
| signer parses exact v0 message itself | `parses_message_independently == true` |
| durable authorization binds policy/proof/signer | `DurableAuthorizationPolicy` hashes and durable anti-replay flags |
| finalized settlement is mandatory | `FinalizedSettlementPolicy` |
| Jito canary is one atomic transaction with one tip | `JitoCanarySafetyPolicy` |
| release is hermetic and sandboxed | `HermeticReleaseAndSandboxPolicy` |
| no single env variable enables live | `env_can_enable_live == false` |
| indeterminate outcome freezes submissions | settlement + ambiguity latch checks |

## Suggested verification

```bash
python -m pytest tests/test_pr151_isolated_release_path.py -q
python -m compileall -q src tests
```

## Deferred work

Runtime wiring, actual isolated signer backend, finalized settlement polling, Jito
submission, and reviewed live canary execution remain future work and must stay
dependent on PR-150 real sender-free soak evidence and human review.
