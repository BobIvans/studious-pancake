# CLR-02 — Минимальное необходимое финансирование

**PLANNED_NOT_RUN.** Код не написан, experiment не запущен.

Зависимости: CLR-01. Связанные задания: WG-10, WG-12, WG-26.

## Гипотеза

Netting и допустимая перестановка операций могут уменьшать временный дефицит по каждому активу.

## Переиспользовать

- `src/economics/non_monotonic_sizing.py`
- `src/economics/split_flow.py`
- `src/lending/financing.py`
- `src/mechanism_discovery/pr356_discovery.py`
- `src/mechanism_discovery/pr356_state_machine.py`

## Дизайн эксперимента

1. Построить ordered vector balance trace, строго разделяя свободные user balances, недоступные claims, protocol transient deltas и financing obligations.
2. Для фиксированного cashflow schedule считать необходимый additional prefunding по каждому asset из максимального отрицательного допустимого prefix. Не оценивать только terminal net balance.
3. Deferred windows допускают временные deltas лишь при pinned protocol rules и обязательном close на boundary. Flash accounting не является безусловным free flashloan.
4. Borrow amount изменяет fee/repayment; каждый допустимый integer amount и ordering пересчитать. PR118 SOL/WSOL semantics сохраняются; иной settlement не маскировать lamports.
5. Сравнить same feasible fills: baseline funding, netting funding, netting+stateful split. Search ≤5000 evaluations в proposed pilot; exhausted → incomplete.

## Измерения

- peak funding vector by asset
- repayment/fee vector
- capital locked duration
- residual debt
- resource constraints
- conservative net after financing

## Когда продолжать

Меньше financing requirement или выше after-cost outcome на одинаковых feasible fills; все prefixes/deadlines/closure проверены.

## Когда остановить или изменить гипотезу

Если требуется отрицательный недопустимый баланс, один ресурс повторно или неизвестный lender cap — такой рецепт invalid.

## Результат будущей работы

Funding frontier: finite evaluated alternatives с actual prefix/closure evidence.

Все outcomes сейчас NOT_RUN, demand UNKNOWN. Любой внешне наблюдаемый результат должен иметь scope/evidence; synthetic profiles не выдаются за реальных клиентов или providers.
