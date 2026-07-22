# PR-179 strict lossless decoding and structural budgets

PR-179 addresses hostile provider/RPC/transaction input boundaries where malformed
serialized input must not be silently filtered, truncated, coerced, or allowed to
amplify CPU/memory/account work.

## This slice

This PR hardens the active Jupiter `/swap/v2/build` parser:

- JSON is decoded with duplicate-key rejection.
- JSON non-finite constants (`NaN`, `Infinity`, `-Infinity`) are rejected.
- Instruction lists are lossless: one malformed element rejects the entire
  response.
- ALT maps are lossless: malformed keys or addresses reject the entire response.
- `routePlan` must be a bounded list of mapping elements.
- Instruction data is base64-validated and bounded by decoded bytes.
- Instruction bucket counts, account metas, ALT tables and ALT address counts are
  bounded before execution instructions are built.
- `blockhashWithMetadata.blockhash` must be exactly 32 bytes.
- Integer strings are digit-count bounded and limited to u64 for Jupiter amount
  fields.

## Safety boundary

This PR does not enable live trading, signing, Jito submission, or new provider
network calls. It only tightens decoding of data that the existing Jupiter adapter
already consumed.

## Why this matters

The snapshot `(11)` audit reproduced two active parser hazards:

- malformed Jupiter instruction list elements were silently removed;
- malformed ALT entries were silently removed.

Both can turn hostile or corrupted provider output into an apparently smaller
valid artifact. PR-179 makes those cases fatal.

## Focused verification

```bash
python -m pytest tests/providers/test_pr179_jupiter_strict_decoding.py -q
python scripts/verify_repo.py
```

## Non-goals

Follow-up PR-179 slices should extend the same strict decoder pattern to Solana
RPC responses, transaction proof inputs, evidence manifests, model artifacts,
webhooks and finalized transaction decoding.
