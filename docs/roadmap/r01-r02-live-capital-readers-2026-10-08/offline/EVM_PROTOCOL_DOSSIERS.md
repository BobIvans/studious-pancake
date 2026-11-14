# EVM account-light flash liquidity — offline technical dossiers
Audited 2026-10-08. EVM callback deployment and runtime gas make these future R-07 candidates for a 10 EUR testing budget. Read-only research can be done sooner; do not promote to Solana/Sui R02 core.

## Morpho Blue — high-priority later, zero protocol flash fee
Official https://docs.morpho.org/developers/contracts/blue/ and morpho-org/morpho-blue@8e26ca6a8dbc5089edcd67fb576248810fd2870a.
- `flashLoan(address token, uint256 assets, bytes calldata data)`, calls `onMorphoFlashLoan` on caller; no borrower credit position required; docs say `flashFee=0`.
- Max is token's **entire balance in Morpho Blue singleton contract**, not any single Morpho market available-to-borrow number. Source balance and token constraints need chain-specific deployed contract proof.
- Must use an authenticated, existing or deployed callback receiver contract; no free arbitrary EOA execution. One-time contract deployment requires gas unless reused/sponsored. Morpho native flashloan is NOT directly ERC-3156 compliant.

## Euler EVK — additional strong EVM candidate
Official https://docs.euler.finance/build/evk/interacting-with-vaults/ and https://docs.euler.finance/curate/vaults/evk/hooks-custom-logic/, pinned repo euler-xyz/euler-vault-kit@e88274cc624b9867d3c0197614dc5fe5201377c3.
- `EVault.flashLoan(uint256 amount, bytes data)`; authenticated borrower callback `onFlashLoan(bytes)`; repay underlying balance within same EVM transaction.
- Core normally has no flash fee, **but installed hooks can impose fee, eligibility restriction, pause or utilization cap**. Do not create generic zero-fee provider for every vault. Read each deployment's asset, balance, factory, hook receiver, fee checks, callback auth. Requires reusable callback contract.
- Every vault is a separate flash liquidity resource; do not double count the same underlying liquidity if wrappers/proxies share it.

## Aave V3 and SparkLend — Pool semantics, deployment-specific fee
Official https://aave.com/docs/aave-v3/guides/flash-loans
- `flashLoanSimple(receiverAddress,asset,amount,params,referralCode)` one asset, requires callback contract `executeOperation` and approval/repayment. `flashLoan()` multi-asset, approved `flashBorrowers` may have fee waiver ONLY on this variant.
- Fee initialized 0.05% historically, governance adjustable; **read current Pool.FLASHLOAN_PREMIUM_TOTAL** and per-reserve flash-enabled flags. A public borrower cannot assume whitelist status.
- SparkLend is a distinct deployed Aave-style pool with independent liquidity; an old deployment verification noted zero initial fee, NOT proof current fee remains zero. `SparkLend` requires current deployment address, pool premium, reserve flags, runtime health. Treat research until independently audited.

## Balancer V3 AND Balancer V2
- V3 official https://github.com/balancer/balancer-v3-monorepo/blob/main/pkg/vault/contracts/Vault.sol: `unlock(bytes)`, `sendTo(token,to,amount)`, transfer repayment, `settle(token,amountHint)` and zero non-settled deltas by end of unlock callback. This is **not the V2 flashLoan(receiver,tokens,amounts,userData) interface**. V3 fees and specific deployment restrictions must be confirmed on-chain.
- V2 official https://github.com/balancer/docs-developers/blob/main/resources/flash-loans.md: explicit `Vault.flashLoan` + `receiveFlashLoan` callback; different source/config and liquidity. Keep separate adapters if later qualified.

## Silo V2/V3 — flashLoan per vault, configurable fee
Official https://docs.silo.finance/docs/developers/dev-tutorials/hooks/ and /silo-config/. Docs expose Flash Loan hook with receiver, token, amount, fee; deployment configurations include `flashloanFee`. Silo v2/v3 naming/deployments matter. Requires callback contract and vault-specific source/fee proofs, not universal 0. Future R-07 only.

