# PR-197 — Archive-complete transaction absence proof and safe resubmission

## Safety boundary

A `null` value from `getSignatureStatuses` is an observation, not proof that a
signed Solana transaction never landed. A caller-provided block height is also
not trusted evidence. PR-197 introduces a separate proof boundary before any
full rebuild with a new permit can be authorized.

This patch does not sign, submit, replay, or automatically rebuild a transaction.
Live submission remains disabled by the existing gates.

## Proof requirements

`ArchiveCompleteResubmissionClient.collect_proof(...)` deliberately has no
`current_block_height` parameter. For every configured independent provider it
collects:

- finalized `getSlot` and `getBlockHeight` evidence;
- rooted `isBlockhashValid` evidence for the exact old blockhash;
- `getSignatureStatuses(searchTransactionHistory=true)` for every old signature;
- finalized `getTransaction` lookup for every old signature;
- genesis identity, provider/correlation identity, response hashes and an
  observation window.

A verified absence requires at least two archive-capable providers in distinct
correlation groups, one cluster genesis, finalized height beyond the original
last-valid height, exact blockhash invalidity, only missing signature/transaction
results, and a completed grace period. Any disagreement remains `ambiguous`.

Jito inflight/durable evidence is supplementary. `not_found` never proves
absence by itself, while pending/landed/unknown Jito evidence blocks the proof.

## Durable one-time authorization

`SQLiteResubmissionProofStore` stores the immutable proof and permits it to be
consumed once for a new permit request hash. The authorization binds:

- proof hash;
- superseded old message hash;
- new permit request hash;
- creation time.

A short proof expiry is enforced. A late landing sets a durable freeze latch and
prevents any further resubmission authorization.

## Compatibility

The legacy PR-045 status classifier remains available as observational
compatibility code. It must not be used as the resubmission authority. New code
must call `resubmission_decision_from_proof(...)` and durably consume the proof.
This additive boundary minimizes conflicts with parallel PR-190…196 work while
providing the contract needed for the later active sender cutover.

## Verification

```bash
python -m pytest -q tests/test_pr197_archive_complete_resubmission.py
python -m py_compile \
  src/submission/resubmission_proof_pr197.py \
  tests/test_pr197_archive_complete_resubmission.py
```

Covered regressions include caller-height removal, two-source archive proof,
provider disagreement, landed-before-expiry detection, grace-period enforcement,
Jito reconciliation, one-time proof consumption and late-landing freeze.
