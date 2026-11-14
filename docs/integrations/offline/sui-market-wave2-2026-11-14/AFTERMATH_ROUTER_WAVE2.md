# aftermath_router@2026-11-14 — Sui market wave-2 dossier (docs-only)

Wave-2 entry. ADDITIVE to PR #621 `AFTERMATH_SUI.md` (SDK router QUOTE/build surface:
TypeScript SDK, gRPC transport, externalFee/recipient, docs v3.3.1 warning). That
dossier deliberately did NOT pin the on-chain packages. This wave pins the official
on-chain contract IDs from the docs "Contracts" pages and types the flash-lender
verdict. Status: `OFFLINE_BEHAVIOR_REFERENCE_ONLY` (discovery/quote routing); no
capacity claim.

## Source pins (verified 2026-11-14)

- Official docs: https://docs.aftermath.finance/pools/contracts.md (fetched
  2026-11-14, official `.md` variant of the spot-pool contracts page), verbatim:
  | contract | type | id |
  |---|---|---|
  | amm | package | `0xefe170ec0be4d762196bedecd7a065816576198a6527c99282a2551aaa7da38c` |
  | ammInterface | package | `0x0625dc2cd40aee3998a1d6620de8892964c15066e0a285d8b573910ed4c75d50` |
  | events | package | `0xefe170ec0be4d762196bedecd7a065816576198a6527c99282a2551aaa7da38c` (same package as amm) |
  | poolRegistry | object | `0xfcc774493db2c45c79f688f88d28023a3e7d98e4ee9f48bbf5c7990f651577ae` |
  | protocolFeeVault | object | `0xf194d9b1bcad972e45a7dd67dd49b3ee1e3357a00a50850c52cd51bb450e13b4` |
  | treasury | object | `0x28e499dff5e864a2eafe476269a4f5035f1c16f338da7be18b103499abf271ce` |
  | insuranceFund | object | `0xf0c40d67b078000e18032334c3325c47b9ec9f3d9ae4128be820d54663d14e3b` |
  | lpCoinsTable | object | `0x7f3bb65251feccacc7f48461239be1008233b85594114f7bf304e5e5b340bf59` |
- Separate per-product Contracts pages exist (`perpetuals/contracts.md`,
  `trade/dca/contracts.md`, `trade/limit-orders/contracts.md`) — perps/DCA/limit
  products were NOT transcribed this wave (out of swap-market scope; do not merge
  perps packages into swap routing).
- Router surface itself (how to route, fee fields, SDK versions): **owned by PR #621
  `AFTERMATH_SUI.md`** — see that file; not re-pinned here.

## Fee/decimals semantics (DOCS_REFERENCE_ONLY)

- Protocol fee accrues to the pinned `protocolFeeVault`/`treasury` objects (docs
  contract table); the AMM's per-pool fee parameters and LP-fee split were not
  transcribed this wave → `BLOCKED_MISSING_PIN` per-pool fee state.
- Coin decimals: AMM pool objects carry per-coin balances in smallest units; pool
  type tags embed `<CoinTypeA, CoinTypeB>` — decimals come from coin metadata, never
  assumed.

## Flash-lender verdict

`MISSING_PIN` (typed negative finding): no flash-loan/flash-borrow entry point is
documented in the official Aftermath docs pages reviewed (pools contracts page +
llms.txt index scan 2026-11-14). Aftermath is routing/discovery only until a Move
flash API is officially pinned. Router capacity is a QUOTE concept — not lender
capacity; the two must never be conflated (repo vocabulary: discovery vs capital).

## Typed blockers

- `MISSING_PIN`: AMM Move module flash-loan API (none documented) — required before
  any Aftermath capital consideration.
- `BLOCKED_MISSING_PIN`: per-pool fee parameters, LP fee split, pause state.
- `BLOCKED_MISSING_PIN`: on-chain live package ID confirmation vs the docs page
  (Sui packages upgrade; docs page fetched 2026-11-14 but no on-chain read performed).
- License: aftermath-ts-sdk license not reviewed (PR #621 acquisition row recorded
  the same gap) — do not vendor SDK source without license review.
- `EXTERNAL_CONFORMANCE_MISSING`: PTB simulation proof.
- Capacity: **UNKNOWN**.
