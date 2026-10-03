# Flashloan как ограниченный источник временного капитала

Полезный вопрос: какой exact amount оставляет максимальный обоснованный net result при конкретном состоянии? Самая большая доступная сумма не обязательно выгодна: price impact и дополнительные издержки могут сделать её убыточной.

## Что надо проверить у lender

| Lender / источник | Identity ресурса | Capacity evidence | Граница |
| --- | --- | --- | --- |
| [Aave V3](https://www.aave.com/docs/aave-v3/guides/flash-loans) | EVM deployment/reserve/asset | Reserve cash plus flags, premium, callback and eligibility | One transaction; selected repay mode only; Multiasset flashLoan has different options from flashLoanSimple |
| [Morpho Blue](https://docs.morpho.org/developers/contracts/blue/) | EVM deployment/token balance | Actual whole contract token balance; common resource across markets | Callback repayment within transaction; Do not sum per-market liquidity as independent flash reserves |
| [Balancer V3](https://docs.balancer.fi/concepts/vault/flash-loans.html) | Vault/token and unlocked context | Actual available token balance and Vault accounting constraints | Close deltas and settle in transaction; Current linked guide is V3; fees must be pinned to deployed rules |
| [Uniswap V3](https://developers.uniswap.org/docs/protocols/v3/guides/flash-swaps/getting-started) | Pool/token0/token1 | Actual pool balances plus lock/callback restrictions | Pool callback debt closes in transaction; Lender pool and swapped pools can be conflicting resources |
| [Kamino](https://github.com/Kamino-Finance/klend) | Solana program revision/reserve/mint | UNVERIFIED in this research; inspect deployed program and accounts | Must prove borrow/repay instruction conformance; Reuse lending owner; no fresh network or program-conformance test |
| [Project 0 / mrgnLendv2](https://docs.marginfi.com/) | Solana program/bank/mint | UNVERIFIED; SDK naming changed in docs | Do not infer legacy flash semantics from product homepage; Cross-venue collateral is a separate persistent health constraint |

Все currently_usable_atoms в matrix равны null: текущие reserve balances и deployment conformance не проверялись. Null означает неизвестно, не нулевую ликвидность. Не связывать dashboard TVL напрямую с полем max_flash_amount.

## Exact economics

Для одноактивного closed loop при стандартном repay:

`modeled_net(q) = final_output(q, shared_state) − q − loan_fee(q) − transaction_cost − tip − other_incremental_costs`.

Swap fees, price impact и поддерживаемые transfer fees уже должны быть включены в exact leg output; нельзя вычесть их второй раз. Slippage buffer — консервативный reserve/ограничение, а не обязательно реализованный расход. Версионный cost contract явно говорит, какие компоненты embedded, какие external и что является uncertainty reserve. Gas/rent учитываются в их native units; если для comparison используется перевод в base asset, требуются rate evidence и adverse bound. Финальное repayment всё равно per-asset.

В `PR118` переиспользовать integer/non-monotonic sizing. Его текущий SOL/WSOL lamports contract нельзя обходить сменой названия asset. Multiasset generalization — отдельное расширение владельца с unit-safe adapter и acceptance, а не новый дублирующий optimizer. Старый monotonic bounded_amount_search в durable reservations не заменяет PR118.

Для каждого sampled q сохранять output, fees, reject reason, state/evidence hash и remaining capacity. Допустимы немонотонные области из-за tick/lot/dust/fee boundaries, поэтому binary search без доказательства монотонности не обоснован. Best sampled q не означает глобальный continuous optimum.

## Совместное состояние и flash capacity

В одном плане несколько путей используют один evolving state fork. Borrow, swaps, redemption и repay имеют упорядоченные effects. При multiasset funding требуется closing vector: каждый долг закрыт в своём активе до своей lender boundary; положительный USD equivalent не компенсирует недостающий один atom.

Несколько loans могут последовательно использовать возвращённый cash в одной предусмотренной модели, если это разрешают lender semantics и порядок. Это не новая одновременная ёмкость. Для внешних неизвестных outcomes повторное использование требует canonical evidence по принятой reconciliation policy. Несколько рынков Morpho, один balance Vault или virtual balances maker нельзя суммировать как независимые деньги.

Netting и внутренний flash accounting могут уменьшить gross transfers и потребность в funding. Они не создают ликвидность, не снимают access predicates и не заменяют обязательства по repayment. Callback/reentrancy locks могут запретить путь через тот же lender pool даже при привлекательной арифметике.

## Агрегация нескольких lenders

Для каждого совместимого lender формировать amount-specific funding alternative: available cash, fee curve, дополнительный transaction cost, доступ, locks и repayment boundary. Сначала сравнить single-lender варианты при одном и том же route state. Если profitable route capacity превосходит один источник, исследовать bounded split funding между двумя lenders в том же settlement domain, с общей векторной моделью cashflows.

Нулевая объявленная loan fee не означает минимальный полный cost: callback composition, token transfers, gas, lock conflicts и дополнительные failure modes могут сделать другой источник выгоднее. Порядок nested callbacks и возможность повторного входа квалифицируются по конкретному deployed code. Один underlying balance, доступный через несколько interfaces, остаётся одним ресурсом. Не суммировать cash на разных chains для одного atomic loan.

Feasible amount set — пересечение условий точного trade state, lender terms, debt closure, account/transaction capacity, eligibility и deadline. Оно может быть немонотонным. Поэтому сравнивается конечная допустимая сетка с net objective, а не просто самый большой доступный principal. Multi-lender исследование добавляется в existing financing owner после квалификации одного lender; в этом пакете оно не реализовано.

## Параллельность loans

Offchain workers независимо проверяют кандидатов. Затем scheduler выбирает совместимую волну и конкретный порядок для зависимых операций. Общий reserve, market vault, payer, nonce, gas object или margin account ограничивает concurrency. Никакой фиксированный «максимум параллельных flashloans» из общего TVL вывести нельзя.

Lender-scoped atomicity сохраняется независимо от транспорта. [Jito](https://docs.jito.wtf/lowlatencytxnsend/) отдельно описывает риск rebroadcast отдельных transactions из skipped blocks. План поэтому не полагается на один bundle как универсальное обеспечение долга, открытого в другой транзакции.

## Что flashloan не финансирует

Resting maker orders, длительный hedge, обычное cross-chain reimbursement, maturity, unstaking queue, delayed issuer redemption и collateral поддерживаемой позиции требуют inventory или другого разрешённого финансирования. Aave debt-conversion option тоже требует collateral/delegation; она не превращает невозвращённый flashloan в бесплатный carry.

Именно поэтому funding graph, inventory graph и execution graph связаны, но имеют разные ресурсы и горизонты. Капитал для failed transaction fees и операционных расходов также не равен временно заимствованному principal.
