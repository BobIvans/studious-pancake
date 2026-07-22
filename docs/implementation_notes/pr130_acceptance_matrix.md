# PR-130 acceptance matrix

| Requirement | Implementation | Test |
|---|---|---|
| Exactly one strategy transaction for first production Jito path | `JitoMevProtectionPolicy.allow_multi_transaction_bundle=False`; canonical live `JITO_BUNDLE` is blocked | `test_pr130_first_production_jito_single_shape_is_ready`, `test_pr130_live_canonical_jito_bundle_is_hard_blocked` |
| Tip in same transaction | `tip_transaction_index` must be `0` and transaction count must be `1` | `test_pr130_standalone_tip_transaction_is_blocked` |
| No standalone tip transaction | Standalone tip index in tx 1 produces `STANDALONE_TIP_TRANSACTION_FORBIDDEN` | `test_pr130_standalone_tip_transaction_is_blocked` |
| Tip account not through ALT | `tip_account_static=False` produces `JITO_TIP_ACCOUNT_MUST_BE_STATIC_NO_ALT` | `test_pr130_alt_tip_account_is_blocked` |
| Bundle acknowledgement/status is not settlement | `bundle_ack_treated_as_settlement=True` is blocked | `test_pr130_bundle_ack_or_status_is_not_settlement_proof` |
| Reviewable manifest | Canonical sender redacted manifest includes PR-130 policy state and blockers | `test_pr130_canonical_manifest_exposes_jito_policy` |

## Safety

This PR adds local policy/evidence checks only. Live submission remains gated by
existing compile-time/config controls.
