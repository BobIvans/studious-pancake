# PR-353 schema and config migration notes

- New config: `config/strategy_evolution.json`.
- New research namespace: `src/strategy_evolution`.
- No existing canonical schema is replaced or rewritten.
- No database/table migration is introduced.
- Forward reader rule: unknown EVO package fields are ignored by pre-existing
  components because they do not consume this new file.
- Backward reader rule: absence of the PR-353 config means all EVO packages are
  unavailable/disabled.
- Downgrade: detach adapters, remove the additive config/module paths, preserve
  evidence and coverage documents.
