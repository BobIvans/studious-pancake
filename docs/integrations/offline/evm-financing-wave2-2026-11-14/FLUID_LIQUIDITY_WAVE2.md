# fluid_liquidity@2026-11-14 — EVM financing wave-2 dossier (docs-only)

Wave-2 entry. ADDITIVE to the wave-1 catalog notes (`docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/EVM_PROTOCOL_DOSSIERS.md` "Fluid DEX V2 / Liquidity Layer" section, and the `fluid_dex_v2_accounting` ledger row): wave-1 recorded that flash accounting via DEX V2 `settle()` is NOT proof of a general-purpose flashloan ABI. This wave pins the **Liquidity layer deployment addresses from the official contracts repo** and formally types the missing public flash-loan ABI as a blocker. Status stays `OFFLINE_BEHAVIOR_REFERENCE_ONLY`; no provider enabled; no capacity claim.

Fact classes: `RAW_OFFICIAL_SNAPSHOT`, `DOCS_REFERENCE_ONLY`, `MISSING_PIN` (typed rows).

## Source pins (verified 2026-11-14)

- `Instadapp/fluid-contracts-public` @ main `404d73f91e6806f881f8dabeb30494f93f9e99b7` (committer date 2026-11-05T20:33:29Z, verified via GitHub API on 2026-11-14).
  - LICENSE at repo root: **Business Source License 1.1**. Parameters (read from the pinned LICENSE file): Licensor "Instadapp Labs"; Licensed Work "Fluid Contracts (c) 2023 Instadapp Labs"; Additional Use Grant: **educational purposes only**, production use (including offering the work to third parties hosted/embedded, especially if competing with Instadapp Labs products) expressly prohibited; Change Date **2027-12-19**; Change License **GNU General Public License v2.0 or later**. → typed `BLOCKED_LICENSE_GRANT` for any production financing use before the change date.
  - Deployment registry: official machine-readable JSONs under `deployments/<chain>/Liquidity.json` in the same repo (ABI + address per chain). GitHub API `license` field reports NOASSERTION because of the BSL; the LICENSE file text is authoritative.

## Liquidity contract deployment pins (`RAW_OFFICIAL_SNAPSHOT`)

Copied verbatim from `deployments/<chain>/Liquidity.json` at the pinned SHA:

| chain | dir present in repo | Liquidity proxy address |
|---|---|---|
| 1 Ethereum mainnet (`deployments/mainnet/Liquidity.json`) | yes | `0x52Aa899454998Be5b000Ad077a46Bbe360F4e497` |
| 42161 Arbitrum One (`deployments/arbitrum/Liquidity.json`) | yes | `0x52Aa899454998Be5b000Ad077a46Bbe360F4e497` |
| 8453 Base (`deployments/base/Liquidity.json`) | yes | `0x52Aa899454998Be5b000Ad077a46Bbe360F4e497` |
| 10 OP Mainnet | **no `deployments/optimism/` dir in repo** | `MISSING_PIN` |

Identical address across mainnet/arbitrum/base is a deterministic deployment artifact (same proxy pattern), NOT shared liquidity: each deployment custodies its own chain's funds. Repo `deployments/` also contains `bnb`, `plasma`, `polygon` (not part of the 6 tracked EVM chains this wave).

## Liquidity-layer flash-loan semantics (DOCS_REFERENCE_ONLY + typed blockers)

- `contracts/liquidity/SPEC.md` (pinned): "Fluid Liquidity is the single core contract that custodies all supplied funds and exposes a unified deposit / withdraw / borrow / payback surface (`operate`) to the allow-listed protocols built on top (Lending / fToken, Vault, DEX, stETH queue, Flashloan, etc.). End users never talk to Liquidity directly: a 'user' in this contract is always another Fluid protocol address."
- `contracts/liquidity/proxy.sol` header comment (pinned): the proxy serves "all allow-listed protocols, such as fTokens, Vault, Flashloan, StETH protocol, DEX protocol".
- Therefore: a "Flashloan" protocol class exists on the Liquidity layer, but **no public `flashLoan(...)` entry point, no public receiver/callback interface (name or signature), and no flash fee formula is documented in the official repo/docs reviewed this wave**. `docs/docs.md` (fetched 2026-11-14) contains zero flash-loan content. The only in-repo Flashloan artifact found is `contracts/mocks/mockFLA.sol` (a mock).
- The official Fluid docs site (docs.fluid.instadapp.io, VitePress) was reachable this wave; `deployment-addresses.html` and `llms.txt` returned 404 at retrieval time; no flash-loan integration page was found in the sitemap snapshot reviewed.

Typed blockers:
- `MISSING_PIN`: public flash-loan ABI on the Fluid Liquidity layer (entry function, callback interface, fee semantics, min/max) — must be pinned from an official source (contract source or official docs) before any Fluid financing adapter work. Until then Fluid is swap/settlement research only (matches wave-1 `fluid_dex_v2_accounting` posture).
- `MISSING_PIN`: OP Mainnet Liquidity deployment address (absent from official repo at pinned SHA).
- `BLOCKED_LICENSE_GRANT`: BSL 1.1, educational-only Additional Use Grant until 2027-12-19 (production use needs grant).
- `BLOCKED_MISSING_PIN`: per-chain live Liquidity balances (flash capacity) — R-02 bounded read, not gathered. Capacity is **UNKNOWN**, not zero.
- `EXTERNAL_CONFORMANCE_MISSING`: fork-simulation proof (R-05).

Correlation note (extends wave-1 `instadapp_fla` row): the Instadapp Flashloan Aggregator (FLA) routes through underlying liquidity; any future Fluid flashloan route reached via FLA must be stored with the same `underlying_capital_resource_id` as the direct Fluid route — aggregator and layer are not two independent lenders.
