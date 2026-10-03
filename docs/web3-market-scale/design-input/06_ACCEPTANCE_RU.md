# 89 будущих сценариев приёмки

Это спецификация тестов, а не отчёт об их выполнении. Карточки WG ссылаются на IDs ниже. Existing regression tests сохраняются; новые tests добавлять для новых рисков и связей owners, не для механического зеркалирования кода.

| ID | Группа | Given / When | Expected |
| --- | --- | --- | --- |
| T01 | baseline | main SHA изменился после baseline; повторить owner scan | Сначала обновить owner map, diff и scope; существующий solver не дублировать. |
| T02 | baseline | В checkout есть пользовательские правки | Не перезаписать; изолировать работу и точно перечислить её diff. |
| T03 | identity | Одинаковый тикер/адрес на разных chain или разный genesis | Различные asset identities; atomic route не пересекает settlement domains. |
| T04 | identity | Переставить independent input rows, сохранить семантику | Semantic identity стабильна; evidence identity следует существующему contract. |
| T05 | identity | Изменить amount, fee/decoder revision, slot/hash, provenance или maturity | Соответствующая evaluation identity меняется; cache miss/invalidation. |
| T06 | sources | Один pool обнаружен двумя aggregators | Один physical market, две source receipts; liquidity не складывается. |
| T07 | sources | Timeout/schema drift/пустая успешная page | Разные статусы; только empty response без ошибок, но не proof completeness. |
| T08 | sources | Запись open-source SDK или unknown tier | Не маркировать free hosted/full depth или graph-admitted. |
| T09 | governance | 429 с retry-after, затем outage | Retry/deadline budget сохраняется, physical attempts учтены, bounded stop. |
| T10 | governance | Cancel во время IO или огромный/deep body | Cancellation propagates; ограничение ресурса до парсинга/мутации, secret body не логируется. |
| T11 | governance | Источник без admitted profile или изменённый host | До IO отказ; новый HTTP обход запрещён. |
| T12 | state | Restart с durable cursor, без snapshot | Coverage=unrestored; кандидатов нет до backfill. |
| T13 | state | Одинаковый replay с duplicates/corrections/retractions | Детерминированный final state; retracted evidence не остаётся в routes. |
| T14 | state | Mixed generation, future timestamp, stale/expired edge | Отказ до candidate emission; ни один stale leg не скрывается aggregate age. |
| T15 | state | Slot spread route-wide больше policy при допустимых adjacent deltas | Route отклоняется по общему max-min slot, не только pairwise. |
| T16 | state | Event cap или reorg посреди epoch | Отказ/инвалидация до некорректной публикации; backfill восстанавливает coherent view. |
| T17 | exact amounts | Quote на10; запрос на100 в нелинейном pool | Fresh evaluation на100; multiply-by10 forbidden. |
| T18 | exact amounts | Raw amounts больше2**53; bool/float вместо int | Точные integers сохраняются; неподходящие типы rejected. |
| T19 | exact amounts | Expected leg output12, conservative11; next edge input12 | Текущая guaranteed-output coupling не проходит; нужен exact input11 evaluation. |
| T20 | exact amounts | Input101, consumed100, остаток1; partial depth | Conservation включает residual1; не выдавать как consumed101 или бесплатный дополнительный выход. |
| T21 | AMM | Pinned constant-product vectors: fee/no fee, dust и reserve extremes | Exact integer matches независимому protocol oracle; rounding и fee location совпадают. |
| T22 | AMM | Stable amp/rate изменился; попытка reuse CPMM или старого cache | Правильная model/revision или reject; не переиспользовать чужую curve. |
| T23 | AMM | Missing program/pool type либо unsupported transfer-fee token | Qualified wrapper fail closed; legacy defaults не дают admission. |
| T24 | ticks bins | Swap пересекает tick/bin boundary и ровно истощает segment | Корректные liquidity/fee transitions и integer output. |
| T25 | ticks bins | Missing tick array/bin либо traversal budget exhausted | Неполный quote не считается exact; explicit rejection/budget status. |
| T26 | ticks bins | Два routes касаются разных ranges одного physical pool | Общий mutable identity/state; нельзя удвоить reserves. |
| T27 | orderbooks | Неверный program owner, artifact hash или unverified subscription | Graph admission отклоняет; disabled strategy сохраняется. |
| T28 | orderbooks | Snapshot, несколько deltas, sequence gap, reconnect | Book invalid до resnapshot/checksum; historical gaps сохраняются. |
| T29 | orderbooks | Buy/sell с non-divisible lot input, tiny depth, fee ceiling | Requested/consumed/residual и fee units exact; никакого full-fill claim без подтверждения. |
| T30 | orderbooks | Cancel/replace на best level перед размерным quote | Новая state identity/output; cache старой depth не применяется. |
| T31 | orderbooks | L2 level красивый, но fill guarantee/queue state неизвестны | Research depth quote labelled conditional, не исполнимая гарантия. |
| T32 | economics | Principal100, min_out105, repayment101, other cost2 уже без swap fees | Net2; не вычитать principal ещё раз и не дважды считать embedded fees. |
| T33 | economics | Fee ceiling повышает repayment на1; estimated profit1 | Повторная проверка net: threshold соблюдён либо reject по exact amounts. |
| T34 | economics | Input USDC units передан как lamports или mint приведён uppercase | Asset/unit mismatch rejected; canonical mint не меняется. |
| T35 | economics | Неизвестна стоимость/repayment; financing source другого chain | Нет validated net/atomic label; blocker явен. |
| T36 | circular sizing | Exact 3hop и4hop; затем2hop и5hop в PR559 detector | Первые допустимы при остальных constraints; последние остаются вне его scope. |
| T37 | circular sizing | Один pool повторён через разные provider/direction; затем разные pools одного program | Повтор одного venue rejected; разные markets одного program разрешены. |
| T38 | circular sizing | Permute inputs; одинаковый amount/state/provenance | Те же ordered candidates/ids и bounded stop. |
| T39 | circular sizing | На размере10 отказ/убыток, на20 прибыль, на30 снова убыток | PR118 рассматривает20; monotonic pruning не применяется. |
| T40 | circular sizing | Ищем при max expansions/evaluations/edge cap | Детерминированный bounded result; неполный search не заявляет отсутствия alpha или continuous optimum. |
| T41 | split flow | Две ветви потребляют shared pool/collateral/funding capacity | Sequential replay не выдаёт общий ресурс обеим ветвям целиком. |
| T42 | split flow | A→B order и B→A order дают разные outputs | Оба admissible ordering учитываются в budget; initial state не мутирует. |
| T43 | split flow | Split gross лучше, но fixed common cost делает net хуже single | Выбрать nondominated single; common cost применить один раз. |
| T44 | split flow | Residual debt>0 либо search exhausted | Split promotion отклонить; label finite-grid optimum только при complete enumeration. |
| T45 | correlated | Stable spread меньше costs | Нет positive-net candidate. |
| T46 | correlated | Depeg/pause/redemption rights diverge | Assets не склеиваются; сценарий риска/eligibility отражён. |
| T47 | primary | Immediate wrapper exact conversion с fees/cap | Amount conservation и capacity соблюдены. |
| T48 | primary | Redemption request pending до следующего epoch | Не включать в atomic cycle; хранить duration/capital lock. |
| T49 | primary | Cutoff/eligibility/controller или exchange rate изменились | Invalidate evaluation; не расходовать чужое claim right. |
| T50 | liquidations | Exact debt state, close factor, collateral и unwind | Заем/repay/bonus/unwind amount-coupled; расходы покрыты. |
| T51 | liquidations | Два candidates на одно collateral/borrower или exhausted pool | Existing conflict selector не удваивает resource. |
| T52 | liquidations | Oracle stale / health изменился / позиция закрыта | Liquidation candidate rejected; speculative trigger не заменяет state. |
| T53 | claims | SY input10 порождает PT/YT bundle | Вход тратится один раз; vector conservation вместо двух независимых edges. |
| T54 | claims | PT maturityA с YT maturityB; redemption before cutoff не разрешён | Recipe rejected by rights identity/eligibility. |
| T55 | claims | Maturity/time/index/negative-yield regime изменились | Новая model/state identity; recompute, obligations не исчезают. |
| T56 | intents | Два opposing intents + внешняя route | Оба limit prices/deadlines/fees соблюдены; surplus не double counted. |
| T57 | intents | Partial fill, expired/replayed intent, changed auction id | Fill rules/nonce/auction bound; недопустимые intents исключены. |
| T58 | intents | Лучший gross solver quote имеет inventory/settlement cost | Rank по одинаковому after-cost outcome; no submitted bid. |
| T59 | domains | EVM same address на двух chain; block number одинаковый | Chain/genesis identity различна; block hash/finality обязательны. |
| T60 | domains | Reorg rollback затронул pool and allowance/state evidence | Все зависимые computations invalidated; replay canonical branch. |
| T61 | domains | Неполный Move object/Cosmos module profile | Discovery/reference only; не заимствовать EVM atomicity. |
| T62 | CEX data | REST snapshot плюс WS deltas с gap/out-of-order | Exchange-specific resync/checksum; не применять чужие sequence semantics. |
| T63 | CEX data | BTC spot/perp/future с разным multiplier/expiry | Разные instrument IDs и amounts; mark ≠ executable bid/ask. |
| T64 | CEX data | Public feed доступен, торговые права неизвестны | Read-only status; no trading/funding access claim. |
| T65 | asynchronous basis | CEX–DEX либо обычный bridge transfer требуется между ногами | Atomic flashloan eligibility=false; inventory settlement scenario. |
| T66 | asynchronous basis | Funding sign сменился, margin call, withdrawal задержан | Negative outcomes отражены; hedge/funding/carry учитываются по времени. |
| T67 | asynchronous basis | Одна сторона исполнилась, другая недоступна | Stranded exposure сохранена, не записывается как complete arbitrage. |
| T68 | replay | Цена опубликована позже decision_at; revised historical observation | Available_at filter исключает look-ahead и поздние исправления. |
| T69 | replay | Повтор одного fixture corpus с одинаковыми versions/seeds | Canonical evidence stable; synthetic не маркируется real. |
| T70 | replay | Настройка на training и оценка на held-out outage windows | Разделение сохранено; отчёт включает rejects и opportunity misses, не только winners. |
| T71 | trace cost | От route_id пройти к amount/ledger/state/raw receipts | Полная lineage доступна; key/header/body secrets отсутствуют. |
| T72 | trace cost | Discovered100, exact20, fresh12, configured200; глобальный total неизвестен | Показывать четыре числа и defined denominator; не писать100% Web3. |
| T73 | trace cost | Расходы есть, qualified useful candidates0 | Cost-per-useful undefined; не zero и не скрытая division by zero. |
| T74 | UI | Открыть большой global view на мобильной ширине | Aggregated/partial view bounded; drill-down, не миллионы nodes. |
| T75 | UI | Выбрать stale/blocked edge с gross positive number | Видны age/reason/amount/net unknown; execution affordance отсутствует. |
| T76 | UI | Переключить amount или snapshot generation | Capacity/evidence обновляются; старый result не подписан новым amount. |
| T77 | scale | Изменился один market из множества | Invalidate affected dependency closure; остальные кеши используют корректные version keys. |
| T78 | scale | Burst/reconnectstorm превышают IO/CPU/retention policy | Backpressure/explicit gap/drop status, bounded memory; no invisible lost completeness. |
| T79 | scale | Сравнить old/new на одном corpus/hardware and budgets | Публикуются p50/p95/p99, coverage/accuracy/rejects и cost; unfair benchmark excluded. |
| T80 | services | Два поставщика дали разные decode/exact results | Independent verification определяет pass/unknown; consensus без oracle не достаточен. |
| T81 | services | Duplicate service close или unknown receipt | Existing institution lifecycle не даёт double release; HELD_UNKNOWN сохраняется. |
| T82 | services | Убрать subsidies из procurement experiment | Отдельно demand/quality/cost observations; синтетический спрос не выдаётся за рыночный. |
| T83 | clearing | Netting нескольких rights/asset obligations | Каждый participant получает допустимый outcome; остаточные обязательства явны. |
| T84 | clearing | Clearing меньше swaps, но больше latency/data/compute costs | Польза после всех затрат относительно same-input baseline; отрицательный эффект сохраняется. |
| T85 | mechanisms | Изменить hook/auction fee и allocation rule | Invariant/conservation/incentive tests на зафиксированных сценариях; general proof не заявляется. |
| T86 | mechanisms | L2/L3/L1 proposal без demand или измеренного infrastructure constraint | Decision memo сохраняет application-first option; автоматического launch нет. |
| T87 | release boundary | Shadow pack passes fixtures, но нет verified real subscription | Qualified_fixture status; no live/whole-market assertion. |
| T88 | release boundary | Просканировать changed imports/config/startup/effects | Нет sender, signer, tx submission, live authorization, enabled OrderbookAmmStrategy. |
| T89 | release boundary | Один research pack blocked, другие прошли свои gates | Capability matrix честно раздельна; не глобальный success. |

## Как подтвердить будущий slice

Сначала focused tests для изменённых owners и необходимых cross-owner invariants. Затем действующие repo quality/authority gates, которые применяются к diff. Полный suite повторять, если этого требует repo gate или есть обоснованный cross-cutting risk. Network smoke держать отдельным opt-in read-only evidence; его отсутствие не маскировать mock success.

У каждого отчёта: commit/tree, exact commands, environment, fixture hashes, counts, skipped checks, stop reasons и remaining external blockers. Passed fixtures не превращаются в real verified subscriptions. Profit outputs synthetic/replay помечаются соответствующим статусом.
