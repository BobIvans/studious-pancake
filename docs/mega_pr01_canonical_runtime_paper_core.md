# MEGA-PR-01 — Canonical Runtime, Durable Paper Core

This is the first sender-free slice for the V2 production-readiness MEGA-PR-01.
It is intentionally not a live-trading, signing, sender or transaction-building
change.

## Roadmap ownership

The V2 audit says the repository is not production-live ready and not yet ready
for operational paper trading: the architecture is fail-closed, but the installed
paper vertical still does not execute a full cycle. MEGA-PR-01 is the first P0
mega package and targets one real installed sender-free paper vertical with
durable state and a fail-closed provider data plane.

This slice covers the acceptance shape for the following MEGA-PR-01 findings:

- `IMPL-01` supported paper command has no executable end-to-end cycle;
- `IMPL-02` runtime authority is fragmented across proof islands;
- `IMPL-03` durable paper paths point into read-only application filesystem;
- `IMPL-04` non-root UID `10001` named-volume ownership is unproven;
- `IMPL-05` mounted `runtime.env` is not consumed by canonical runtime;
- `IMPL-06` legacy setup and PM2 remain competing unsafe entrypoints;
- `IMPL-07` legacy Kamino program ID conflicts with reviewed KLend identity;
- `IMPL-08` provider configuration and SecretHandle flow are incomplete;
- `IMPL-09` shipped production package surface exceeds active runtime graph.

## What this slice adds

- `src/mega_pr01_canonical_runtime_paper_core.py` — an offline typed evidence
  evaluator for the first MEGA-PR-01 paper-core acceptance bundle.
- `tests/test_mega_pr01_canonical_runtime_paper_core.py` — positive and negative
  probes for composition-root drift, writable durable state, raw secret exposure,
  missing paper dependencies, data-lineage gaps, protocol identity drift and
  accidental live/signer/sender enablement.
- `scripts/verify_mega_pr01_canonical_runtime.py` — focused verifier for this
  slice.
- `.github/workflows/mega-pr01-canonical-runtime.yml` — sender-free focused CI.

## Current boundary

The gate can mark an evidence bundle as ready for functional sender-free paper
core only when all required surfaces are present and no live/signer/sender scope
is requested. The result explicitly keeps `production_ready=false`,
`live_execution_allowed=false`, `signer_allowed=false` and `sender_allowed=false`.

## Follow-up implementation work

This PR starts the acceptance contract. Later MEGA-PR-01 commits still need to
wire the real installed paper runtime to this gate:

1. choose the final runtime lifecycle authority and quarantine duplicate active
   proof islands;
2. add the actual batch source, runtime cycle and `PaperShadowRuntimeDependencies`;
3. move paper DB/journal/evidence to mounted writable state and prove fsync,
   restart, kill-9 recovery, backup/restore and corruption handling;
4. replace generic raw environment/provider seams with typed provider config and
   SecretHandle/FileHandle objects;
5. bind rooted RPC, Helius intake, MarginFi/Kamino/Jupiter identity and provider
   lineage to planning;
6. run one positive installed-wheel paper fixture to durable `paper_accepted` and
   stable negative reject fixtures.

## Safety invariants

- no private-key loading;
- no signer or sender process;
- no RPC, Jito, Helius, Jupiter, MarginFi or Kamino network call;
- no transaction construction, simulation, signing, submission or reconciliation;
- no paper-ready, production-ready or live-ready claim.
