# Roadmap PR-06 — management deadline and external audit anchoring

## Scope of this slice

This branch implements an active, reviewable subset of numeric roadmap PR-06.
It does not claim that PR-06 is complete while roadmap PR-04, PR-02 and PR-03
remain incomplete.

The slice changes the installed O1 management listener and adds a sender-free
audit-evidence product:

- the request timeout includes semaphore/queue wait as well as handler work;
- signed runtime-state verification runs outside the asyncio event loop;
- runtime snapshot reads use a single-open, `O_NOFOLLOW`, `fstat`-verified file
  boundary;
- a consistent SQLite backup is independently checked against the PR-184 audit
  chains;
- source DB/WAL/SHM are retained as non-authoritative forensic companions;
- the checkpoint is bound to release, source commit, environment, database
  epoch and PolicyBundle, then signed with a dedicated Ed25519 evidence key;
- a second key signs a create-only receipt intended for an independently
  mounted immutable/WORM anchor directory;
- verification reopens every artifact, recomputes hashes, replays the audit
  chain and verifies both signatures.

## Management behavior

`ActiveManagementHttpServer._bounded()` now establishes one timeout before it
waits for the connection semaphore. Queue saturation therefore cannot keep a
request alive indefinitely. Filesystem-backed state verification is executed
through `asyncio.to_thread`, so a slow local filesystem does not stall unrelated
coroutines.

`/ready` remains fail-closed. This patch does not manufacture PR-04 readiness;
it continues to accept only the existing canonical readiness payload and its
state hash.

## Audit checkpoint hierarchy

```text
live observability SQLite (+ WAL/SHM)
  -> SQLite backup API consistent snapshot
  -> PR-184 aggregate-chain verification
  -> signed PR-06 checkpoint manifest
  -> separately signed create-only anchor receipt
  -> independent verifier
```

The consistent backup is the checkpoint's transactional database image. Raw
DB/WAL/SHM copies are forensic material only and are explicitly labelled as
such. Their presence must never override a failed consistent snapshot or chain
verification.

## External-anchor deployment contract

The built-in anchor adapter writes with `O_CREAT|O_EXCL` and never updates an
existing receipt. Production must mount `--anchor-directory` from an
independently administered immutable or WORM-capable store. A normal writable
local directory demonstrates protocol behavior but is not, by itself, proof of
external immutability.

Example:

```bash
python -m src.observability.audit_anchor_pr06 capture \
  --database /var/lib/flashloan-bot/observability.sqlite \
  --output-directory /var/lib/flashloan-bot/checkpoint-001 \
  --release-id release-2026-07-23 \
  --source-commit <40-char-sha> \
  --environment paper \
  --policy-bundle-hash <sha256> \
  --keypair /run/secrets/audit-checkpoint-key.json

python -m src.observability.audit_anchor_pr06 anchor \
  --checkpoint /var/lib/flashloan-bot/checkpoint-001/audit-checkpoint.json \
  --anchor-directory /mnt/external-worm/audit-anchors \
  --anchor-id primary-worm \
  --keypair /run/secrets/external-anchor-key.json
```

The checkpoint and anchor keys are evidence/control identities. They must not be
trading-wallet keys and must be supplied as owner-only secret files.

## Safety boundaries

- no signer or trading-wallet import;
- no transaction sender, RPC submission or Jito path;
- no live enablement;
- no environment boolean can make canonical paper readiness true;
- no caller-supplied artifact digest is accepted;
- no raw DB/WAL/SHM copy can become authoritative settlement or financial truth.

## Remaining roadmap PR-06 work

Later slices still need the completed PR-04 service to publish its canonical
state into the signed runtime snapshot, authenticated-proxy or mTLS identity
that is not enabled by an environment boolean alone, deployment execution smoke
under the final seccomp/egress profile, real alert acknowledgement drills, and
backup/restore/rollback/signer-revocation rehearsals.
