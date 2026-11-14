# evm_callback_atomicity@2026-11-14 — EVM financing wave-2 cross-provider note (docs-only)

Cross-provider atomicity note for EVM flash financing. Domain isolation rule holds
(wave-1, binding): EVM atomicity semantics are EVM-owned and never merged into
Solana/Sui readers; the Sui counterpart note lives in
`docs/integrations/offline/sui-market-wave2-2026-11-14/SUI_PTB_ATOMICITY_WAVE2.md`.

## The atomicity model (DOCS_REFERENCE_ONLY)

EVM flash lending is atomic via a **callback inside one transaction**. The lender
transfers the principal, invokes a designated callback function on the receiver/caller
contract, and requires principal + fee to be back (transferred or approvable for
pull) before the outer call completes. Any missing repayment reverts the whole
transaction — no partial settlement exists. Official-doc quotes pinned this wave:

- Aave (aave.com/docs/aave-v3/guides/flash-loans, fetched 2026-11-14): receiver must
  "give allowance to the `Pool`" for "the flash loaned amount + fee"; "If funds are
  missing: the transaction reverts." Pool pulls at the end of the callback.
- Euler (euler-vault-kit `IEVault.sol` nat-spec @ `93a1de49...`): `onFlashLoan()`
  "must repay the loan to the main Euler address prior to returning".
- Fluid (liquidity SPEC): only allow-listed protocols may call the Liquidity core; a
  public flashloan ABI is not documented → `MISSING_PIN` (see FLUID_LIQUIDITY_WAVE2).
- Morpho Blue / Balancer V2/V3, Uniswap V2/V3, DODO, Silo: wave-1 catalog notes stand
  unchanged (`onMorphoFlashLoan`, `receiveFlashLoan`, V3 `unlock`/`sendTo`/`settle`,
  `uniswapV2Call`, `uniswapV3FlashCallback`, `pancakeV3FlashCallback`, DVM/DPP call
  callbacks, Silo FLASH_LOAN hook).

## Interface names + selectors (pinned vs MISSING)

| protocol | entry (pinned source) | callback name | callback auth | bytes4 selector |
|---|---|---|---|---|
| Aave V3 `flashLoanSimple` | `IPool.flashLoanSimple(address,address,uint256,bytes,uint16)` @ aave-v3-origin `5c2eb37f...` | `executeOperation(address,uint256,uint256,address,bytes) returns (bool)` on `IFlashLoanSimpleReceiver` | receiver is the `receiverAddress` param; `initiator` echoed | `MISSING_DEPLOYED_ABI` (not source-published) |
| Aave V3 `flashLoan` (multi) | `IPool.flashLoan(...)` arrays | `executeOperation(address[],uint256[],uint256[],address,bytes)` on `IFlashLoanReceiver` | same | `MISSING_DEPLOYED_ABI` |
| Euler EVK | `EVault.flashLoan(uint256,bytes)` @ EVK `93a1de49...` | `onFlashLoan(bytes)` on `IFlashLoan` | **caller contract only** (no receiver param) | `MISSING_DEPLOYED_ABI` |
| Fluid Liquidity | no public ABI pinned | unpinned | allow-listed protocol addresses only | `MISSING_PIN` |
| Morpho Blue | wave-1 pin (`flashLoan(address,uint256,bytes)`) | `onMorphoFlashLoan(uint256,bytes)` | caller contract only | `MISSING_DEPLOYED_ABI` |

Rationale for the selector typing: no official doc or pinned source reviewed this wave
publishes bytes4 selectors for these callbacks, and the offline toolchain has no keccak
implementation to compute them. Policy: derive selectors from the pinned ABI at build
time, or leave unset; never copy from third-party selector databases (repo rule:
unknown is not zero, fixtures are never live evidence). ERC-3156 (`flashLoan`/
`flashFee`/`maxFlashLoan`, selectors published in the EIP text) remains a *standard*,
not a lender (wave-1 fact): only specific implementations count.

## Builder-facing obligations (R-03/R-05 scope, unchanged)

1. A reusable deployed receiver contract is mandatory for every callback above (EOA
   cannot receive the callback); deployment gas is a one-time setup cost.
2. Repayment arithmetic: owed = principal + fee, computed from the *live* per-
   deployment premium (Aave/Spark `FLASHLOAN_PREMIUM_TOTAL()`, stateful) or the
   protocol's documented fee rule (Morpho 0, Euler per-hook, Uniswap pair fee) —
   never from cached constants.
3. Callback sender authentication: `evm_financing.py`
   (`EvmFlashObligation.require_callback` / `expected_callback_sender`) already models
   this; selectors/ABIs stay unpinned until deployment conformance work lands.
4. All capacity claims remain **UNKNOWN** until an R-02 bounded read + R-05 fork
   simulation exists. Pins in this wave are documentation facts, not liquidity.
