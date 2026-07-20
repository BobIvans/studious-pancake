# PR-051 — AI decision intelligence: advisory-only evidence hardening

PR-051 makes the existing offline decision-intelligence package safer and more auditable without changing the live or paper trading safety envelope.

## Boundary

AI/ML output is advisory-only. It may produce a shadow score, a band, and short reasons, but deterministic policy remains authoritative for:

- sizing;
- minimum profit;
- allowlists;
- permits;
- senders;
- kill switches;
- live policy schema;
- candidate acceptance after deterministic rejection.

The bot must remain fully operable without AI. If an artifact is missing, disabled, corrupted, or not explicitly enabled by offline configuration, recommendation falls back to deterministic baseline.

## Added components

### `src.decision.advisory`

`apply_advisory_guard(...)` wraps a deterministic candidate decision plus a `RankingRecommendation`. The output envelope preserves `final_allowed = deterministic_allowed`.

A `PRIORITIZE` advisory band for a rejected candidate is logged as ignored evidence through `AI_PRIORITIZE_IGNORED_FOR_REJECTED_CANDIDATE`; it cannot unlock the candidate.

`assert_no_ai_control_surface(...)` rejects advisory payloads that reference forbidden control surfaces such as `min_profit`, `permit`, `sender`, `kill_switch`, `live_policy`, or sizing fields.

### `src.decision.model_registry`

The model registry is an offline manifest of already-created model artifacts. It verifies:

- artifact checksum through `load_artifact(...)`;
- artifact version;
- feature spec version;
- model status enum;
- no embedded live policy or permit fields.

The registry records dataset and evaluation hashes when present and explicitly sets:

```json
{"live_policy_schema_changed": false, "runtime_promotion_allowed": false}
```

### `src.decision.shadow_ab`

The shadow A/B report compares deterministic baseline decisions to advisory model recommendations. It records:

- model failure fallback count;
- ignored `PRIORITIZE` attempts on rejected candidates;
- advisory disagreements;
- `rejected_candidates_unlocked_by_ai = 0`;
- automatic disable reasons.

The report is reproducibly hashed and written as `shadow_ab_report.json`.

### Dataset secret policy

`DecisionDatasetBuilder` now rejects events containing wallet, API, signing, mnemonic, private-key, or credential-shaped fields/values before those events are hashed or written to `rows.jsonl`.

This keeps prompts, datasets, manifests, and model artifacts free of user wallet/API secrets.

## Acceptance mapping

- Bot works without AI: model disabled/missing artifact returns deterministic baseline.
- Model failure falls back to deterministic baseline: covered by shadow A/B report.
- AI output cannot unlock rejected candidates: enforced by advisory envelope.
- Provenance and evaluation report hashes: supported by model registry and report hashes.
- Enabling AI does not change live policy schema: registry and report explicitly assert false.
- No secrets in prompts/datasets: dataset builder rejects secret-shaped raw events before persistence.

## Focused tests

```bash
python -m pytest tests/test_pr051_ai_advisory_evidence.py -q
```

Full repository verification remains:

```bash
python scripts/verify_repo.py
```

## Non-goals

PR-051 does not add an online LLM call, external model API, new provider credential, paper execution promotion, live sender integration, or any automatic trade permission. The model remains a shadow challenger only.
