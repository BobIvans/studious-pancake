# Все обсуждённые стратегии

Приоритет ниже — порядок инженерного исследования, не рейтинг доказанной доходности. Присутствие source в строке означает кандидат для данных/документации, не поддержанный connector.

| ID | Семейство | Задания | Owners | Candidate sources | Требуемые данные | Funding | Ограничения масштабирования |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | Multi-path / split-flow | WG-11 WG-12 | O01 O09 O10 O11 | raydium orca meteora-dlmm meteora-damm uniswap curve balancer jupiter | Pool/account state и shared resource replay | В одном atomic domain при доказанном repayment | Capacity after costs; shared liquidity, fixed costs, CU/message bounds |
| S02 | Stable/correlated assets | WG-13 | O01 O04 O13 O22 | curve balancer raydium orca pyth-hermes switchboard | Exact depth + depeg/redemption evidence | Условно: только немедленные операции в одном domain | Small spread, depeg, stale oracle; correlation ≠ identity |
| S03 | DEX ↔ mint/redeem/wrapper | WG-14 | O24 O25 | sanctum kamino marginfi aave morpho | Exchange rates, права, caps, fees, queues | Immediate conversion — возможно; async queue — нет | Eligibility, pause, cutoff, rights transfer, latency/capital lock |
| S04 | Liquidation + collateral sale | WG-15 | O18 O20 O21 | kamino marginfi aave morpho pyth-hermes | Debt/collateral/oracle + exact unwind | Условно, если protocol и atomic repayment доказаны | Close factor, bonus, competition, shared collateral and pool liquidity |
| S05 | PT/YT и composite products | WG-16 | O22 O24 O25 | pendle uniswap | Vector claims, SY rates, maturity and pool state | Только для конкретного проверенного atomic recipe | Maturity, negative yield, fees, vector conservation |
| S06 | Intent / batch solver | WG-17 WG-26 | O10 O11 O26 | cow-protocol 0x 1inch jupiter | Intent rules, auction snapshot, exact external routes | Один из вариантов financing, не доступ к order flow | Access, limit prices, deadlines, partial fills, inventory and surplus ownership |
| S07 | Cross-chain / CEX–DEX / spot–perp basis | WG-18 WG-19 WG-20 | O19 O22 O23 O24 | ccxt cryptofeed binance-spot coinbase-exchange kraken bybit okx-cex defillama | Domain-separated depth, funding, borrow, finality/withdrawal terms | Обычный atomic flashloan не финансирует междоменное ожидание | Inventory, bridge/CEX settlement, margin, funding and hedge risk |

## Market-of-Markets

| Продукт | Задания | Переиспользовать | Критерий полезности |
| --- | --- | --- | --- |
| Общий clearing solver | WG-26, WG-17, WG-12 | AGG-05, route graph, intent/claims IR | Улучшение заданного outcome после costs относительно independent execution |
| Рынок проверяемых расчётов | WG-25 | Existing INST-01 procurement institution | Проверяемые accuracy/latency/cost; demand без субсидий — отдельный эксперимент |
| Лаборатория новых market mechanisms | WG-27 | Mechanism-discovery contracts, claims и institution owners | Воспроизводимое сравнение rules, fees, allocation и incentive scenarios |

Порядок расширения: сначала измерить exact capacity нескольких существующих markets; затем shared-state split-flow; далее product conversions с доказанными правами. Cross-chain/CEX/perp используются для отдельного inventory research. Их объем нельзя включать в доступную atomic flashloan capacity.

Флешзаём увеличивает временно доступный principal только при допустимом заимствовании и своевременном repayment. Он не исправляет отсутствие spread, плохую глубину, неподтверждённое состояние или задержку settlement. Никакая доходность, масштаб капитала или выигрыш конкуренции здесь не обещаны.

В техническом пакете S01–S07 покрыты полностью на уровне целей, dependencies, owners, tests и blockers. Реализация каждого market adapter и соответствующая эмпирическая квалификация остаются будущей работой.
