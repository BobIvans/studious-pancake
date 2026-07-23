# PR-222 — Atomic Flash-Loan Execution and Sender-Free Qualification

This slice starts the Mega-PR PR-222 vertical as a sender-free evidence gate.
It does not sign, submit, read private keys, call RPC/Jito/Jupiter/MarginFi, or
claim live readiness.

## Scope

The new gate validates one immutable evidence bundle for:

- canonical atomic plan identity and durable reservation binding;
- compiled v0 message identity, blockhash window, min-context slot and wire size;
- decoded MarginFi borrow/repay and Jupiter leg instruction semantics;
- exact simulation evidence bound to the same message bytes;
- conservative economics, failed-landing fee reserve and guaranteed output;
- installed sender-free qualification evidence and PR-223 handoff readiness.

## Safety boundary

A passing PR-222 report always leaves:

```text
signer_allowed=false
sender_allowed=false
live_execution_allowed=false
```

The only positive state is `ready_for_pr223_signer_review`, which means the
sender-free atomic evidence contract is coherent enough for a later isolated
signer PR to review exact bytes. It is not permission to trade.

## Verification

```bash
python -m py_compile \
  src/atomic_sender_free_execution.py \
  tests/test_atomic_sender_free_execution.py
PYTHONPATH=. pytest -q tests/test_atomic_sender_free_execution.py
```

## Local result

```text
7 passed
```

## Follow-up work inside PR-222

This is the first acceptance-gate slice. Later PR-222 commits should connect the
same contract to the installed sender-free composition root once PR-219, PR-220
and PR-221 authority surfaces are stable.
