# PR-136 — Multi-RPC independence, rooted-fork quorum and endpoint trust

This patch adds a side-effect-free PR-136 quorum primitive. It does not call RPC,
does not submit transactions, and does not change paper/live execution behavior.

## What changed

- Adds endpoint identity evidence to `src/data_plane/rpc.py`:
  - provider/operator identity;
  - backend correlation group;
  - region and endpoint account label;
  - genesis hash;
  - node version and feature set;
  - max supported transaction version;
  - bounded evidence freshness.
- Adds rooted fork evidence for RPC samples:
  - current slot;
  - finalized slot;
  - root slot;
  - block hash marker.
- Adds `RootedRpcQuorumGate`:
  - requires finalized/rooted evidence;
  - rejects samples whose context slot is not rooted;
  - counts independent correlation groups, not URLs;
  - rejects same-slot payload conflicts;
  - rejects feature-set mismatch by default;
  - rejects unsupported transaction-version evidence.
- Adds focused PR-136 negative tests.

## Safety properties

- Two URLs on the same backend/correlation group cannot satisfy a two-source
  quorum.
- Highest-slot equality alone is not enough: the context slot must be covered by
  rooted/finalized evidence.
- Matching payloads are comparable only when genesis, request, commitment,
  feature set, transaction-version support and freshness are compatible.
- The canonical endpoint is selected from already-validated independent evidence;
  latency is never a substitute for trust.

## Non-goals

- No live submission enablement.
- No sender, signer, Jito, MarginFi, Jupiter or wallet behavior changes.
- No network client wiring.
- No automated endpoint discovery.
- No on-chain block ancestry fetch yet; this primitive stores the evidence that
  a future RPC adapter must supply.

## Suggested verification

```bash
python -m pytest tests/test_pr136_rooted_rpc_quorum.py -q
python -m pytest tests/test_pr040_rpc_ws.py -q
python -m black --check src/data_plane/rpc.py tests/test_pr136_rooted_rpc_quorum.py
python scripts/verify_repo.py --skip-dependency-audit
```

## Acceptance mapping

| Requirement | Evidence |
|---|---|
| Two correlated URLs cannot satisfy quorum | `test_pr136_two_correlated_urls_cannot_satisfy_two_source_quorum` |
| Independent rooted sources can accept | `test_pr136_independent_rooted_sources_accept_same_payload` |
| Same-slot conflicts fail closed | `test_pr136_same_slot_payload_conflict_fails_closed` |
| Unrooted source cannot join quorum | `test_pr136_unrooted_or_lagging_endpoint_cannot_join_quorum` |
| Genesis / tx-version support required | `test_pr136_genesis_and_transaction_version_support_are_required` |
| Feature-set mismatch is not comparable | `test_pr136_feature_set_mismatch_is_not_comparable_by_default` |