## Uniswap V2 — flash swap, NOT generic lending reserve
Official https://developers.uniswap.org/docs/protocols/v2/concepts/flash-swap. Pair.swap(amount0Out,amount1Out,to,data) permits optimistic token transfer and callback before settlement; repay returned asset + applicable pair swap fee OR pay other leg while preserving invariant. Reserve-specific, pool fee nonzero. Requires pair authentication and callback receiver. Liquidity is the trading pool itself: avoid double counting quote liquidity and lender capacity as independent.
## Uniswap V3 — pool-local `flash`
Official https://developers.uniswap.org/docs/protocols/v3/guides/flash-swaps/getting-started, /flash-callback. `pool.flash(recipient,amount0,amount1,data)` with `uniswapV3FlashCallback(fee0,fee1,data)`, verified canonical pool/factory, repay fee0/fee1. Receiver contract and gas required. Different ABI from Uniswap V2, no shared generic builder.
## PancakeSwap V3
Official https://github.com/pancakeswap/pancake-developer/blob/master/docs/pages/contracts/v3/pancakev3pool.md. Pool `flash(address recipient,uint256 amount0,uint256 amount1,bytes data)` with `pancakeV3FlashCallback`. Requires chain/pool/factory verification and fee. Do not assume its BNB Chain liquidity automatically applies to Solana/Sui.
## DODO V2 DVM/DPP
Official https://docs.dodoex.io/en/developer/contracts/dodo-v1-v2/guides/flash-loan. Pool `flashLoan` sends base/quote, DVMFlashLoanCall or DPPFlashLoanCall callback depending pool, enforces non-loss conditions. Fee and liquidity are pool-specific; two kinds are not fungible.
## Instadapp Flashloan Aggregator
Official https://docs.instadapp.io/flashloan/contracts. `getBestRoutes(tokens,amounts)` resolver can quote fees/routes, `flashLoan(tokens,amounts,route,data,instaData)` runs through underlying liquidity. **Router not independent lender**. Store normalized `underlying_capital_resource_id` / correlation group to avoid double counting an Aave/Spark/Balancer pool and the same pool reached via aggregator. Needs receiver and gas; check chain-specific contracts.
## Fluid DEX V2 / Liquidity Layer
Official https://docs.fluid.instadapp.io/integrate/dex-v2-swaps.html documents flash accounting via DEX V2 `settle()` and callback. Flash accounting does not by itself establish a general-purpose flashloan balance/borrow ABI. Keep as swap/settlement research only until a specific liquidity-layer flashloan is source-qualified.

## Exclusions / weakly verified
Maker/Sky DSS Flash (synthetic mint) and Pancake V2 are research placeholders only until current official deployment/fee and contract proofs; not counted as verified independent cash lenders. Any ERC-3156 lender requires *specific implementation* (standard is not lender).

---

# DOSSIER WAVE 2026-11-14 (R-07 stream L) — Morpho Blue + Aave V3 deployment/flashloan pins

Retrieval window UTC: 2026-11-13T20:51:00Z → 2026-11-14T00:11:53Z. Zero-network verifier: see `offline/verify_bundle.py` output recorded in the source ledger session receipt. All facts below are re-retrieved from official primary sources on the retrieval date; the 2026-10-08 sections above are history and are NOT rewritten.

Domain isolation (binding for this wave): EVM remains a separately isolated research domain. No cross-chain atomicity assumptions are made between EVM, Solana or Sui edges; chain IDs, deployed contracts, callback/receiver code, pool balances and gas/settlement semantics here are EVM-owned and never merged into Solana/Sui readers. Local/fork simulation (anvil/foundry fork of a pinned deployment) is the only execution-evidence path for any of this; nothing in this wave enables a provider, signs, sends, deploys a receiver, or claims live capacity.

Fact classes used in this wave:
- `RAW_OFFICIAL_SNAPSHOT`: address/constant copied verbatim from an official pinned source at retrieval time (no live chain read performed).
- `DOCS_REFERENCE_ONLY`: behavior quoted from official docs/source, not exercised on-chain.
- `BLOCKED_MISSING_PIN`: fact required for qualification that no official source pinned in this wave provides; typed blocker row.

