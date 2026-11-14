# aave_v3_flashloansimple@2026-11-14 — EVM financing wave-2 dossier (docs-only)

Wave-2 entry. ADDITIVE to (never replaces) the wave-1 pins in
`docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/EVM_PROTOCOL_DOSSIERS.md`
(morpho_blue@2026-11-14 + aave_v3@2026-11-14, merged via PR #618). Wave-1 pinned the
deployment table; this wave pins the per-deployment `flashLoanSimple` call surface,
callback interface, and fee-read functions. Status stays
`OFFLINE_BEHAVIOR_REFERENCE_ONLY`. No provider enabled; no capacity claim; no live read.

Fact classes: `RAW_OFFICIAL_SNAPSHOT` (verbatim constants copied from pinned official
sources at retrieval time), `DOCS_REFERENCE_ONLY` (behavior quoted from official docs,
not exercised on-chain), `BLOCKED_MISSING_PIN` / `MISSING_DEPLOYED_ABI` (typed blockers).

## Source pins (verified 2026-11-14)

- `aave/aave-v3-origin` @ `5c2eb37f39959dd491ba97fdc2af94bb4ee88f41` (commit verified
  live via GitHub API on 2026-11-14; committer date 2025-09-19T10:39:19Z — same commit
  pinned by wave-1; default branch `main`). License: **BSL 1.1** (see wave-1 license
  block and `BLOCKED_LICENSE_GRANT` row, unchanged).
  - `src/contracts/interfaces/IPool.sol` (L403): exact `flashLoanSimple` signature:
    ```solidity
    function flashLoanSimple(
      address receiverAddress,
      address asset,
      uint256 amount,
      bytes calldata params,
      uint16 referralCode
    ) external;
    ```
  - `src/contracts/interfaces/IPool.sol` (L699, L707): fee-read functions pinned:
    `function FLASHLOAN_PREMIUM_TOTAL() external view returns (uint128);` and
    `function FLASHLOAN_PREMIUM_TO_PROTOCOL() external view returns (uint128);`
  - `src/contracts/misc/flashloan/interfaces/IFlashLoanSimpleReceiver.sol` (L25):
    ```solidity
    function executeOperation(
      address asset,
      uint256 amount,
      uint256 premium,
      address initiator,
      bytes calldata params
    ) external returns (bool);
    ```
- Official docs: https://aave.com/docs/aave-v3/guides/flash-loans (fetched 2026-11-14):
  "borrows from a single reserve. The fee is never waived and no debt position can be
  opened, but it uses less gas"; "The flash loan fee is set to 0.05% at deployment and
  can be changed by governance vote"; "At initialization, `FLASHLOAN_PREMIUM_TO_PROTOCOL`
  is set to 0"; pull repayment: "You **don't** need to transfer the owed amount back to
  the `Pool`. The funds are _pulled_ automatically at the end of your operation" —
  receiver "must give allowance to the `Pool`" for "the flash loaned amount + fee";
  failure semantics: "If funds are missing: the transaction reverts" (whole-tx revert,
  atomic).
- Deployment addresses: **not re-pinned in wave-2**; wave-1 (same-day retrieval window
  2026-11-13T20:51Z..2026-11-14T00:11:53Z, PR #618) pinned them from the
  aave.com/docs/reference/addresses page JSON cross-verified against
  `@aave-dao/aave-address-book@4.77.6`. Cite wave-1 `deployment_pins` for chain ids
  1 / 10 / 42161 / 8453 (see table below). The aave.com addresses page is
  JS-rendered; wave-2 re-fetch via plain HTTP returned only the page shell, so no
  independent wave-2 snapshot of the table was taken.

## Per-deployment `flashLoanSimple` surface (DOCS_REFERENCE_ONLY)

| chain id | Pool proxy (from wave-1 #618 pins) | flashLoanSimple exposure |
|---|---|---|
| 1 Ethereum mainnet "Core" | `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2` | docs document `flashLoanSimple` on the V3 Pool generically; Core instance is a full-featured Pool |
| 10 OP Mainnet | `0x794a61358D6845594F94dc1DB02A252b5b4814aD` | L2 chains may expose the gas-optimized L2 Pool instead of the generic Pool — variant not pinned |
| 42161 Arbitrum One | `0x794a61358D6845594F94dc1DB02A252b5b4814aD` | same L2 Pool caveat |
| 8453 Base | `0xA238Dd80C259a72e81d7e4664a9801593F98d1c5` | same L2 Pool caveat |

Identical Pool address on 10/42161 is a deterministic deployment artifact, not shared
liquidity (wave-1 correlation rule, unchanged). The Ethereum Prime/EtherFi/Horizon
instances remain separate `underlying_capital_resource_id`s.

## Fee semantics (DOCS_REFERENCE_ONLY)

- Premium: `FLASHLOAN_PREMIUM_TOTAL()` is the live fee in basis points of 10000
  (uint128; 0.05% = 5). Governance-adjustable per deployment via
  `PoolConfigurator.updateFlashloanPremiumTotal`. Live per-chain values NOT read in
  this wave → typed blocker below.
- `flashLoanSimple` fee is **never waived** (no `flashBorrower` whitelist path on this
  variant; waiver exists only on multi-asset `flashLoan()` for ACLManager-approved
  `flashBorrowers`).
- Repayment owed = `amount + premium`; rounding is in the Pool's favor on pull
  (wave-1 fact, unchanged).

## Typed blockers (carried/new)

- `MISSING_DEPLOYED_ABI`: bytes4 selector for `flashLoanSimple(...)` and
  `executeOperation(...)` is NOT published in any official source reviewed (docs and
  pinned IPool.sol give names/types only). Do not hard-code selectors from third-party
  databases; derive from the pinned ABI at build time or leave unset. (No keccak
  implementation available in the offline toolchain to compute them in-dossier.)
- `BLOCKED_MISSING_PIN`: per-chain live `FLASHLOAN_PREMIUM_TOTAL()` /
  `FLASHLOAN_PREMIUM_TO_PROTOCOL()` values (R-02 bounded read; not gathered).
- `BLOCKED_MISSING_PIN`: L2 Pool variant `flashLoanSimple` specifics for OP/Arbitrum/
  Base (wave-1 blocker, not closed).
- `BLOCKED_MISSING_PIN`: per-reserve `flash-enabled`/active/borrowing/paused state
  (per-reserve eligibility is state, not constant).
- `BLOCKED_LICENSE_GRANT`: aave-v3-origin BSL 1.1 until 2027-03-06 (wave-1 fact).
- `EXTERNAL_CONFORMANCE_MISSING`: fork-simulation proof (R-05).
- Capacity: **UNKNOWN**. A docs/repo pin is NOT a capacity proof; no balance read, no
  RPC call, no fork run was performed in this wave.
