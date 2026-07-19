# PR-005 transaction lifecycle

Checked on 2026-07-19 against the official contracts recorded in `docs/external_contracts.yaml`.

The only live execution path is:

`TradePlan -> TransactionCompiler -> Structural Validation -> RPC Simulation -> Cost Reconciliation -> ExecutionDecision -> Signing -> Submission -> Confirmation -> Balance Reconciliation`.

Providers provide normalized instruction bundles and metadata. They do not choose blockhashes, compile full transactions, sign, simulate, submit, retry, mark landing, or fabricate paper-mode success.

## MarginFi flash loans

MarginFi flash loans are modeled as `start_flashloan(end_index)` and `end_flashloan(projected_active_balances)` around ordinary lending borrow and repay instructions. The compiler computes the final end instruction position in pass 1 and only builds the start instruction in pass 2.

## Shadow mode

Shadow/paper mode can build, sign locally when safe, simulate, and record `WOULD_EXECUTE` or `WOULD_REJECT`. It must not create fake bundle IDs, call confirmation trackers, or record a landed trade.