## morpho_blue@2026-11-14 — RAW_OFFICIAL_SNAPSHOT + DOCS_REFERENCE_ONLY

Status: NOT enabled; remains OFFLINE_BEHAVIOR_REFERENCE_ONLY. Extends (does not replace) the 2026-10-08 section above.

Source pins (all 40-hex, verified via GitHub API at retrieval time):
- `morpho-org/morpho-blue` @ main `339a885801972740eb27f51da110a4675b839d42` (2026-11-13T10:51:42Z), SPDX license **GPL-2.0** (GitHub license field; scripts in deployment repo GPL-2.0-or-later). Release tag `v1.0.0` @ `55d2d99304fb3fb930c688462ae2ccabb1d533ad` — the deployed singleton source lineage.
- `morpho-org/sdks` @ main `56f1ed62827a7aab39d979c0143d1fbf970c37ca` (2026-11-12T14:55:52Z), SPDX license **MIT**; file `packages/morpho-ts/src/addresses.ts` is the official per-chain address registry used below.
- `morpho-org/morpho-blue-deployment` @ main `3c9ac96cf5c7352ff01739a15d6057198e76d70e` (2024-09-05, repo frozen; broadcast folders for chain ids 1, 5, 8453, 84532, 11155111).
- Official docs: https://docs.morpho.org/developers/contracts/blue/ (Blue contract reference) and https://docs.morpho.org/developers/contracts/addresses/ (canonical addresses page) and https://docs.morpho.org/learn/concepts/flashloans (flash-loan flow).

Deployments (`RAW_OFFICIAL_SNAPSHOT`, from `morpho-org/sdks@56f1ed62` `addresses.ts`; cross-checked against docs.morpho.org addresses page for the same contract names). Chain id → Morpho Blue singleton:
- 1 Ethereum mainnet → `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb`
- 8453 Base → `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb`
- 10 OP Mainnet → `0xce95AfbB8EA029495c66020883F87aaE8864AF92`
- 42161 Arbitrum One → `0x6c247b1F6182318877311737BaC0844bAa518F5e`
- 137 Polygon PoS → `0x1bF0c2541F820E775182832f06c0B7Fc27A25f67`
- 56 BNB Chain → `0x01b0Bd309AA75547f7a37Ad7B1219A898E67a83a`
The SDK registry lists 44 mainnet chains total (full mapping lives in the pinned `addresses.ts`; the 6 above are the chains tracked by `src/resources/multichain_capabilities.json` EVM rows). Corollary correction to the 2026-10-08 text: the singleton address is **not** identical across chains — per-chain pins are mandatory; Ethereum/Base share one canonical address, most other chains do not.

Flash-loan semantics (`DOCS_REFERENCE_ONLY`, docs Blue reference + flash-loans concepts page):
- Entry: `flashLoan(address token, uint256 assets, bytes calldata data)`. Morpho transfers `assets` to the **caller** (`msg.sender`), then calls `onMorphoFlashLoan(amount, data)` on the caller. There is no separate receiver address parameter — the caller and the callback receiver are the same contract.
- Repayment: inside the callback the receiver must `approve` the Morpho singleton for the borrowed amount; Morpho pulls the assets back. Missing approval/balance reverts the entire transaction (atomic).
- Fee: `flashFee` is **zero** (docs: "Not ERC-3156 compliant but compatibility is easily reached: a. flashFee is zero. b. maxFlashLoan is the token's balance of this contract. c. The receiver of assets is the caller.").
- Max/capacity read: max flash amount = the token's **entire balance of the Morpho Blue singleton** (all markets' liquidity + deposited collateral + donations), NOT any single market's available-to-borrow. Capacity read approach (`DOCS_REFERENCE_ONLY`): `IERC20(token).balanceOf(singleton)`; live per-chain values are NOT read in this wave.
- The per-market `fee` (uint128, `setFee`, cap `MAX_FEE = 0.25e18` in `ConstantsLib.sol` @ pinned SHA) is a lending-market fee accruing to `feeRecipient`; it is unrelated to flash loans and must never be booked as flash cost.
- Callback auth: callback must be on the contract that called `flashLoan`; no EOA path; a reusable deployed receiver contract is required (gas cost of that deployment is the setup cost, unchanged from the 2026-10-08 analysis).

