# sui_ptb_atomicity@2026-11-14 — Sui local-atomicity note (docs-only)

Sui-side counterpart to `docs/integrations/offline/evm-financing-wave2-2026-11-14/EVM_CALLBACK_ATOMICITY_WAVE2.md`.
Domain isolation rule holds: Sui atomicity semantics are Sui-owned; EVM callback
semantics are never merged into Sui readers and vice versa.

## PTB atomicity (official citation, fetched 2026-11-14)

Source: https://docs.sui.io/develop/transactions/ptbs/prog-txn-blocks (official Sui
docs). Verbatim quotes:

- Atomicity: "The runtime applies the effects of each transaction command in the
  block, atomically at the end of the transaction."
- Failure: "If one transaction command fails, the entire block fails and none of the
  effects from the commands apply."
- Ordering/chaining: "The individual transaction commands within a PTB execute in
  order." / "You can use the results from one transaction command in any subsequent
  transaction command within the PTB."
- Size: "A PTB can perform up to 1,024 unique operations in a single execution".
- Gas: "At the beginning of execution, the system withdraws the maximum gas budget
  (in terms of SUI) from the gas coin." / "The system returns any unused gas to the
  gas coin at the end of execution".

## What this means for flash-borrow → use → repay

- A flash loan (e.g. DeepBook V3 `borrow_flashloan_base` returning the
  `FlashLoan` hot potato) can be borrowed, swapped, and repaid **inside one PTB**:
  the repay command consumes the hot-potato receipt, and Sui Move's linearity makes
  an unreplied hot potato impossible to drop — an unrepaid loan aborts the whole
  PTB (DeepBook docs: "The entire PTB reverts."). This is local atomicity by
  construction, no receiver contract needed (unlike EVM).
- `src/multichain/sui.py` (`SuiPtbAdapter.compile`, `SuiHotPotatoObligation`,
  `SUI_HOT_POTATO_NOT_CLOSED`) is the canonical runtime model of exactly this
  invariant — read-only context; this wave adds no code.
- Gas budget must cover the whole PTB (withdrawn up-front); gas coin is an owned
  object and must not be consumed as a trade object (modeled by
  `SUI_GAS_OBJECT_REUSED`).

## Discovery vs capital (repo vocabulary — binding)

- **DEX state** (Cetus CLMM pool balances/price/ticks, Aftermath AMM pools, FlowX
  routes, DeepBook orderbook depth) is *discovery/quote* evidence: shared-object
  state that advances per checkpoint; reading it is a market-data concern.
- **Lender capacity** (DeepBook pool/vault balances behind `borrow_flashloan_*`,
  any future Cetus/Aftermath flash API) is *capital* evidence: it qualifies a
  `FlashCapitalEdge` and requires governed checkpoint-consistent reads with
  independent quorum per the R02-CAP-C reader standard. The same shared object can
  back both surfaces — one capital resource, one capacity number, no double count.
- UNKNOWN is not zero: until a governed capacity read exists, every lender capacity
  in this bundle is **UNKNOWN** (never modeled as 0).

## Comparison table (cross-domain, isolation preserved)

| property | EVM | Sui |
|---|---|---|
| atomic unit | transaction + callback | PTB |
| borrow/repay binding | callback must repay before return (Aave `executeOperation`, Euler `onFlashLoan`, Morpho `onMorphoFlashLoan`) | hot-potato receipt must be consumed in-PTB (DeepBook `FlashLoan`) |
| receiver auth | deployed receiver contract mandatory (gas cost) | no receiver contract; caller composes PTB |
| failure semantics | whole tx reverts | whole PTB reverts, no effects applied |
| receipt type | `bool` return + allowance/pull | linear hot potato (no abilities) |
| runtime model owner | `src/multichain/evm_financing.py` | `src/multichain/sui.py` |

Typed blockers: none new from this note itself; per-source blockers live in the
per-source dossiers. The EVM↔Sui correspondence above is an editorial aid only —
adapters must not share code across domains.
