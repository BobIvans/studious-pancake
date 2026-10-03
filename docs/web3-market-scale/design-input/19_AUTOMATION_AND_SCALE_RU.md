# Автоматизация R&D, скорость и ёмкость

**В этом архиве automation — disabled design, а не запущенный сервис или расписание.** `data/deep_web3_automation_design.json` не исполняемый workflow. Следующая реализация сначала должна автоматизировать воспроизводимый research loop на offline corpus.

## Предлагаемый цикл

| Стадия | Вход / выход | Что останавливает продвижение |
| --- | --- | --- |
| Документы и deployment diff | Версия источника → изменение dossier | Нет подтверждённой версии или конфликт docs |
| Qualification | Raw fixture + independent vectors → модель/контрпример | Identity, rights, rounding или state semantics неизвестны |
| Ingest и invalidation | События → coherent state generation и dirty dependencies | Gap, correction, stale/unsupported commitment |
| Поиск | Dirty bounded subgraph → finite candidates | Explicit search/CPU/deadline cap |
| Exact sizing | Amount grid → per-point result, joint split transitions | Неверные units, неучтённый общий ресурс или debt |
| Replay и benchmark | Capsule → correctness/cost/latency evidence | Hindsight, несопоставимый baseline, отсутствующая лицензия |
| Исследовательский verdict | Evidence → pass/reject/unknown + следующая задача | Нет positive after-cost evidence или полезного workflow |

LLM может предлагать grammar/adapter/test ideas и объяснять evidence. Проверки amount/state/rights детерминированы. Текст источника, model output или выигрыш в synthetic benchmark не изменяет production eligibility и не добавляет провайдера в allowlist.

## Сначала ускорить повторное вычисление

- Построить inverse dependency index: state key → edges/actions → candidates. Ключи включают fees, hooks, allowance, oracle, account health, order nonce и access state, не только pool reserves.
- По событию пересчитывать bounded dirty frontier. Сравнивать после каждой завершённой generation с full recomputation на том же universe.
- Cache key: model revision + complete state evidence + asset identities + integer amounts + rights/context. Не кешировать только пару символов и цену.
- Наборы raw fetch/decode общие для всех трёх продуктов; сохранять lineage и индивидуальные rights. Два API с общим upstream не дают два независимых доказательства.
- Batch независимые reads в пределах quota, coalesce superseded updates только при доказанной snapshot semantics. Orderbook deltas без непрерывной sequence нельзя терять.
- При overflow — gap/incomplete и checkpoint/backfill. Durable cursor без восстановленного state не является готовым snapshot.
- Marginal/approximate prices используют для ranking. Без доказанного bound pruning может пропускать integer/non-monotonic profit; такой поиск помечается truncated/heuristic.

## Предлагаемые начальные пределы

Один domain, один exact model, 3 assets, 4 venues; 3/4-hop routes, 8 amount points, 2 split paths. Существующий graph предел512 edges и default4096 expansions/100 candidates сохраняются. На будущий experiment дополнительно предлагается cap5000 exact edge calls, queue512 pending events и portfolio18 evaluated candidates.

Это разные бюджеты, а не взаимозаменяемые числа. Отдельно измерять и ограничивать route expansions, edge calls, allocations, path permutations, bytes и elapsed time. Текущие runtime defaults не менялись. Для offline-run network/paid budgets равны0. Missing budget останавливает admission.

Масштабировать benchmark ступенями: 10→100→1000 discovery records и1x→10x→100x replay arrival rate, оставляя finite hot graph. Cold metadata не выдавать за exact fresh coverage. Сначала доказать пользу дополнительных рынков; только затем предлагать новые пределы и storage/index partitioning.

## Что измерять

| Группа | Метрики |
| --- | --- |
| Correctness | False admission, mismatch vs full replay, amount/state/model rejection, missing dependency |
| Coverage | Declared universe, discovered, decoded, fresh, qualified, eligible, profitable sampled points, unknown denominator |
| Latency | Source event→available_at→receive→materialize→exact evidence; p50/p95/p99 и queue age |
| Work | Physical requests/retries, bytes, CPU, peak memory, backlog, evaluator calls, truncation fraction |
| Economics | Net by exact size, total cost per useful evidence capsule, fixed source overhead amortization |
| Capital | Peak principal/collateral by asset/domain, time-integrated locked capital, settlement tail, trapped funds |
| Product | Repeat workflow, customer cost reduction, retention, willingness to pay; сейчас UNKNOWN |

Отсутствие opportunities при полном qualified search и остановка по бюджету — разные результаты. При нулевом полезном output cost/opportunity undefined, не0. Unknown coverage denominator не превращать в100%.

## After-cost и масштаб капитала

Для замкнутого atomic route в settlement asset: `net = terminal_output − exact_repayment − external_costs − justified_buffers`. Pool fees, уже вычтенные evaluator, второй раз не списываются. Нативный gas из другого asset требует отдельного budget/valuation evidence. Refundable rent/collateral влияет на peak capital, а невозмещаемая часть — на cost.

Для async flow: по каждому asset/domain считать `capital_time = integral(locked_balance(t) dt)`. В steady state средний занятый inventory связан с admitted flow и средним временем освобождения; это условная модель планирования, не гарантия tail liquidity. Быстрый пользовательский fill не освобождает reimbursement claim.

Для сервисов: `delivered_cost = data + compute + verification + retries + network/storage + support`. Дешёвый supplier полезен только после проверки delivered result. Сначала измерить локальный baseline; hardware/GPU/zk proof не покупать только по заявленной скорости ядра.

## Как выбирать новые рынки

Hard gates: точная семантика, coherent evidence, доступ/rights, доступный hedge/settlement model и полный resource budget. Затем Pareto comparison incremental useful coverage, reuse engineering cost, capital/time, verified margin и customer value. Не заполнять неизвестную доходность воображаемым score.

Против benchmark overfitting: фиксировать finite corpus и seed до сравнения, отделять development/holdout по времени, логировать все проверенные гипотезы, отрицательные результаты и смены параметров. Synthetic examples доказывают инварианты; реальный market advantage требует point-in-time replay и отдельной forward shadow проверки.

## Стадии дальнейшей поставки

1. DP-01: привести границы нового CPMM bridge к строгому квалифицированному контракту.
2. DP-02: один bounded exact shared-state split experiment у AGG05.
3. DP-03/04: incremental replay и цена низкой задержки на том же corpus.
4. DP-05/07: один vault/claim плюс один user-intent workflow; не все EVM/Sui markets одновременно.
5. DP-10/11/12: evidence API, проверка механизма и исследования demand/scale.

Даты и объёмы реального запуска не назначены. Никакой scheduler, background campaign, customer outreach, provider purchase или trade execution этим обновлением не создан.
