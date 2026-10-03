# Как находить новые отношения и не перепутать их с арбитражем

Есть три разных объекта: точное экономическое тождество; статистическая связь; гипотеза без доказательств. Они имеют разные типы в relation registry. Корреляция может помочь shortlist, но не даёт операции, которой можно вернуть flashloan.

## Поиск от прав и cashflows

Сначала связать продукты по одному underlying, collateral, issuer, maturity, settlement index и доступному conversion. Проверить quantity multipliers, decimals, rebases, haircut, transfer fees и settlement conventions. Native/bridged/staked/wrapped формы имеют явные отношения с направлениями и условиями; объединять их по символу нельзя.

Примеры структурных гипотез: share versus underlying basket; immediate wrapper conversion; SY versus PT+YT при правилах продукта; полный outcome partition; liquidation reward versus unwind depth. Цена и курсы здесь лишь входы. Само тождество подтверждается правами и операциями продукта.

## Поиск статистических отношений

Не считать все пары всех токенов на каждой итерации. Разделить universe по доказанным economic families, общим факторам, maturity и settlement domain. Обновлять residual features только затронутых групп. Approximate nearest neighbors и embeddings могут выбирать кандидатов для исследования; они не подтверждают identity и не заменяют exact evaluation.

Для каждой гипотезы заранее записать: список инструментов, признак, lookback, lag, sampling rule, transaction-cost model, endpoint доступности данных, критерий отбраковки и семейство множественных сравнений. Выбор pairs/lags на train и подбор thresholds входят в число проведённых исследований. Не сохранять только удачные опыты.

| Гипотеза | Что измерять | Проверка, которая может её опровергнуть |
| --- | --- | --- |
| Lead/lag между площадками | Returns/residuals с реальными available_at | Добавить задержки/сдвиги timestamps и исключить искусственную предсказуемость |
| Price residual в stable family | Executable bid/ask с fees и depth | Депег или inaccessible conversion разрушает предполагаемую связь |
| Funding curve | Funding schedule, index, basis и collateral cost | Изменение funding, margin shock, невозможность закрыть hedge |
| Flow-induced inventory pressure | Net flow с правильной дедупликацией | Исключение incentives, own transfers и routing double counts |
| Общий liquidation event | Borrower state, oracle update, unwinding depth | Опоздавший event или конкурирующее погашение устраняет возможность |
| Новый продукт | Cashflow rights и доступный conversion | Неполные права или delayed settlement переводят задачу в inventory |

## Проверка качества

1. Зафиксировать raw manifest и feature cutoff. Историческое решение не видит данные, которые появились позже, даже если provider timestamp старый.
2. Применить chronological train/validation/final holdout. Исключить пересекающиеся label horizons; embargo выбирается по максимальному горизонту воздействия/holding, а не произвольному числу строк.
3. Учесть serial dependence: один shock с тысячей updates не равен тысяче независимых экспериментов. Использовать event clusters/block resampling и effective episodes.
4. Запустить latency null, independent-series null, shifted labels и ablations. Выбранная коррекция множественных тестов должна учитывать зависимость; простое независимое предположение не объявлять доказанным.
5. Проверить executable amounts, turnover, spread, fees, gas, data/compute cost и допустимую inventory модель. Даже устойчивое предсказание может не покрывать издержки.
6. Для лучших кандидатов спроектировать forward shadow. Small sample остаётся UNKNOWN; красивый in-sample Sharpe не основание расширять капитал.

`src/mechanism_discovery/research_quality.py` уже содержит purged walk-forward helpers. `src/market_data_evolution/contracts.py` владеет point-in-time evidence. Их нужно расширять необходимыми controls, а не объявлять наличие helper-функций полноценной statistical validation platform. `causal_twin.py` replay с замороженным flow не доказывает, как реальные участники изменят поведение.

## Автоматическая эволюция

Hypothesis worker может предлагать relations и experiments из нового schema/protocol/event. Он не должен сам давать своим предложениям статус verified. Независимый deterministic evaluator проверяет amounts и cashflows; отдельная research review проверяет temporal leakage и selection bias. Негативные результаты, доступность и причины отказа сохраняются с версией, чтобы не переоткрывать одну ложную гипотезу каждый день.

Drift watch следит за изменением decoder, прав, комиссий, correlations и liquidity regime. При drift evidence становится нуждающимся в новой проверке; это не команда удвоить polling или капитал. Все automation profiles в архиве disabled, schedule=null.

Выгода от наблюдения большого рынка — больше проверяемых гипотез и лучшее понимание ограничений. Она не означает, что все корреляции являются прибыльными сделками.
