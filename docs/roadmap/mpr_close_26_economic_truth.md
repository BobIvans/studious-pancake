# MPR-CLOSE-26 — Finalized economic truth and lineage quarantine

This slice implements an offline acceptance gate for the **MPR-26 Finalized Economic Truth, Settlement Semantics, Lineage Quarantine** roadmap item.

## What this adds

- `src/economic_truth_pr26.py` defines four separate canonical economic schemas:
  - `QuoteEconomics` for provider/route quote economics;
  - `SimulationEconomics` for exact message simulation economics;
  - `PaperEconomics` for sender-free estimated paper outcomes;
  - `FinalizedChainEconomics` for finalized-on-chain payer/token deltas.
- `ReportMetric` and `evaluate_economic_truth_bundle(...)` prevent report rows from collapsing different lineages into one PnL bucket.
- `evaluate_instruction_firewall(...)` fails closed for unknown writable/signing accounts, hidden tip transfer outside same-message policy and mutable compute-budget changes after final simulation.
- `JitoSettlementEvidence` treats bundle ACK/landed as transport evidence only; uncle/rebroadcast remains fail-closed; finalized Jito evidence must bind exact message digest and signature.

## Safety boundary

This PR does **not** enable live trading, signing, senders, RPC calls, Jito submission, provider calls or runtime promotion. It is a deterministic standard-library-only gate that future active paper/live code must satisfy before claiming realized settlement or production-ready economics.

## Acceptance focus

```bash
python -m py_compile src/economic_truth_pr26.py tests/test_mpr_close_26_economic_truth.py
python -m pytest -q tests/test_mpr_close_26_economic_truth.py
pytest -q tests -k "settlement or economic or reconciliation or lineage or jito or account_lifecycle or wsol or ata or rent"
```

## Follow-up wiring

Later MPR-24/MPR-27/MPR-28 work should feed this gate from the active paper vertical, release evidence artifacts and bounded canary permit path. Until finalized transaction proof exists, paper outcomes must remain `paper_estimated` and cannot be reported as realized PnL.
