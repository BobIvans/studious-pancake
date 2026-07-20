# PR-074 — durable capital engine integrated with exact fee workflow

## Scope

This patch starts roadmap PR-074 without enabling live trading, signing, sender
imports, or transaction submission.

It adds a narrow sender-free capital workflow that can be called after the
final canonical message has been built and Solana `getFeeForMessage` has
returned a non-null fee for that exact message.

## Boundary

The workflow:

1. keeps the existing PR-057 durable reservation as the pre-submission capital
   fence;
2. applies the exact final `getFeeForMessage` result to a `CapitalCandidate`;
3. revalidates the candidate while excluding the current attempt's own active
   reservation from startup-recovery subtraction;
4. fails closed and releases the pre-submission reservation if the exact final
   fee makes the candidate unaffordable or non-profitable;
5. fails closed and releases if the exact final required lamports exceed the
   already-durable reservation amount.

## Non-goals

- No MarginFi execution capability is added.
- No Jupiter `/build` integration is added.
- No signer or sender path is imported.
- No live or canary mode is enabled.
- No reservation top-up/re-reserve behavior is introduced; increased exact fees
  require a future reviewed rebuild/replan path.

## Focused validation

```bash
python -m pytest tests/test_pr074_exact_fee_capital_workflow.py -q
python -m pytest tests/test_pr057_durable_capital_reservations.py \
  tests/test_pr074_exact_fee_capital_workflow.py -q
python -m compileall -q src/economics tests/test_pr074_exact_fee_capital_workflow.py
```

Full repository validation remains:

```bash
python scripts/verify_repo.py --skip-dependency-audit
```
