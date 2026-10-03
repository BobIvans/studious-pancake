# MML-03 — Custom accounting и будущие финансовые продукты

**PLANNED_NOT_RUN.** Код не написан, experiment не запущен.

Зависимости: CLR-03, MML-02. Связанные задания: WG-16, WG-27.

## Гипотеза

Одна новая accounting/transformation rule может уменьшить transfers или открыть полезный продукт при явных obligations.

## Переиспользовать

- `src/mechanism_discovery/hook_native.py`
- `src/mechanism_discovery/claims.py`
- `src/mechanism_discovery/pr356_state_machine.py`
- `src/mechanism_discovery/mechanism_compiler.py`

## Дизайн эксперимента

1. Сперва baseline flash-accounting delta model и один simple wrapper/conversion; затем отдельно fixed/floating rights или PT/YT при verified adapter.
2. Hook identity включает domain, PoolKey, hook address/permissions/code revision и reachable mutable configuration; shared hook state может связывать несколько pools.
3. Все transient balances закрываются на правильном boundary; нельзя считать внутренний delta всемирной credit line.
4. Custom accounting changes переводят evaluator в другую model revision; unsupported hooks fail closed, не стандартная AMM formula.
5. Переиспользовать существующие research model/contracts; только offline model/local fixture evaluation без deployment, signer или submission. Сравнить с application-level implementation.

## Измерения

- transfers/resources saved
- capital requirement by asset
- obligation closure
- rights/capacity failures
- model complexity and verification cost
- new user outcome availability

## Когда продолжать

Конкретная полезная capability с exact invariants и after-cost advantage; отсутствующая liquidity/distribution — explicit product blocker.

## Когда остановить или изменить гипотезу

Если решение требует собственной chain до доказанного workload/demand bottleneck, отложить L1/L2/L3 и сохранить application baseline.

## Результат будущей работы

One-product mechanism dossier, compatibility/identity rules и application-vs-chain decision criteria.

Все outcomes сейчас NOT_RUN, demand UNKNOWN. Любой внешне наблюдаемый результат должен иметь scope/evidence; synthetic profiles не выдаются за реальных клиентов или providers.
