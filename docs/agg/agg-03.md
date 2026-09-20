# AGG-03 — Jupiter Lend, Slumlord и installed paper pipeline

Статус после post-AGG reconciliation: **MERGED_CODE / operationally BLOCKED**.

Исторический AGG-03 PR #495 был source-level/default-off tranche. Текущий
reconciliation закрывает его code-integration debt поверх merged AGG-01…15,
не меняя operational/live status.

## Base и effect boundary

- historical implementation base: main at 0c4f216a62d62b20f6fb4ec4bbd0548cea58df65
- AGG-03 merge commit: 693afe31c4cb5d2aa63b84c7aa40c88b115e3c0b
- reconciliation input main: 27875850a88edf102c904e31955e0df8b78b13b4
- effect scope: DEFAULT_OFF_NO_SIGN_NO_SEND
- SIGN: отсутствует
- SEND: отсутствует
- live activation: отсутствует

Исторический tranche не менял installed path. После AGG-01 и этого
post-merge closure lender-neutral FinancingPort теперь подключается к тому же
canonical planner/simulator/orchestrator/lifecycle/capital path. Jupiter Lend
является PRIMARY obligation, Slumlord — RENT obligation; оба входят в одну
immutable final-message sequence. Generic repayment проверяется только после
exact final simulation через lender-specific decoder. Legacy MarginFi остаётся
отдельным generation-1 profile и не переименовывается.

## Реализовано

### SLUM-01 source-level tranche

Добавлен src/lending/slumlord.py:

- immutable upstream pin:
  - repo https://github.com/igneous-labs/slumlord
  - commit 5c5565cb106f5316a66df8ba616034a7810fa850
  - instructions blob 9755520565f83dd2ee9f02bcc2651e193e669dcc
  - library blob 03b41179d6e50b745ee9b9e6273753f0b9fb39b1
- pinned program id and derived slumlord PDA from seed "slumlord";
- strict empty/8-byte debt state decoder;
- outstanding = max(old_lamports - current_lamports, 0);
- Borrow builder with no invented amount field;
- Borrow amount semantics = reserve balance - 1;
- Repay and CheckRepaid builders with exact ordered metas and privileges;
- fail-closed order certificate requiring Borrow -> Repay -> succeeding
  top-level CheckRepaid;
- typed rejection codes for malformed state, wrong identity, active loan,
  insufficient reserve, amount override and invalid order.

### JUP-02 source-level tranche

Добавлен src/lending/jupiter_lend.py на основании официального public IDL:

- repo https://github.com/jup-ag/jupiter-lend
- commit 33a22cf7a5bfdd32ab1712dda4adfbeb9b348ad9
- target/idl/flashloan.json blob
  0d0ae6d624b33355315e98baaf0a5d00d317beb8
- IDL version 0.1.4
- program id jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS
- flashloan_admin PDA derived from the pinned seed/program;
- exact borrow/payback discriminators;
- positive-u64 little-endian amount binding;
- exact 14-account order and signer/writable flags from the IDL;
- fixed ATA/System/Instructions-Sysvar identities;
- fail-closed Borrow-before-Payback and equal-amount certificate.

Этот код не копирует непроверенный npm runtime и не получает signer.
Package integrity/license для npm helper не объявляются проверенными.

## Tests

Добавлен tests/lending/test_agg03_financing_adapters.py.

Матрица проверяет:

- Slumlord upstream identity pins;
- byte-level discriminators и ordered account metas;
- reserve_balance - 1 и отсутствие amount в Borrow ABI;
- saturating outstanding debt;
- active/malformed state rejection;
- обязательный succeeding CheckRepaid;
- Jupiter Lend official IDL identity;
- borrow/payback discriminator + u64 encoding;
- 14 account flags;
- flashloan_admin PDA;
- amount mismatch/reversed order/zero amount rejection;
- sender-free boundary.

## NF disposition этого PR

