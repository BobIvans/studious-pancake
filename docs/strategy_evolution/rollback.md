# PR-353 rollback

Rollback is config-first. All nine packages are checked in `DISABLED`, so detach
research-candidate adapters and stop optional reads through existing provider
controls while preserving append-only evidence, coverage records and tombstones.

A code revert is secondary and must not delete historical evidence. PR-353 adds
no live operation requiring settlement recovery and no writer migration to
canonical stores.

The additive `pr353.strategy-evolution.config.v1` schema has a downgrade path:
remove/ignore `config/strategy_evolution.json` and `src/strategy_evolution`;
pre-PR-353 readers and canonical owners continue unchanged.
