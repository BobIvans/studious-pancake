# PR-095 — Kamino real conformance promotion gate

This PR adds the review boundary for the optional Kamino track without enabling
live trading, signing, RPC submission, liquidation execution or automatic runtime
promotion.

## Intent

PR-067 introduced a schema for Kamino conformance evidence. PR-095 tightens that
boundary for a future real promotion package by requiring:

- exact `Kamino-Finance/klend` source pin;
- exact `Kamino-Finance/klend-sdk` source pin;
- the `@kamino-finance/klend-sdk` package identity;
- current developer-doc source reference;
- deployment-program hash evidence;
- canonical IDL hash evidence;
- SDK account and instruction vector evidence;
- read-only RPC market, reserve, obligation and oracle vectors;
- oracle, health and fee proof;
- a common-kernel proof so MarginFi/Kamino math stays comparable;
- a dedicated sender-free shadow soak reference;
- signed human review.

## Safety boundary

A passing PR-095 evaluation means only:

```text
ready-for-shadow-review
```

It always returns:

```text
live_execution_allowed = false
```

The module does not import a signer, sender, Jito transport, RPC submit path,
wallet key path or live runtime command.

## Evidence location

Materialized PR-095 artifacts must live under:

```text
evidence/kamino/pr095/
```

`check_pr095_materialized_artifacts(...)` verifies that every referenced file
exists under that root and hashes to the pinned SHA-256 digest.

## Recommended focused verification

```bash
python -m pytest tests/lending/test_kamino_pr095_real_conformance.py -q
python -m pytest \
  tests/lending/test_kamino_pr067_conformance.py \
  tests/lending/test_kamino_pr095_real_conformance.py -q
python -m black --check \
  src/lending/kamino_real_conformance.py \
  tests/lending/test_kamino_pr095_real_conformance.py
```

## Non-goals

- no liquidation execution;
- no flash-loan execution;
- no signer or wallet mutation;
- no live/canary enablement;
- no fabricated real artifacts;
- no automatic use of Kamino combinations by the standard runtime.
