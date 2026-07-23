# PR-227 — Exact Money, Asset Identity and Atomic Execution Evidence

This PR starts the Pass 8/9 **PR-227** roadmap package as a dependency-gated,
sender-free/offline checkpoint.

## Roadmap ownership

PR-227 owns F-387–F-403, F-410–F-423 and F-481–F-495. Its roadmap goal is to
build an exact base-unit money model and one replayable atomic
plan/compiler/simulation contract where asset identity, amounts, protocol pins,
ALT, blockhash, fee and simulation all refer to one immutable byte identity and
one cluster context.

The uploaded roadmap also marks PR-227 as dependent on PR-225 and PR-228. This
checkpoint therefore returns `READY_DEPENDENCY_GATED`, not live readiness.

## Added checkpoint

- `src/pr227_exact_money_atomic_evidence.py`
- `tests/test_pr227_exact_money_atomic_evidence.py`
- `.github/workflows/pr227-exact-money-atomic-evidence.yml`

## Covered invariants

- exact non-bool integer base units with u64/u128 bounds;
- UI amount conversion requires explicit rounding policy and remainder evidence;
- cluster-bound asset identity includes genesis, mint, token program, rooted mint
  bytes, decimals, metadata slot and Token-2022 extension identity;
- built-in asset identity can no longer collapse to mint+decimals only;
- caller-supplied plan/sequence fingerprint is forbidden;
- plan hash changes when compute, tip, blockhash, ALT or asset identity changes;
- Leg A guaranteed output, Leg B input, dust, repayment, fee and tip are checked
  in one conservative balance equation;
- protocol pins require materialized program bytes length/hash and release
  registry hash;
- ALT evidence is resolver-owned: address list, raw account hash, rooted source
  slot, current slot, deactivation and extension metadata are validated;
- simulation evidence binds raw RPC request/response bytes, endpoint, genesis,
  JSON-RPC version, API version, context slot, fee, blockhash and explicit
  sigVerify policy;
- pre-signer freshness revalidates blockheight, reservation expiry, simulation
  hash and ALT hash immediately before any future signer boundary;
- bundle evaluation is blocked unless PR-225 provider plane and PR-228
  secret/release trust are declared ready by their own future gates.

## Safety boundary

This checkpoint does **not**:

- enable live trading;
- create or sign transactions;
- call RPC, Jupiter, Jito, MarginFi, Kamino, Helius or any provider;
- read wallets/private keys;
- submit or simulate real transactions;
- claim full PR-227 completion.

## Verification

```bash
python -m py_compile \
  src/pr227_exact_money_atomic_evidence.py \
  tests/test_pr227_exact_money_atomic_evidence.py
python -m pytest -q tests/test_pr227_exact_money_atomic_evidence.py
```

## Remaining full PR-227 work

Later slices must wire the evidence contract into the canonical atomic planner,
compiler and exact simulation implementation after PR-225 and PR-228 stabilize.
They must also retire superseded execution/numeric paths instead of creating
parallel `_prNNN` generations.
