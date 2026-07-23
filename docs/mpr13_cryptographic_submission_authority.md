# MPR-13 — Cryptographic signer and rooted submission authority

## Status

This draft adds the first production-shaped MPR-13 authority while keeping
`MPR13_COMPILE_TIME_LIVE_ENABLED = False`. It does **not** enable a signer,
private-key access, RPC submission or Jito submission.

All changed paths are new, so the branch does not rewrite files currently used by
parallel roadmap PRs. The legacy PR-045 surface remains in place until a reviewed
cutover removes or permanently disables it.

## Authority chain

```text
exact VersionedMessage bytes
  -> solders decoder inside signer boundary
  -> payer/signers/writable accounts/programs/blockhash/ALT identity
  -> immutable review hash + cluster/policy/block-height bounds
  -> durable SQLite permit
  -> atomic permit consume + immutable full-bundle intent
  -> staged transport evidence + identity-bound receipt
  -> authenticated status observation
  -> observed / confirmed / finalized / reconciled
  -> archive-complete absence quorum + late-landing freeze before rebuild
```

## Findings addressed

| Finding | Control introduced |
|---|---|
| F-314 | `SoldersVersionedMessageDecoder` derives authority-bearing identity from canonical bytes; no caller-owned `program_ids` input exists. |
| F-315 | Review and permit bind exact message/identity hashes, decoder version, payer/signers/accounts/programs/blockhash, cluster, policy generation and ALT snapshots. |
| F-316 | Permit state is persisted in SQLite and survives process restart. |
| F-317 | Permit TTL is bounded; consumption checks rooted block height with a safety margin. |
| F-318 | `commit_intent()` consumes the permit and creates the immutable intent in one `BEGIN IMMEDIATE` transaction. |
| F-319 | Ordered tuples retain every bundle message hash, wire digest and signature. |
| F-320 | Status envelopes bind exact intent identity, genesis, request/response hashes, provider, slot/root and collection time, and require an authority MAC. |
| F-321 | Jito inflight status is always advisory/`OBSERVED`, including provider text `Landed`. |
| F-322 | `OBSERVED`, `CONFIRMED`, `FINALIZED` and `RECONCILED` remain distinct; finalized evidence must be root-covered. |
| F-323 | Rebuild fails closed unless rooted blockheight expiry, archive completeness, two independent absence authorities and the late-landing freeze are present. |
| F-324 | ACK requires prior dispatch evidence and an identity-matching provider receipt. |
| F-325 | Durable lifecycle and hash-chained events are restart-queryable through ambiguity and rooted reconciliation. |
| F-326 | Only `BODY_COMPLETE` or later becomes ambiguous; DNS/connect/TLS failures remain pre-send. |

## Durable schema

The authority owns four tables:

- `permits`: exact decoded identity, policy/revocation generations and one-time state;
- `intents`: complete ordered wire identity and materialized lifecycle state;
- `events`: per-intent hash-chained transition evidence;
- `observations`: authenticated status envelopes with request/response and slot/root identity.

SQLite uses WAL, `synchronous=FULL`, foreign keys, a `0700` directory and a `0600`
DB file.

## Required cutover before review-ready

This draft is not permission to activate live trading. Before changing the
compile-time flag:

1. The isolated signer must call only this byte-derived policy boundary.
2. The canonical sender must receive only an opaque committed `intent_id`, not
   call the legacy in-memory `LivePermitIssuer.consume()` path.
3. RPC/Jito adapters must produce authenticated staged-write and receipt evidence
   at the transport boundary.
4. The archive-complete absence proof must come from a registered authenticated
   recovery authority rather than a caller-constructed object.
5. Capital release and realized PnL must accept only `RECONCILED` intent IDs.
6. Legacy live submission paths must be deleted or permanently hard-disabled.
7. Full repository CI, restart/process-race and real solders message fixtures must pass.

## Verification

```bash
PYTHONPATH=. python -m pytest -q tests/test_mpr13_authority.py
python -m py_compile src/submission/mpr13_authority.py tests/test_mpr13_authority.py
```

The targeted suite covers false metadata vs bytes, TTL/blockheight expiry,
restart/double consumption, full bundle identity, ACK identity, advisory Jito
inflight status, confirmed/finalized separation, tampered observations, staged
transport ambiguity, and archive/quorum/freeze rebuild policy.
