# spark_lend_psm3@2026-11-14 — EVM financing wave-2 dossier (docs-only)

Wave-2 entry. ADDITIVE to wave-1: the ledger row `spark_lend` (role RESEARCH_EVM,
"INDIRECT_HISTORIC_DOC") and the 2026-10-08 SparkLend paragraph recorded "distinct
deployed Aave-style pool with independent liquidity; old zero-initial-fee observation
is NOT proof of current fee". This wave closes the deployment-address gap with the
official Spark Address Registry and pins the current official flash-loan doc page;
PSM3 is checked and typed. Status stays `OFFLINE_BEHAVIOR_REFERENCE_ONLY`.

## Source pins (verified 2026-11-14)

- `sparkdotfi/spark-address-registry` @ master (repo pushed 2026-11-13T07:29:04Z,
  license **AGPL-3.0**, verified via GitHub API on 2026-11-14; per-file source
  comment anchors e.g. `// spark-alm-controller/MainnetController.sol@984ec54
  (v1.10.0)`). Head commit SHA is recorded in SOURCE_MANIFEST.json.
  - `src/SparkLend.sol` (chain 1 Ethereum mainnet), verbatim constants:
    - `POOL = 0xC13e21B648A5Ee794902342038FF3aDAB66BE987`
    - `POOL_ADDRESSES_PROVIDER = 0x02C3eA4e34C0cBd694D2adFa2c690EECbC1793eE`
    - `POOL_ADDRESSES_PROVIDER_REGISTRY = 0x03cFa0C4622FF84E50E75062683F44c9587e6Cc1`
    - `POOL_CONFIGURATOR = 0x542DBa469bdE58FAeE189ffB60C6b49CE60E0738`
  - Registry also ships per-chain files (Arbitrum, Avalanche, BSC, Base, Gnosis,
    Optimism, Unichain, WorldChain, XLayer, Robinhood + `SparkLend.sol`); only the
    Ethereum mainnet POOL rows above were transcribed this wave.
- Official docs: https://docs.spark.finance/dev/sparklend/features/flash-loans
  (fetched 2026-11-14). Docs portal re-hosted at docs.spark.finance (former
  docs.spark.fi links in wave-1 history).
- `sparkdotfi/spark-psm` @ master (license **AGPL-3.0**, repo pushed 2026-11-02;
  default branch `master`) — PSM3 implementation, README: "implementation of a Peg
  Stability Module (PSM) contract, which facilitates the swapping, depositing, and
  withdrawing of three given assets"; swap surface `swapExactIn` / `swapExactOut` with
  `minAmountOut`/`maxAmountIn` guards; deposit/withdraw shares via mint/burn.

## SparkLend flash-loan semantics (DOCS_REFERENCE_ONLY, official docs 2026-11-14)

- Two entry points, same Aave-derived shapes: `flashLoan` (multi-reserve; fee waived
  when "msg.sender holds FLASH_BORROWER_ROLE") and `flashLoanSimple` (one reserve;
  "fee never waived"; "skips the multi-asset bookkeeping").
- Callback: multi-asset `executeOperation(address[] assets, uint256[] amounts,
  uint256[] premiums, address initiator, bytes params)` returns `bool`; single-asset
  receiver implements `IFlashLoanSimpleReceiver`. A `false` return reverts with
  `INVALID_FLASHLOAN_EXECUTOR_RETURN` (error code 13).
- Eligibility flag: bit 63 of the reserve configuration (`flashLoanEnabled`), toggled
  by `PoolConfigurator.setReserveFlashLoaning(asset, enabled)`; validation also
  checks the reserve is active and not paused; disabled reserve →
  `FLASHLOAN_DISABLED` (error code 91).
- Aave-v3 deviation: non-zero `interestRateModes[i]` reverts with
  `FLASHLOAN_INTO_BORROW_DEPRECATED` — "Flash loans must repay in-transaction, full
  stop" (no debt-position alternative).
- Repayment: "Grant Pool an ERC20 allowance for amount + premium of the borrowed asset
  before returning from executeOperation. The Pool performs safeTransferFrom to
  settle." If the Pool cannot pull, the tx reverts (atomic). Docs warn residual
  approvals/balances on receivers have been griefed.
- Fee: split between reserve LPs and treasury (bps) via
  `PoolConfigurator.updateFlashloanPremiumTotal` / `updateFlashloanPremiumToProtocol`;
  live values via `Pool.FLASHLOAN_PREMIUM_TOTAL()` / `FLASHLOAN_PREMIUM_TO_PROTOCOL()`.
  **The page states no default number** — the wave-1-era "zero initial fee" historic
  observation remains NOT a live pin.

## PSM3 verdict

`MISSING_PIN` (typed, negative finding): the official PSM3 README/source review found
**no flash-loan, flash-mint, or borrow entry point** — PSM3 is a swap/deposit/withdraw
peg-stability contract, not a flash lender. Any sDai/USDS liquidity seen through PSM3
is QUOTE/swap routing surface, not capital. Do not book PSM3 as a financing source.

## Typed blockers

- `MISSING_PIN`: SparkLend live `FLASHLOAN_PREMIUM_TOTAL()` value and
  `FLASH_BORROWER_ROLE` membership policy (docs state mechanics, not live numbers).
- `MISSING_PIN`: per-reserve `flashLoanEnabled` (bit 63) state per asset.
- `MISSING_DEPLOYED_ABI`: bytes4 selectors not published in official sources.
- `BLOCKED_MISSING_PIN`: pool liquidity (capacity) — R-02 bounded read; **UNKNOWN**,
  never zero.
- License notes: Spark docs/registry/PSM repos are AGPL-3.0 (registry + PSM verified
  via GitHub API); SparkLend core derives from Aave v3.0.2 lineage (Aave BSL terms of
  upstream apply to derived work questions — treat production use as unresolved until
  legal review; typed as `BLOCKED_LICENSE_GRANT` caution rather than a blocker to
  reading/research).
- `EXTERNAL_CONFORMANCE_MISSING`: fork-simulation proof (R-05).
