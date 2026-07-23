# SUPER-MPR-A — Canonical Runtime + Legacy Retirement + Trusted Provider Gateway

## Scope

This PR starts the consolidated SUPER-MPR-A delivery track. It combines the
runtime authority, legacy execution retirement and trusted provider gateway
requirements into one reviewable slice.

The patch is intentionally sender-free and network-free. It does not claim full
paper readiness. It creates the installed runtime command surface and provider
normalization contract that later live-data paper wiring must use.

## Canonical runtime boundary

The production-facing entrypoint remains the installed console command:

```text
flashloan-bot -> src.cli_pr189:main
```

SUPER-MPR-A adds explicit public aliases that route through that installed CLI:

```text
flashloan-bot status
flashloan-bot paper
flashloan-bot shadow
flashloan-bot verify
```

The aliases are one-way compatibility shims:

```text
paper  -> run --mode paper
shadow -> run --mode shadow
verify -> readiness
```

There is no `live` alias. Live still fails closed through the existing product
contract.

## Legacy execution retirement contract

The new `src.super_mpr_a_runtime_gateway` contract lists source-only and legacy
surfaces that must remain outside the production runtime boundary:

```text
arb_bot.py
src.cli
src.legacy_arb_bot
src.ingest.execution_router
src.ingest.jito_shotgun
src.ingest.wsol_manager
src.ingest.dust_sweeper
src.execution.senders
```

The contract also provides fail-closed checks for paper/shadow imports that try
to reach sender, signer, live-control or Jito surfaces.

## Trusted provider gateway contract

The new gateway contract normalizes already-fetched provider bytes into one
provider-neutral quote model. It enforces:

- provider identity;
- strict bounded JSON parsing;
- request and response SHA-256 digests;
- context slot freshness;
- retry budget;
- quota budget;
- quote expiry;
- slippage and confidence bounds;
- canonical route digest.

No network I/O is performed in this slice. Later integration must route actual
Jupiter, Helius, OKX, Odos, OpenOcean and Solana RPC clients through this
boundary or an equivalent stricter gateway before paper/shadow can consume their
data.

## Safety boundary

This PR does not:

- enable live trading;
- enable Jito;
- load wallets or private keys;
- import signer services from paper/shadow;
- submit transactions;
- create on-chain ATA/wSOL side effects;
- declare `production_ready` or `paper_ready` true.

## Verification

```bash
python -m py_compile \
  src/super_mpr_a_runtime_gateway.py \
  tests/test_super_mpr_a_runtime_gateway.py
PYTHONPATH=. python -m pytest -q tests/test_super_mpr_a_runtime_gateway.py
```

## Remaining SUPER-MPR-A work

Follow-up work must wire every real HTTP/RPC provider adapter through this
trusted gateway, retire or quarantine remaining legacy source paths at import
runtime, and replace recorded-only provider fixtures with real live-data
paper/shadow candidates without allowing signer, sender or Jito access.
