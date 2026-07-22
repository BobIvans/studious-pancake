# PR-122 — Deterministic opportunity identity and persistent dedup

This PR implements the review-safe core of roadmap PR-122: deterministic logical
opportunity identity and a persistent SQLite dedup ledger. It intentionally does
not alter the live/runtime detector path in this patch, so it remains stable
while neighboring roadmap PRs are being merged in parallel.

## Scope covered

- Deterministic logical opportunity ids with the `lop_<sha256>` shape.
- Canonical JSON hashing for exact route evidence.
- Identity payload includes strategy, opportunity type, pair id, exact amount,
  policy version, optional slot bucket, and first/second leg evidence.
- Recent blockhash / recent transaction material is intentionally excluded.
- Persistent SQLite ledger blocks duplicate logical opportunities after process
  restart.
- Explicit material invalidation reasons are required to re-admit the same
  logical id.

## Safety boundary

- No RPC calls.
- No provider calls.
- No transaction building.
- No signing.
- No submission.
- No bundle polling.
- No wallet mutation.
- No live or paper runtime migration.

## Deferred wiring

Earlier PR-122 iterations wired the deterministic id directly into the detector
and domain model. That created repeated conflicts while `main` was moving through
parallel strategy/runtime PRs. This version keeps the stable primitive and ledger
only; runtime wiring can be added in a follow-up PR after surrounding discovery
and lifecycle changes settle.

## Acceptance mapping

| Requirement | Evidence |
|---|---|
| Same exact evidence yields same id | `test_same_exact_market_evidence_replays_same_logical_id` |
| Material route changes change the id | `test_material_route_change_changes_logical_id` |
| Recent blockhash is excluded | `test_blockhash_is_not_part_of_identity_payload` |
| Missing request/response evidence is rejected | `test_missing_request_or_response_hash_is_rejected` |
| Persistent dedup survives restart | `test_persistent_ledger_blocks_same_evidence_after_restart` |
| Material invalidation can re-admit | `test_material_invalidation_can_admit_same_logical_id` |
| Unknown invalidation is rejected | `test_unknown_invalidation_reason_is_rejected` |

## Suggested verification

```bash
python -m pytest tests/test_pr122_opportunity_identity.py -q
python scripts/verify_repo.py --skip-dependency-audit
```
