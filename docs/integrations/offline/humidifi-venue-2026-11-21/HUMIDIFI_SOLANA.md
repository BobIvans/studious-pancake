# HumidiFi (Solana Prop AMM) — venue dossier (DAG node N01)

Status: **PINNED_SOURCE_REFERENCE — CAPTURE_ONLY — NOT PAPER_QUALIFIED — NOT PROMOTABLE**
Owner: PR #665 implementation slice (`codex/prop-amm-competitive-toolchain-2026-11-21`), taking N01 ownership per user decision 2026-11-21.
Base main SHA audited: `2628041ab145432759e38e65ce8c4c5517c778fc`.
Machine-readable pins: [`SOURCE_MANIFEST.json`](./SOURCE_MANIFEST.json) (this directory).

## 1. Identity

| Field | Value |
| --- | --- |
| Official name | HumidiFi (Solana Proprietary AMM) |
| Role | Direct Prop AMM venue candidate (WSOL↔USDC/USD1) |
| Chain/domain | Solana mainnet-beta |
| Operator | HumidiFi (off-chain operator; on-chain program is closed-source) |
| Correlation group | prop_amm (independent of CPMM/CLMM/DLMM aggregators) |
| Checked at | 2026-11-21 |

## 2. Official sources

| Source | Value | Status |
| --- | --- | --- |
| Docs / OpenAPI | NONE FOUND — HumidiFi publishes no official program documentation or IDL | UNKNOWN, honestly recorded |
| Source repository (instruction layout) | `LimeChain/pmm-sim` @ `cc4ae891a2a765d92c89d4381f96dce4afd446bb` (MIT) + `LimeChain/magnus` @ `9ecd34b634031f5dfdf5747c33a329605ea6e7c4` (MIT) | PINNED, mirrored with SHA256SUMS |
| SDK | NONE — no official SDK exists; bindings are reverse-engineered in the pinned research source | — |
| Terms/license | Venue operator terms UNKNOWN; upstream research source is MIT | UNKNOWN ≠ zero |

The program itself is closed-source. Everything below is derived from the pinned MIT-licensed research harness source, verified against deployed on-chain state during a one-time read-only capture. It is **not** an official contract statement.

## 3. Access

| Field | Value |
| --- | --- |
| Auth mode | NONE (permissionless on-chain program) |
| Secret reference | NONE — no credentials used or stored |
| Free tier | n/a |
| Rate limit | n/a (no API) |
| Base URL / program ID | Program `9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp` (from pinned magnus `pmm_humidifi::declare_id!`, blob `f43ad2b0ba7a93b6b78cce0ab690ec82301cde49`) — on-chain owner equality asserted at capture |

## 4. Semantic contract

| Field | Value |
| --- | --- |
| Exact vs indexed | Exact at the captured slot only (raw account bytes + deployed program bytes executed in local LiteSVM). Stale for any other slot. |
| Slot/finality | Recorded per snapshot under `research/pmm-sim-caller-profile/snapshot/` |
| Units | Raw integer token amounts; WSOL 9 dec, USDC 6 dec, USD1 6 dec |
| Token-2022 | UNKNOWN (all pinned markets use SPL Token program) |
| Oracle | UNKNOWN (not applicable to pinned HumidiFi markets) |
| Underlying venue identity | Direct HumidiFi market accounts; no aggregator wrapping |
| min_amount_out | **HumidiFi IGNORES min_amount_out** (upstream pmm-sim notes). Hard gate. |
| CU/fee model | UNKNOWN (CU measured per benchmark row from LiteSVM; operator fee model not documented) |
| Account closure | UNKNOWN |

## 5. Evidence

- Mirror integrity: `vendor/strategy-research/pmm-sim-cc4ae891/` — `provenance.json` + `SHA256SUMS` (170 files); upstream master head == pin at verification (2026-11-21, no drift); Magnus `extend-router-ixs` branch still exactly at pinned rev.
- Markets: 15 market entries (v1×5, v2×5, v3×5) from pinned `cfg/setup.toml` (sha256 `859b6e4e…`); each market/ATA existence and owner verified in the one-time capture.
- Capture: one-time user-authorized read-only `getAccountInfo`/`getMultipleAccounts` (public RPC, credential-free, no subscriptions, no signing) → `research/pmm-sim-caller-profile/snapshot/<slot>/` with per-account SHA-256 + whole-snapshot digest. **CAPTURE_ONLY evidence — never PAPER_QUALIFIED, never live.**
- Caller-profile matrix: see `research/pmm-sim-caller-profile/` results; every row carries `classification` (`SYNTHETIC_SIMULATION` vs `GENUINE_EXECUTABLE_ROUTE_CANDIDATE`) and router-binary provenance.
- Quote parity vs Jupiter comparator: **BLOCKED_PROVIDER_CALLS_DISABLED** in this slice (official Jupiter V2 `/order`/`/build` adapter is a later PR). Aggregator results here are local simulations only.

## 6. Promotion blockers

1. **BLOCKED_UNTIL_SAME_TX_POST_BALANCE_GUARD** — HumidiFi ignores `min_amount_out`; a direct route must prove a same-transaction post-balance assertion guaranteeing minimum proceeds + flashloan repayment, or stay blocked.
2. **BLOCKED_SNAPSHOT_STALENESS** — benchmark rows are valid only at the captured slot; no cross-slot reuse.
3. **BLOCKED_PROVIDER_CALLS_DISABLED** — genuine aggregator-route comparison and official Jupiter/direct-builder conversion are separate gated PRs.
4. **UNKNOWN ≠ zero** — quote model, CU/fee model, account-closure semantics and operator terms remain UNKNOWN until separately pinned; fixtures are never live evidence.
5. No spoof binaries or caller impersonation may ever reach a mainnet transaction builder (`must_not` in `VENDORED_SOURCE_MANIFEST_V1.json`).
