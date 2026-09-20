# AGG-03 — Jupiter Lend, Slumlord и installed paper pipeline

Статус этого change-set: **IN_PROGRESS / IMPLEMENTED_OFFLINE**.

Этот PR является независимой, mergeable частью AGG-03. Он не объявляет весь
AGG-03 завершённым и не меняет operational/live status.

## Base и effect boundary

- base: main at 0c4f216a62d62b20f6fb4ec4bbd0548cea58df65
- branch: codex/agg-20260920-03
- effect scope: LOCAL_BUILD_TEST only for the new adapters
- SIGN: отсутствует
- SEND: отсутствует
- live activation: отсутствует

На base installed paper path по-прежнему создаёт
CoreV1ReleaseProfile(lender="marginfi") и передаёт dependencies=None.
Это не изменяется данным PR, потому что canonical planner, exact-attempt
provider evidence и raw economic reconciliation всё ещё содержат MarginFi-
specific contracts. Подмена только runtime resolver без миграции этих owners
создала бы второй, недоказанный путь.

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

## Exact blockers before AGG-03 can be COMPLETE

1. **AGG03_GENERIC_FINANCING_SEAM_MISSING** — CoreV1Dependencies,
   AtomicPlannerRequest/Planner provenance, ProviderExecutionEvidence and raw
   reconciliation still encode MarginFi as the financing authority.
2. **AGG03_PREREQUISITE_EQUIVALENCE_UNPROVEN** — AGG-01 and AGG-02 are required
   package dependencies by the master plan, but current main contains no merged
   AGG-01/AGG-02 identities. Existing historical owners must be reconciled before
   migration rather than duplicated.
3. **AGG03_JUPITER_LEND_RUNTIME_STATE_UNQUALIFIED** — the public IDL is pinned,
   but reserve/liquidity/rate-model/vault account closure, live fee/status
   evidence and package-integrity decision are not yet bound to the installed
   runtime.
4. **AGG03_SLUM_DEPLOYMENT_UNQUALIFIED** — pinned source is sufficient for
   source-level builders, not for deployed executable hash, current PDA balance,
   account owner observation or network compatibility.
5. **AGG03_FULL_MESSAGE_COMPATIBILITY_UNPROVEN** — Slumlord CheckRepaid and
   Jupiter Lend payback constraints require exact final-message proof; guessing
   an order is forbidden.
6. **AGG03_ACCOUNT_LIFECYCLE_NOT_INTEGRATED** — ATA/WSOL/rent prefix solvency,
   shared Slumlord resource reservation and protected-inventory proof are not
   wired into canonical owners.

## Next resume

RESUME
AGG_ID: AGG-03
branch: codex/agg-20260920-03
base_sha: 0c4f216a62d62b20f6fb4ec4bbd0548cea58df65
implementation_status: IMPLEMENTED_OFFLINE for Slumlord/Jupiter-Lend low-level adapters; AGG-03 overall IN_PROGRESS
operational_status: UNQUALIFIED
completed evidence: source pins, unsigned builders, state/order checks, focused tests
next concrete change: migrate the canonical financing request/evidence seam in the AGG-01 compatible owner, then supply a verified installed dependency resolver instead of dependencies=None
do not: create a second runtime/planner/ledger, fake provider evidence, enable live, sign or send
