# PR-171 — Chain-time, commitment, slot and fork-consistency contract

This PR starts the PR-171 work as a review-safe, side-effect-free contract layer.
It does **not** change trading logic, RPC clients, transaction simulation, fee
queries, cache writers, accounting, settlement, CLI commands, or live/canary
behaviour.

## Scope

The patch adds `src/pr171_chain_context.py`, a pure evaluator/model package for:

- stage-specific commitment requirements;
- unified `ChainContext` evidence;
- explicit context slot / `minContextSlot` requirements;
- no slot invention from unrelated blockhash provenance;
- coherent pre-state / simulation / fee / blockhash-ALT evidence;
- strict account response cardinality;
- commitment-aware cache keys;
- root/fork invalidation reasons;
- finalized accounting/settlement requirements.

The evaluator always returns:

```text
runtime_live_enabled = false
```

## Safety boundary

This patch deliberately avoids:

- calling Solana RPC;
- changing `TransactionSimulator`;
- changing `getFeeForMessage` code;
- changing provider clients;
- changing cache writers;
- constructing transactions;
- signing or submitting transactions;
- changing accounting/settlement code;
- enabling live or canary execution.

## Acceptance mapping

| PR-171 requirement | Gate evidence |
|---|---|
| no implicit commitment | `require_no_implicit_commitment(...)` |
| stage-specific commitment | `default_stage_policy()` |
| unified chain context | `ChainContext` |
| no slot fallback | `require_simulation_context_slot(...)` |
| coherent pre/post simulation | `evaluate_simulation_bundle(...)` |
| strict account cardinality | `AccountSetEvidence` |
| no cache contamination | `build_cache_key(...)` includes commitment/root/fork/minContextSlot |
| reorg/root invalidation | `reorg_invalidation_reasons(...)` |
| processed cannot be finalized accounting | `evaluate_finalized_accounting_context(...)` |

## Suggested verification

```bash
python -m pytest tests/test_pr171_chain_context.py -q
python -m compileall -q src tests
```

## Deferred work

Runtime integration into the simulator, fee lookup, pre-state account reader,
blockhash/ALT fetcher, cache, replay, accounting and settlement paths remains future
work. Those follow-up changes should consume this contract but must continue to keep
live execution disabled until the full PR-152…173 readiness chain is reviewed.