| NF | Статус в этом PR | Evidence / blocker |
|---|---|---|
| NF-097 | PARTIAL | source/program identity pinned; deployed executable/account evidence ещё отсутствует |
| NF-098 | IMPLEMENTED_OFFLINE | strict PDA/owner/data/lamports state semantics; network observation не выполнялся |
| NF-099 | IMPLEMENTED_OFFLINE | Borrow bytes/metas + reserve-minus-one semantics |
| NF-100 | IMPLEMENTED_OFFLINE | Repay bytes/metas + debt semantics |
| NF-101 | PARTIAL | CheckRepaid builder/order invariant есть; VM reset proof остаётся AGG-04/SIM |
| NF-102 | PARTIAL | source-level order certificate; Jupiter/Slumlord full-message compatibility не доказана |
| NF-107 | PARTIAL | unit/conformance negatives; loaded-state matrix остаётся downstream |
| NF-109 | PARTIAL | official IDL pinned and unsigned builders implemented; runtime account/state resolver unqualified |
| NF-068 | EXISTING_PARTIAL | current JupiterRouterAdapter/build parser уже существует; current network sample not claimed |
| NF-123 | EXISTING_PARTIAL | managed-vs-build separation exists in prior code; no new execution authority |
| NF-103..106, NF-108, NF-114..115 | BLOCKED/NOT_IN_THIS_TRANCHE | требуют lifecycle/capital/shared-resource integration |
| NF-155..158, NF-167 | BLOCKED | canonical installed planner/request/economic evidence remain MarginFi-specific |
| NF-160..162 | EXISTING/PARTIAL | existing firewall retained; financing-specific full-message proof not yet integrated |

## Current closure and remaining qualification blockers

Закрытый code debt:

1. AGG-01 и AGG-02 имеют canonical merge receipts; historical prerequisite
   inversion сохранён только как audit fact.
2. `FinancingPort` имеет concrete Jupiter Lend PRIMARY и Slumlord RENT
   adapters поверх pinned source contracts.
3. Canonical atomic planner принимает lender-neutral PRIMARY financing и
   auxiliary Slumlord rent financing в одной immutable sequence:
   `rent borrow → setup → primary borrow → swaps → primary repay → cleanup →
   rent repay → CheckRepaid`.
4. Provider evidence и planner provenance связаны с lender/program/deployment
   generation.
5. Economic reconciliation принимает primary + auxiliary repayment bundle,
   но только из post-simulation lender decoder.
6. CORE-V1 composition может собрать generic path без второй lifecycle/capital/
   planner authority при наличии qualified primary evidence, rent evidence и
   repayment decoder.

Оставшиеся blockers являются external qualification, а не отсутствующим
code seam:

- **AGG03_JUPITER_LEND_RUNTIME_STATE_UNQUALIFIED** — нужен текущий deployment/
  reserve/liquidity/rate-model/vault evidence и qualified repayment decoder.
- **AGG03_SLUM_DEPLOYMENT_UNQUALIFIED** — нужен deployed executable/PDA owner/
  balance evidence на выбранной generation.
- **AGG03_LOADED_STATE_FULL_MESSAGE_UNQUALIFIED** — нужны loaded-state/fork
  vectors для полного Jupiter + Slumlord + route message.
- **AGG03_ACCOUNT_LIFECYCLE_EVIDENCE_MISSING** — ATA/WSOL/rent prefix solvency
  и protected-inventory behavior должны быть подтверждены exact campaign
  evidence, а не только code tests.

Эти blockers не должны превращаться в `production_ready` от одного CI pass.

## Next resume

RESUME
AGG_ID: AGG-03
merge_commit: 693afe31c4cb5d2aa63b84c7aa40c88b115e3c0b
reconciliation_input_main: 27875850a88edf102c904e31955e0df8b78b13b4
implementation_status: MERGED_CODE with lender-neutral PRIMARY+RENT composition
operational_status: BLOCKED
completed code evidence: pinned adapters, FinancingPort bridges, one-message planner
composition, post-simulation repayment bundle, fail-closed exact identities
remaining evidence: Jupiter Lend deployed state/decoder, Slumlord deployment/PDA,
loaded-state full-message vectors, lifecycle/rent campaign evidence
do not: fake provider evidence, relabel MarginFi, enable live, sign or send
