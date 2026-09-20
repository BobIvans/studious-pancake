# AGG-03 — Jupiter Lend, Slumlord и installed paper pipeline

## Текущее состояние после AGG debt reconciliation

Исходный AGG-03 был merged как source-level/default-off slice в PR #495.
После него AGG-01 (#501) добавил lender-neutral financing contracts, а все
AGG-01…15 теперь присутствуют в `main`. Эта debt-closure ветка завершает
оставшийся **code-side** seam AGG-03 без включения live:

- concrete unsigned `JupiterLendFinancingPort`;
- concrete unsigned `SlumlordFinancingPort`;
- adapter в существующий `AtomicMarginfiJupiterPlanner`, без второго planner;
- PRIMARY + RENT obligations в одном immutable message;
- Slumlord order: rent borrow → primary lender/Jupiter route → cleanup →
  Slumlord repay → CheckRepaid;
- lender/generation/program/evidence identity в planner provenance;
- lender-neutral repayment bundle и canonical economic reconciliation;
- post-simulation repayment decoder boundary;
- non-MarginFi CORE-V1 composition через те же lifecycle/capital/runtime owners;
- installed default-off profile `core-jupiter-lend-jupiter-v1`.

`MarginFi` legacy profile не переименовывается и сохраняет generation 1.
Новый profile не получает operational admission из-за самого наличия adapters.

## Provenance

### Slumlord

- upstream: `igneous-labs/slumlord`
- commit: `5c5565cb106f5316a66df8ba616034a7810fa850`
- instructions blob: `9755520565f83dd2ee9f02bcc2651e193e669dcc`
- library blob: `03b41179d6e50b745ee9b9e6273753f0b9fb39b1`
- program: `s1umBj7CEUA6djs6V1c6o2Nym3QrqF4ryKDr1Nm1FKt`

Source-level builders, PDA/state semantics and Borrow → Repay → CheckRepaid
ordering are retained. Borrow has no invented amount field and preserves
reserve-balance-minus-one semantics.

### Jupiter Lend

- upstream: `jup-ag/jupiter-lend`
- commit: `33a22cf7a5bfdd32ab1712dda4adfbeb9b348ad9`
- flashloan IDL blob: `0d0ae6d624b33355315e98baaf0a5d00d317beb8`
- IDL version: `0.1.4`
- program: `jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS`

The local bridge remains unsigned and does not import an unverified npm runtime.

## Dependency reconciliation

The historical merge order was not the master DAG order. That is recorded in
`config/agg_merge_receipts.json` and checked by
`src/release_gate/agg_debt_closure.py`. It is no longer a current prerequisite
blocker: AGG-01 and AGG-02 are both merged and the financing seam is now
integrated into the canonical planner/composition.

Resolved stale blockers:

- `AGG03_GENERIC_FINANCING_SEAM_MISSING` — **resolved code-side**;
- `AGG03_PREREQUISITE_EQUIVALENCE_UNPROVEN` — **resolved dependency-side**;
- `AGG03_ACCOUNT_LIFECYCLE_NOT_INTEGRATED` — code-side ordered RENT bookends
  and shared canonical message are implemented; real-state prefix solvency still
  requires qualification evidence.

## Remaining blockers are external qualification, not hidden code debt

1. **AGG03_JUPITER_LEND_RUNTIME_STATE_UNQUALIFIED** — current deployed
   reserve/liquidity/rate-model/vault state, fee semantics and account closure
   still require rooted read-only evidence.
2. **AGG03_SLUM_DEPLOYMENT_UNQUALIFIED** — source pin does not prove the current
   on-chain executable, loader/program-data identity, PDA owner/balance or
   deployment generation.
3. **AGG03_FINANCING_REPAYMENT_DECODER_UNQUALIFIED** — code has a mandatory
   post-simulation decoder boundary, but actual Jupiter Lend + Slumlord
   deployment decoders need loaded-state vectors and independent conformance.
4. **AGG03_FULL_MESSAGE_EXTERNAL_CONFORMANCE_UNPROVEN** — immutable ordering is
   implemented, but exact loaded-state/fork simulation evidence for the selected
   deployment/profile generation is still required.
5. **AGG03_PREFIX_SOLVENCY_EVIDENCE_MISSING** — network fee, ATA/WSOL/rent and
   protected-inventory cashflow need a real/recorded qualified state campaign.

These blockers must remain fail-closed; none may be converted to success by
unit tests or fabricated network output.

## Status

- implementation: **IMPLEMENTED_OFFLINE / merge pending for this closure diff**
- operational: **UNQUALIFIED**
- sign: **disabled**
- send: **disabled**
- live: **disabled**
- automatic scale-up: **disabled**

After merge, the implementation status may be recorded as `MERGED_CODE`, but
operational qualification still requires a new exact campaign bound to the
merged source/wheel/config/program generations.
