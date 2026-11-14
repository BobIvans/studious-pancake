# euler_evk@2026-11-14 — EVM financing wave-2 dossier (docs-only)

Wave-2 entry. ADDITIVE to wave-1: the 2026-10-08 Euler EVK section and the
`euler_evk` ledger row in `docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/`
(pinned `euler-xyz/euler-vault-kit@e88274cc...`) already recorded
`EVault.flashLoan(uint256,bytes)` + `onFlashLoan(bytes)` and the hooks-caveat. This
wave re-pins the current source generation, adds the exact callback interface file and
the **BSL 1.1 license parameters** (previously unrecorded), and types the per-vault
deployment-registry gap. Status stays `OFFLINE_BEHAVIOR_REFERENCE_ONLY`.

## Source pins (verified 2026-11-14)

- `euler-xyz/euler-vault-kit` @ master `93a1de491531e54cbbcf0e5c8cacfe558f924867`
  (committer date 2026-10-29T15:17:06Z, verified via GitHub API on 2026-11-14;
  default branch `master`; repo pushed 2026-11-02). Wave-1 pin `e88274cc...` recorded
  as `previous_pins` lineage.
  - `src/EVault/IEVault.sol` (L259-264), verbatim:
    ```solidity
    /// @notice Request a flash-loan. A onFlashLoan() callback in msg.sender will be invoked, which must repay the loan
    /// to the main Euler address prior to returning.
    /// @param amount In asset units
    /// @param data Passed through to the onFlashLoan() callback, so contracts don't need to store transient data in
    /// storage
    function flashLoan(uint256 amount, bytes calldata data) external;
    ```
  - `src/interfaces/IFlashLoan.sol` (file SPDX header `GPL-2.0-or-later`), verbatim:
    ```solidity
    interface IFlashLoan {
        /// @notice Function that will be called on the caller of `flashloan`
        /// @param data Data that was passed to the `flashloan` call
        function onFlashLoan(bytes memory data) external;
    }
    ```
  - Repo-root `LICENSE`: **Business Source License 1.1**; Parameters: Licensor
    "Euler Labs Ltd."; Licensed Work "Euler Vault Kit (c) 2024 Euler Labs Ltd.";
    **Additional Use Grant: None**; Change Date **2029-04-24**; Change License
    **GNU General Public License v2.0 or later**. Note the mixed license surface: the
    repo root LICENSE is BSL 1.1 while at least the pinned interface file carries an
    SPDX `GPL-2.0-or-later` header — do not treat the repo as uniformly MIT/GPL.
    GitHub API license field: NOASSERTION (BSL).

## Flash-loan semantics (DOCS_REFERENCE_ONLY, from the pinned source nat-spec)

- Caller == callback receiver: `flashLoan(uint256 amount, bytes calldata data)` invokes
  `onFlashLoan(bytes memory data)` on `msg.sender` (no separate receiver address
  parameter). The callback "must repay the loan to the main Euler address prior to
  returning" — repay-by-transfer model, in the same transaction.
- Fee: **not assumed zero**. Wave-1 fact stands: core normally has no flash fee, but
  installed hooks can impose fee/eligibility/pause/utilization caps per vault; every
  vault is a separate flash liquidity resource (no double counting of wrappers sharing
  the same underlying).
- Failure semantics: repayment must be complete before the callback returns; a vault
  with a paused/hooked state may revert (exact revert conditions per deployment are
  unpinned).

## Typed blockers

- `MISSING_PIN`: official per-vault EVK deployment registry (address list per chain).
  Searched the euler-xyz org on 2026-11-14: no public deployments/registry repo was
  identified (unlike Aave's address-book). Without a registry pin, per-chain per-vault
  addresses remain UNKNOWN.
- `BLOCKED_MISSING_PIN`: installed hook fee/eligibility/pause state per vault (wave-1
  blocker, unchanged; per-vault, per-chain, stateful).
- `MISSING_DEPLOYED_ABI`: bytes4 selectors for `flashLoan(uint256,bytes)` and
  `onFlashLoan(bytes)` not published in official sources; derive from pinned ABI at
  build time.
- `BLOCKED_LICENSE_GRANT`: EVK BSL 1.1 with **no Additional Use Grant** until
  2029-04-24 — stricter than Aave's BSL; production use requires an Euler Labs grant.
- `EXTERNAL_CONFORMANCE_MISSING`: fork-simulation proof (R-05).
- Capacity: **UNKNOWN** (per-vault balances never read; docs pin is not capacity
  proof).
