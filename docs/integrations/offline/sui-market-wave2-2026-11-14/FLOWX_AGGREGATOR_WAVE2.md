# flowx_aggregator@2026-11-14 — Sui market wave-2 dossier (docs-only)

Wave-2 entry. ADDITIVE to PR #621 `FLOWX_SUI.md` (FlowX TypeScript SDK
`@flowx-finance/sdk` 2.1.0, `swap-aggregator.md` QUOTE surface, license UNKNOWN —
all owned there). This wave checks the official docs for **on-chain** package pins
and types the flash-lender verdict. Status: `OFFLINE_BEHAVIOR_REFERENCE_ONLY`
(discovery/quote routing); no capacity claim.

## Source pins (verified 2026-11-14)

- Official docs: https://docs.flowx.finance/contract/swap.md (fetched 2026-11-14),
  verbatim — the page contains exactly two on-chain anchors, as suiexplorer links:
  - `AMM`: `0xba153169476e8c3114962261d1edc70de5ad9781b83cc617ecc8c1923191cae0`
  - `ZAPPER`: `0x38eff60545e56d3bc1bab5f3efa31f50089e5f4b2d55d77717adcc041d34839f`
  These are explorer links (package or shared object not labeled by type on the
  page) — treated as `RAW_OFFICIAL_SNAPSHOT` of the links themselves, with the
  object-kind ambiguity typed below.
- `docs.flowx.finance/llms.txt` index scan (fetched 2026-11-14): DEX Aggregator
  description page, developer SDK pages (owned by #621), GenesiX farming/swap
  contract pages, bug bounty page. **No aggregator package ID page exists** in the
  index reviewed.

## Verdicts (typed)

- `MISSING_PIN`: on-chain **aggregator** package ID + aggregator Move module surface.
  Official docs expose only the AMM/ZAPPER anchors above; the aggregator itself is
  reachable solely via the hosted SDK (PR #621). Without the package pin, aggregator
  route decoding cannot be verified offline.
- `MISSING_PIN` (typed negative finding): no flash-loan API documented anywhere in
  the official FlowX docs reviewed — FlowX is quote routing only, never capital.
- `BLOCKED_MISSING_PIN`: AMM/ZAPPER anchor object-kind (package vs shared object)
  and per-pool fee/decimals state (no official schema page reviewed).
- `BLOCKED_LICENSE_GRANT` (caution): SDK license UNKNOWN per PR #621 (npm license
  None, no LICENSE file) — inherited; do not vendor SDK source.

## Failure semantics / rate limits

- Not published on the reviewed official pages → `MISSING_PIN` for 429/error contract
  (SDK error handling was out of #621's transcribed surface as well). Treat any
  third-party error-code table as unverified.

## Typed blockers summary

- `MISSING_PIN`: aggregator on-chain package + module ABI.
- `MISSING_PIN`: flash-loan API (negative finding).
- `BLOCKED_MISSING_PIN`: anchor object kinds; pool fee/decimals; error/rate-limit contract.
- `EXTERNAL_CONFORMANCE_MISSING`: PTB simulation proof.
- Capacity: **UNKNOWN** (quote ≠ capacity; repo vocabulary discovery vs capital).
