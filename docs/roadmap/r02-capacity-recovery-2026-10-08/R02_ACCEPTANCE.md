# Acceptance and negative evidence matrix — R02-CAP
```
Stage        Allowed                                Not allowed
R02-STRUCT   Pinned source decode, synthetic replay   FlashCapitalEdge creation from raw vault balance
R02-LIVE     Rooted/independent real reserve snapshot New account, signed/sent transaction
R03-OFFLINE  Unsigned SDK-conformant borrow/repay     Claim full live borrow capacity
R05-PAPER    Complete exact tx simulation            Production promotion without safety review
```

## Quality sequence
1. Offline pin integrity `offline/verify_offline.py` must match every Git blob SHA; 19 primary SDK reference source files, Jupiter 192-byte layout and Kamino 280-byte prefix. This is a **provenance check**, not live decoder conformance.
2. `offline/test_probe_structural.py` on synthetic samples; wrong owner, discriminator, size, encoding, padding, missing fee fields. This probe always sets `qualified_edges=[]`, `execution_authority=NONE`.
3. Runtime R02 test: governed per-RPC admission, immutable source generation, independent finality/quorum, batch account reads and actual exact SDK field mapping. Separate public smoke result and independently anchored acceptance receipts. Rooted RPC peers must be operationally independent providers, not aliases of the same upstream.
4. For positive `FlashCapitalEdge` an actual live *resource-level* snapshot must prove all: chain genesis / Sui package & checkpoint; program or object owner, mint/coin type and decimals; fee numerator/denominator and correct rounding; all applicable flash borrow caps and available vault balance; outstanding liabilities/reservations; pause/freeze, staleness, object-version conflicts; pre-existing ATA/position cost; deterministic raw read hash and independent corroboration; amount+effective fee; no unresolved UNKNOWN state.
5. Failed proof: preserve typed negative `MISSING_EFFECTIVE_FLASH_CAP`, `MISSING_PINNED_DEPLOYED_ABI`, `FEE_SCHEMA_DRIFT`, `NO_INDEPENDENT_QUORUM`, `NAVI_API_ONLY_NOT_ONCHAIN`, `P0_ACCOUNT_BINDING_PENDING_USER`. NO positive edge on a fake or historical snapshot.
6. Replay from captured evidence with network forbidden; tests verify no state promotion after tampering / unknown version / expired fee / reused wallet identity. Run existing QPR/DIN/Dynamic Universe/FlashCapitalGraph tests and `python scripts/verify_repo.py`, record actual count and HEAD; do not copy #585 historical test claims.
7. Operational safety: unchanged `sign_enabled=false`, `send_enabled=false`, no create or close token accounts, no ATA payments, no P0 account creation, no secrets, no live borrow, all 27 catalog providers disabled until separate qualification.

## PR division
R02-CAP-A: source-pinned Jupiter TokenReserve + limit ownership reader. R02-CAP-B: Kamino real reserve/fee decoder and on-chain reader. R02-CAP-C: NAVI current package/object/fee reader. R02-CAP-D: P0 bank-only / optionally preexisting account public scanner. Small independent PRs target main. R03 starts with offline SDK builders in separate PR(s) only after cross-owner contracts freeze; R03 not a replacement for R02.

## Stop definition
Structural parser alone = `PARTIAL_DECODED`, not pass. If no real network/SDK compatible adapter, record `BLOCKED_LIVE_STATE`, with exact field and resource missing. R02 positive completion requires actual current on-chain snapshots for *each relevant lender* with replay, validated against real SDK version; if P0 public account unavailable, report three lenders evaluated and P0 user-binding still BLOCKED. Do not overstate "four qualified readers". 