Typed blockers carried forward (unchanged, none closed by this wave):
- `BLOCKED_MISSING_PIN`: per-chain live singleton token balances (live capacity) — requires R-02 bounded read evidence, not yet gathered.
- `BLOCKED_MISSING_PIN`: reusable callback receiver contract source/deployment pin (R-03 builder scope).
- `EXTERNAL_CONFORMANCE_MISSING`: fork-simulation proof per R-05.

## aave_v3@2026-11-14 — RAW_OFFICIAL_SNAPSHOT + DOCS_REFERENCE_ONLY + BLOCKED_MISSING_PIN rows

Status: NOT enabled; remains OFFLINE_BEHAVIOR_REFERENCE_ONLY. Extends the 2026-10-08 section above.

Source pins (all verified at retrieval time):
- `aave/aave-v3-origin` @ main `5c2eb37f39959dd491ba97fdc2af94bb4ee88f41` (2025-09-19T10:39:19Z). LICENSE at repo root: **Business Source License 1.1**, Licensor "Aave DAO, represented by its governance smart contracts", Licensed Work "Aave v3.3", Change License MIT, Change Date earlier of 2027-03-06 or a date on `v32.aavelicense.eth`. Additional Use Grant permits use/copy/modify but forbids uses that enable migration of users/funds away from Aave and production use by operators of competing Aave forks within the preceding four years. Official licensing statement: https://aave.com/docs/resources/code-licensing ("Aave V3 Smart Contracts: Business Source License 1.1 ... Converts to the MIT License by March 6, 2027"). BSL grants non-production use; reading balances and research is inside that grant, but production trading use needs a waiver/commercial grant — this is a typed license blocker for any future live wave.
- `aave/aave-v3-core` @ master `782f51917056a53a2c228701058a6c3fb233684a` (2024-09-03T13:56:19Z, final commit "chore: deprecate for 3.1 origin"). LICENSE.md: BSL 1.1 with Change Date 27 January 2023 → **converted to MIT** post-change-date. Tag `v1.19.4` @ `b74526a7bc67a3a117a1963fc871b3eb8cea8435`. This repo is the deployed V3.0/V3.1-era source lineage referenced by most current instances.
- `bgd-labs/aave-address-book` @ main `b8c801a413c4b934afaf7976d2ddc5fbada6dce6` (2026-11-11, release 4.77.6), SPDX **MIT**; npm package `@aave-dao/aave-address-book@4.77.6` (dist integrity `sha512-leqAnLA5Au27VDRMSNQeaqHmCQ5rjQXOo/7bivWay9Q2T4ZU8dQYZGSsdGu/MUttZs8TQrsQtLOVxFQGIHJh5w==`) provides `CHAIN_ID` + `POOL` per network. The Aave ecosystem's machine-readable deployment registry.
- Official docs: https://aave.com/docs/aave-v3/guides/flash-loans and https://aave.com/docs/reference/addresses (page JSON contains the full V3 deployment tables; parsed at retrieval time).

