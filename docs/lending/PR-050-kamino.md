# PR-050 — Kamino lending/liquidation promotion boundary

## Goal

Support Kamino liquidation candidates only when the exact protocol, asset pair,
market, reserves, oracle accounts, writable metas, IDL hash, deployed program,
and RPC fixture provenance have been reviewed and pinned.

Kamino's official developer entry point is the Kamino documentation and the
`@kamino-finance/klend-sdk` package. This PR records those provenance fields but
keeps the packaged runtime registry empty until real reviewed entries are added.

## What this PR adds

- `src.lending.kamino.KaminoSupportedRegistry` for supported combinations.
- `KaminoDeploymentProvenance` requiring official HTTPS source, klend SDK name,
  IDL SHA-256, RPC fixture SHA-256, program ID, deployment slot, and review date.
- `KaminoShadowLiquidationPlanner` that returns a typed shadow decision and never
  builds or submits a transaction.
- Integer-only profitability math including:
  - network fee;
  - priority fee;
  - rent/ATA budget;
  - slippage budget;
  - flash-loan fee;
  - Kamino/protocol fee;
  - configured minimum net profit.
- A tiny exact binary fixture decoder to prove fail-closed parsing behavior.

## Safety boundary

The default packaged registry is intentionally empty:

```json
{
  "schema_version": "pr050.kamino-supported-combinations.v1",
  "combinations": []
}
```

An empty or unverified registry is a safe-idle state, not a fallback to guessed
Kamino addresses. `config/kamino_supported_combinations.example.json` is only an
operator template and keeps `verified=false`.

## Non-goals

- No live trading.
- No signer or sender.
- No Kamino instruction builder.
- No account mutation.
- No automatic promotion from a docs URL alone.
- No claim that the fixture decoder is a production Kamino account layout.

## Future promotion checklist

Before a real Kamino pair can become supported, attach evidence for:

1. official source URL and reviewed SDK/IDL version;
2. deployed program ID and deployment slot;
3. real RPC account bytes for market, reserves, oracle inputs, and obligation;
4. SHA-256 of the exact IDL and fixtures;
5. supported writable metas and owners;
6. integer health/liquidation math review;
7. exact simulation and reconciliation evidence from the common kernel;
8. separate shadow soak report;
9. human review that live remains disabled.

## Verification

```bash
python -m pytest tests/lending/test_kamino_pr050.py -q
python -m compileall -q src/lending tests/lending
python scripts/verify_repo.py
```
