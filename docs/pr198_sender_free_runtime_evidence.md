# PR-198 — Sender-Free Durable Runtime and Real Shadow Evidence

## Purpose

This slice implements the first typed PR-198 acceptance boundary from the
consolidated seven-PR roadmap. It is intentionally offline and sender-free: a
green result means the runtime evidence is ready for PR-199 review, not that a
signer, sender, Jito transport or live capability may be imported.

The roadmap requires the full vertical to run on real data without signing or
submission: ingest/inbox, normalization, candidate, rooted state, plan, compile,
exact simulation and durable sender-free outcome.

## Scope

`src/paper_shadow/sender_free_runtime_evidence_pr198.py` validates:

- accepted PR-197 atomic execution/economic-kernel evidence;
- exact composition-stage order through durable outcome;
- PR-195 fenced queue/outbox, bounded concurrency, backpressure and restart
  safety;
- deterministic replay from raw inputs and protocol snapshots with ambient
  network disabled;
- immutable redacted shadow outcomes with would-submit identity, reason, costs,
  expected profit, slots, freshness and evidence hashes;
- multi-day non-synthetic mainnet read-only soak without trading wallet usage;
- required chaos scenarios for RPC disagreement, provider timeouts, webhook
  duplicate/gap, SQLite crash/busy, clock jump, drift, blockhash expiry and
  shutdown mid-attempt;
- SLO thresholds for ingest, quote/build, plan, simulation, DB contention and
  task/FD/memory growth;
- signed/redacted/immutable evidence bundle identities with exact commit, image,
  lock, config and protocol snapshot hashes;
- explicit denial of signing keys, sender modules, Jito submit endpoints, live
  permits and live capability.

## Safety properties

The result always returns `live_execution_allowed=false`,
`sender_import_allowed=false` and `signing_allowed=false`. The module cannot
submit, sign, open live mode, import a sender or mutate runtime state.

## Verification

The focused workflow runs Black, Mypy, the PR-198 regression suite, compileall
and evidence-hash capture on the two new Python files.

## Deliberate limits

This PR does not wire the production composition root, run live mainnet soak,
open signer IPC, submit canary transactions or consume real secrets. It creates
the fail-closed evidence contract that later runtime wiring and acceptance
artifacts must satisfy before PR-199 can begin.