Deployments (`RAW_OFFICIAL_SNAPSHOT`): chain id → Pool proxy (cross-verified: aave.com addresses page JSON and address-book npm 4.77.6 agree on every row below).
- 1 Ethereum mainnet "Core" → `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2` (PoolAddressesProvider `0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e`)
- 1 Ethereum "Prime" (Lido marketplace instance) → `0x4e033931ad43597d96D6bcc25c280717730B58B1`
- 1 Ethereum "EtherFi" instance → `0x0AA97c284e98396202b6A04024F5E2c65026F3c0`
- 1 Ethereum "Horizon" RWA instance → `0xAe05Cd22df81871bc7cC2a04BeCfb516bFe332C8`
- 10 OP Mainnet → `0x794a61358D6845594F94dc1DB02A252b5b4814aD`
- 42161 Arbitrum One → `0x794a61358D6845594F94dc1DB02A252b5b4814aD`
- 43114 Avalanche → `0x794a61358D6845594F94dc1DB02A252b5b4814aD`
- 137 Polygon PoS → `0x794a61358D6845594F94dc1DB02A252b5b4814aD`
- 8453 Base → `0xA238Dd80C259a72e81d7e4664a9801593F98d1c5`
- 56 BNB Chain → `0x6807dc923806fE8Fd134338EABCA509979a7e0cB`
- 42220 Celo → `0x3E59A31363E2ad014dcbc521c4a0d5757d9f3402`
- 100 Gnosis Chain → `0xb50201558B00496A145fE76f7424749556E326D8`
- 57073 Ink → `0x2816cf15F6d2A220E789aA011D5EE4eB6c47FEbA`
- 59144 Linea → `0xc47b8C00b0f69a36fa203Ffeac0334874574a8Ac`
- 5000 Mantle → `0x458F293454fE0d67EC0655f3672301301DD51422`
- 4326 MegaETH → `0x7e324AbC5De01d112AfC03a584966ff199741C28`
- 143 Monad → `0x69a5F9AD4f96ebf0a0C792dD42a01cC5C0102fef`
- 9745 Plasma → `0x925a2A7214Ed92428B5b1B090F80b25700095e12`
- 196 X Layer → `0xE3F3Caefdd7180F884c01E57f65Df979Af84f116`
- 11155111 Sepolia (testnet) → `0x6Ae43d3271ff6888e7Fc43Fd7321a503ff738951`
- Officially grouped **Deprecated** on the addresses page (do not qualify without re-confirmation): Metis (1088) `0x90df02551bB792286e8D4f13E0e357b4Bf1D6a57`, Scroll (534352) `0x11fCfe756c05AD438e312a7fd934381537D3cFfe`, Soneium (1868) `0xDd3d7A7d03D9fD9ef45f3E587287922eF65CA38B`, Sonic (146) `0x5362dBb1e601abF3a4c14c22ffEdA64042E5eAA3`, ZKsync Era (324) `0x78e30497a3c7527d953c6B1E3541b021A98Ac43c`. Aave V3 on Aptos is a Move-VM deployment with no EVM Pool — out of EVM domain scope.
- Correlation rule (extends 2026-10-08): the four Ethereum instances (Core/Prime/EtherFi/Horizon) are separate deployed pools with separate liquidity; each is its own `underlying_capital_resource_id`. The identical Pool address on Arbitrum/Avalanche/Polygon/OP is a deterministic deployment artifact, not shared liquidity.

Flash-loan semantics (`DOCS_REFERENCE_ONLY`, flash-loans guide + `FlashLoanLogic.sol`/`Pool.sol` @ pinned SHAs):
- `flashLoanSimple(receiverAddress, asset, amount, params, referralCode)`: one asset, fee **never waived**, no debt-position alternative; lower gas. `flashLoan(receiverAddress, assets[], amounts[], interestRateModes[], params, referralCode)`: multi-asset; fee waived only for approved `flashBorrowers` (ACLManager), and per-asset a variable-rate debt position backed by collateral/credit delegation may be opened instead of repaying.
- Callback: Pool transfers assets to `receiverAddress`, then calls `executeOperation(asset(s), amount(s), premium(s), initiator, params)` on the receiver. `initiator` is the calling contract. Receiver must `approve` the Pool for `amount + premium` (or hold a debt position on `flashLoan()`); missing approval/balance reverts the whole transaction (atomic). Source line confirms: "no premium is paid when taking on the flashloan as debt".
- Fee: premium set **0.05% at deployment** and changeable by governance (PoolConfigurator `updateFlashloanPremiumTotal`, ACL-gated). Live value MUST be read per deployment: `Pool.FLASHLOAN_PREMIUM_TOTAL()` (uint128, basis points of 10000, so 0.05% = 5) and `Pool.FLASHLOAN_PREMIUM_TO_PROTOCOL()` for the treasury split. Rounding is in the Pool's favor on pull (`amount + premium`). A public borrower cannot assume whitelist fee-waiver status.
- Eligibility: flash loans only for reserves with borrowing enabled and active; per-reserve flash availability is state, not constant.
- Capacity read approach (`DOCS_REFERENCE_ONLY`): `Pool.getReservesList()` → `Pool.getReserveData(index)` (asset, liquidityRate, aToken, active/borrowing/frozen flags) plus `IERC20(asset).balanceOf(POOL)` for available cash; live values are NOT read in this wave.

