# PR-127 — Dual-clock freshness and provider-native expiry contract

This PR adds a side-effect-free timing/freshness boundary. It does not call RPC,
providers, NTP, Jito, signers, senders, or live submission paths.

## Scope covered

- Dual-clock snapshot:
  - monotonic nanoseconds for validity and deadlines;
  - UTC wall clock for audit display only;
  - optional chain slot and block-height evidence.
- Quote provenance:
  - requested-at monotonic evidence;
  - received-at monotonic + UTC evidence;
  - provider timestamp;
  - context slot and block height;
  - optional provider-native expiry translated onto the monotonic timeline.
- Freshness policy:
  - provider-native expiry wins when available;
  - otherwise an explicit conservative local max-age with source/reason is required;
  - `expires_at=None` never means unbounded freshness.
- Monotonic-only cycle deadlines and leases/cooldowns.
- NTP/clock-skew diagnostic is advisory and cannot extend quote validity.
- Replay determinism: evaluation depends only on explicit captured inputs.

## Non-goals

- No provider adapter wiring.
- No route-discovery behavior changes.
- No runtime sender, RPC, Jito, MarginFi, Jupiter, or paper/live changes.
- No sleeps, process-clock reads, wall-clock validity checks, or background tasks.

## Suggested verification

```bash
python -m pytest tests/test_pr127_dual_clock_freshness.py -q
python -m black --check src/freshness/__init__.py src/freshness/clock.py tests/test_pr127_dual_clock_freshness.py
python scripts/verify_repo.py --skip-dependency-audit
```

## Acceptance mapping

| Requirement | Evidence |
|---|---|
| Wall-clock change cannot extend quote validity | `test_pr127_wall_clock_jump_cannot_extend_local_quote_validity` |
| Wall-clock change does not alter monotonic freshness | `test_pr127_wall_clock_jump_cannot_change_freshness_result` |
| Provider-native expiry is respected | `test_pr127_provider_native_expiry_overrides_long_local_max_age` |
| `expires_at=None` is never unbounded | `test_pr127_expires_at_none_never_means_unbounded_freshness` |
| Context slot / block height policy exists | `test_pr127_cross_slot_and_block_height_policies_fail_closed` |
| Cooldowns/leases are monotonic-only | `test_pr127_monotonic_lease_ignores_wall_clock_jumps` |
| Replay determinism | `test_pr127_replay_determinism_uses_explicit_clock_inputs` |
