# PR-049 — Phoenix/OpenBook orderbook conformance

PR-049 starts with **one venue only**: Phoenix legacy spot. OpenBook v2 remains
outside the default registry until a later focused PR can pin and verify its
own official artifacts.

## Scope implemented

- The default orderbook registry no longer contains synthetic Phoenix/OpenBook
  program IDs.
- The default Phoenix registry entry pins the official mainnet Phoenix program:
  `PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY`.
- The official source repository and Solana verified-build command are pinned in
  `src.providers.orderbook.conformance`.
- Shadow and live are both disabled by default until an operator supplies
  verified market/account bytes and a verified artifact hash.
- Synthetic PR-016 orderbook fixtures moved to `tests/fixtures` and are loaded
  explicitly by fixture tests only.
- The runtime adapter no longer hardcodes `PHXLEG16` or `OBV2LEG!`; decoding is
  driven by the selected registry spec's `layout_discriminator`.

## Verified-build pin

The pinned verification command is:

```bash
solana-verify verify-from-repo -um \
  --program-id PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY \
  https://github.com/Ellipsis-Labs/phoenix-v1
```

The registry intentionally remains fail-closed with:

```json
{
  "enabled_shadow": false,
  "enabled_live": false,
  "markets": []
}
```

A later promotion PR must replace `sha256:verification-required-before-shadow-enablement`
with an operator-verified artifact hash and add real market fixtures before
shadow is allowed.

## OpenBook v2 boundary

OpenBook v2 is not enabled in the PR-049 default registry. Existing synthetic
OpenBook tests still run against `tests/fixtures/orderbook_venues_fixture.json`,
but that fixture registry is not loaded by production code paths.

## Non-goals

- no live orderbook execution;
- no production IOC instruction builder for Phoenix;
- no OpenBook v2 mainnet registry entry;
- no RPC calls from conformance checks;
- no claim of market readiness without official account bytes, layout proof,
  partial-fill proof and settlement proof.

## Acceptance mapping

- Fake `PHXLEG16` / `OBV2LEG!` magic bytes are removed from adapter code.
- Fake Phoenix/OpenBook program IDs are removed from the default registry.
- Default Phoenix pin uses the official mainnet program ID.
- Fixture-only synthetic decoding remains isolated under `tests/fixtures`.
- Live remains disabled.
- Shadow remains disabled until verified bytes and artifact hash are supplied.
