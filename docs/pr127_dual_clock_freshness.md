# PR-127 — Dual-clock freshness, provider-native expiry and provenance contract

PR-127 introduces a side-effect-free boundary for time, slot, and quote-freshness decisions. It does not call NTP, RPC, providers, wallets, senders, Jito, or databases.

## Why this exists

Wall-clock timestamps are useful for audit display, but they are unsafe for runtime TTL, request deadlines, cooldowns, and in-process leases. A backward wall-clock jump must not make an old quote fresh again. A forward wall-clock jump must not skip a cooldown or expire a lease early.

## Added boundary

`src/freshness/dual_clock.py` adds:

- `PR127ClockReading`: monotonic nanoseconds, UTC audit timestamp, optional chain slot and block height.
- `PR127ReplayClock`: deterministic replay source for tests and corpus replay.
- `PR127Deadline`: monotonic request/retry/build/simulation deadline.
- `PR127Cooldown`: monotonic cooldown.
- `PR127Lease`: monotonic in-process lease.
- `PR127CycleBudget`: explicit first-leg, exact-second-leg, final-build, compile/simulation, and retry-overhead budget.
- `PR127QuoteFreshnessEvidence`: provider-native expiry when available, otherwise a bounded local max age with required source/reason.
- `PR127SlotPolicy`: provider/candidate-specific cross-slot and block-height drift policy.
- `evaluate_pr127_quote_freshness(...)`: fail-closed freshness evaluation.
- `diagnose_pr127_clock_skew(...)`: NTP/wall-vs-monotonic diagnostic.

## Safety rules

1. Runtime validity uses monotonic time only.
2. UTC is retained for audit display and provenance, not for extending TTL.
3. `expires_at=None` is not a valid freshness state.
4. Provider-native expiry is represented explicitly.
5. If a provider has no native expiry, the adapter must provide a conservative local max-age and source reason.
6. Quote evidence keeps requested-at monotonic, received-at monotonic+UTC, provider timestamp, context slot, and block height when available.
7. Cross-slot behavior is explicit per provider/candidate.
8. Replay tests use deterministic clock readings, including wall-clock jumps.

## Suggested verification

```bash
python -m pytest tests/test_pr127_dual_clock_freshness.py -q
python -m black --check src/freshness/__init__.py src/freshness/dual_clock.py tests/test_pr127_dual_clock_freshness.py
python scripts/verify_repo.py --skip-dependency-audit
```

## Non-goals

This PR does not wire provider adapters, route execution, sender lifecycle, live mode, MarginFi/Kamino state, RPC transport, Jito transport, or paper composition. Those layers can consume this boundary in later integration PRs.
