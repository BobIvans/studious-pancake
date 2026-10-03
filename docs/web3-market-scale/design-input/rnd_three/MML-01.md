# MML-01 — Dynamic fee против фиксированной комиссии

**PLANNED_NOT_RUN.** Код не написан, experiment не запущен.

Зависимости: RD-00. Связанные задания: WG-27.

## Гипотеза

Одна ограниченная fee rule может менять balance trader/LP outcomes в конкретных рыночных режимах.

## Переиспользовать

- `src/mechanism_discovery/hook_native.py`
- `src/mechanism_discovery/research_quality.py`
- `src/mechanism_discovery/causal_twin.py`

## Дизайн эксперимента

1. Отдельный pinned EVM/v4 fixture. Фиксированный pool type, начальная liquidity, external reference process и request stream.
2. A: fixed fee. B: один dynamic-fee rule с lagged observable volatility/depth input и fee bounds. Изменять один фактор, параметры выбирать на training, замораживать на held-out.
3. Пересчитать counterfactual state path, fills и fees; нельзя взять observed historical trades как гарантированно неизменные при новых fees.
4. Phase1 frozen-demand replay — результат условен. Phase2 stress demand elasticity/order abandonment, stale oracle, jump/depeg, congestion и adversarial timing.
5. Разложить per-user execution, LP fees и inventory markout, solver net и compute/gas cost. Fee transfer от trader кLP сам по себе не общий economic gain.

## Измерения

- trader cost/slippage/fill
- LP fees plus inventory value under explicit valuation
- solver after-cost result
- order abandonment
- gas/compute overhead
- sensitivity to demand response

## Когда продолжать

Нет нарушений state/fee invariants; tradeoff и неопределённость измерены. Кандидат проходит только заранее выбранную цель с guardrails для остальных участников.

## Когда остановить или изменить гипотезу

Более высокая fee revenue при ухудшении итогового LP outcome или collapse flow не называется улучшением рынка.

## Результат будущей работы

Fee mechanism dossier с conditional counterfactual results, constraints и negative regimes.

Все outcomes сейчас NOT_RUN, demand UNKNOWN. Любой внешне наблюдаемый результат должен иметь scope/evidence; synthetic profiles не выдаются за реальных клиентов или providers.