Typed blockers:
- `BLOCKED_MISSING_PIN`: per-chain live `FLASHLOAN_PREMIUM_TOTAL()` values and per-reserve active/borrowing/paused flags — R-02 bounded read, not yet gathered.
- `BLOCKED_MISSING_PIN`: L2 Pool variant (`/aave-v3/smart-contracts/l2-pool`) gas-optimized `flashLoanSimple` specifics not pinned in this wave — L2 chains (Polygon/OP/Arbitrum/Base/Scroll/Mantle) may expose the L2 Pool instead of the generic Pool; must be pinned per chain before any builder work.
- `BLOCKED_LICENSE_GRANT`: aave-v3-origin BSL 1.1 until 2027-03-06 — production use of v3.3 source requires governance waiver/commercial grant; non-production research and simulation are within the Additional Use Grant.
- `EXTERNAL_CONFORMANCE_MISSING`: fork-simulation proof per R-05.

## EVM next-provider shortlist (docs-only ranking, wave 2026-11-14)

Ranked by incremental information value against the 2026-10-08 catalog (27 candidates, none qualified lenders). One provider per future PR; nothing enabled; every row keeps its existing disabled status.

1. **balancer_v2** — existing official source doc pin (`balancer/docs-developers` flash-loans.md); zero non-settled-delta `Vault.flashLoan` + `receiveFlashLoan` callback on a multi-token vault covers many assets per read. Typed blockers: `BLOCKED_MISSING_PIN` (Vault deployment address per chain), `BLOCKED_MISSING_PIN` (current protocol fee state — docs fee history is not a live pin), `EXTERNAL_CONFORMANCE_MISSING` (receiver contract + fork proof).
2. **uniswap_v3** — pool-local `flash`/`uniswapV3FlashCallback` with fee0/fee1; broad chain coverage via canonical factory. Typed blockers: `BLOCKED_MISSING_PIN` (canonical factory + per-chain pool registry pins), `BLOCKED_MISSING_PIN` (pool fee tiers per target pool), `EXTERNAL_CONFORMANCE_MISSING`.
3. **balancer_v3** — `unlock()`/`sendTo`/`settle` flash accounting, distinct ABI from V2 (no shared builder). Typed blockers: `BLOCKED_MISSING_PIN` (V3 Vault deployment pins), `BLOCKED_MISSING_PIN` (V3 fee/settlement state), `EXTERNAL_CONFORMANCE_MISSING`.
4. **euler_evk** — already repo-pinned (`euler-xyz/euler-vault-kit@e88274cc`); incremental value is per-vault deployment + hook/fee state (every vault is a separate liquidity resource). Typed blockers: `BLOCKED_MISSING_PIN` (per-vault deployment pins), `BLOCKED_MISSING_PIN` (installed hook fee/eligibility/pause state per vault), `EXTERNAL_CONFORMANCE_MISSING`.
5. **dodo** — existing offline adapter rows in `src/resources/multichain_capabilities.json` for the 6 tracked chains; per-pool base/quote debts already modeled. Typed blockers: `BLOCKED_MISSING_PIN` (per-pool deployment pins DVM/DPP/DSP per chain), `BLOCKED_MISSING_PIN` (per-pool fee + non-loss-condition state), `EXTERNAL_CONFORMANCE_MISSING`.

Not shortlisted this wave: spark_lend (needs full re-pin of a distinct deployment), instadapp_fla (router — dedup required before value), fluid_dex_v2_accounting (not proven general flashloan), maker_dssflash / pancakeswap_v2_flash_swap (no direct official source inspected yet), erc3156_implementations (standard, not a lender).
