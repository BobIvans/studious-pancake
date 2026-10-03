# «Весь рынок на ладони»: read-only интерфейс

Это спецификация будущего UI, не собранное приложение. Главный экран показывает карту поддержанного universe и степень достоверности, а не обещание видеть каждую площадку Web3.

| Экран | Содержимое | Пользовательский результат |
| --- | --- | --- |
| Overview | Domains/strategy families, discovered/bound/qualified/fresh, source lag, coverage denominator | Понять, какая часть рынка действительно наблюдается |
| Market map | Bounded subgraph, pools/orderbooks/rights, направления преобразований | Найти связанные рынки без миллиона одновременно показанных nodes |
| Route detail | Ordered legs, integer amounts, costs, state/slot/version, repeated resources | Объяснить кандидат и причину rejection |
| Capacity | Exact sampled amounts и conservative net с funding/resource caps | Сравнить размеры без scaling одной quote |
| Source trace | Primary source, receipt, decoder/version, available_at и admission status | Проследить происхождение каждого числа |
| Research packs | Async horizons, rights/expiry, assumptions, blocked/unverified | Не путать разные продукты и виды финансирования |

Фильтры: chain/domain, asset address, product/maturity, venue/program, family, source, freshness, evidence class, atomic/async, max hops, selected amount. Тикер поиска всегда раскрывает chain/address. Пользовательский selection не изменяет canonical identity.

Предлагаемые UI caps:200 visible nodes и500 edges с pagination/drill-down; это presentation policy, не изменение graph/search limits. Aggregated edge раскрывает underlying markets и не суммирует повторяющуюся liquidity. Missing global denominator явно подписан.

Node/edge статусы имеют текст и цвет: discovered, schema-tested, decoded, exact-qualified, fresh, stale, gap, blocked, unsupported. Mobile layout: overview → список маршрутов → detail; graph — вспомогательный режим. Выбранный amount и timestamp всегда рядом с цифрами output/net.

No wallet connection, balances acquisition, trade button, auto-execution or live permission. Экспортировать можно read-only evidence bundle и corpus references без credentials. UI не повышает eligibility и не вызывает signing/submission.
