# pmm-sim: исследование caller-dependent Prop AMM pricing

## Статус

Режим: offline / local LiteSVM research only. Использование upstream параметра --spoof для эксперимента в локальной VM разрешено этим пакетом. Его нельзя переносить в mainnet sender/transaction builder.

## Почему этот режим нужен

README LimeChain/pmm-sim прямо предупреждает: некоторые Prop AMM могут давать preferential rates для whitelisted caller addresses, а цена может зависеть от источника CPI. README перечисляет Jupiter, OKX, DFlow и Titan как поддерживаемые simulated aggregator profiles.

На pinned upstream commit cc4ae891a2a765d92c89d4381f96dce4afd446bb изучен код:
- src/lib.rs: enum Aggregator перечисляет Jupiter, DFlow, OKX Labs и Titan.
- src/builder.rs: builder выбирает соответствующий router instruction/discriminator, а затем при spoof меняет instruction.program_id на выбранный aggregator program ID.
- src/env.rs: локальный LiteSVM загружает специальный magnus-router-spoof-<aggregator>.so под выбранным aggregator ID.
- src/lib.rs benchmark: spoof profile применяется только для CPI; direct call оставляет spoof пустым.

Это не реальная интеграция Jupiter/DFlow/OKX/Titan. В локальной VM исполняется специальный Magnus router binary, размещённый под адресом профиля. Это контролируемый эксперимент поведения Prop AMM при разных caller IDs. На mainnet program ID определяет реально deployed executable; нельзя просто поменять program_id на Jupiter и заставить сеть исполнять собственный router под Jupiter ID.

## Какие именно профили проверять

| Profile | Что измеряет |
|---|---|
| DIRECT | Вызов Prop AMM напрямую, без router CPI |
| MAGNUS_NATIVE | CPI через обычный Magnus router |
| JUPITER_SIM | Локальный Magnus router под Jupiter program ID |
| DFLOW_SIM | Локальный Magnus router под DFlow program ID |
| OKX_SIM | Локальный Magnus router под OKX Labs program ID |
| TITAN_SIM | Локальный Magnus router под Titan program ID |

Результаты этих профилей позволяют определить, есть ли у конкретного AMM различие цены по caller profile, но не разрешают production impersonation.

## Какие AMM проверять

Текущий README pmm-sim перечисляет:
- HumidiFi swap v1, v2, v3;
- SolFi V2;
- Obric V2;
- ZeroFi;
- Tessera V;
- GoonFi;
- BisonFi.

Проверять каждую конкретную market/program version отдельно. Нельзя объединять все HumidiFi версии или все пулы в одну строку результата. Market addresses берутся из pinned setup manifest / approved capture; программа, market state и account owners должны быть подтверждены.

## Чего мы уже знаем и чего пока не знаем

Из README подтверждена сама возможность caller-dependent rates. В README есть рисунок WSOL→USDC в одном конкретном slot с Jupiter-профилем и примеры запуска GoonFi/Jupiter, Tessera+SolFi/DFlow. Но репозиторий на момент аудита не содержит воспроизводимой полной таблицы, которая бы показывала для каждого Prop AMM, какой caller profile даёт лучший quote.

Поэтому сейчас нельзя честно сказать:
- «HumidiFi лучше котирует Jupiter на X bps»;
- «DFlow получает лучшую цену на SolFi»;
- «Titan/OKX whitelist включён на GoonFi»;
пока эти факты не подтверждены одним и тем же state snapshot и численными benchmark output.

## Обязательный benchmark protocol

### A. Один неизменный state snapshot

Получить один approved snapshot через текущий governed capture/source owner. Сохранить:
- cluster/genesis, slot, commitment/root status;
- market/pool addresses;
- все необходимые account bytes, owners, lamports, executable/program data hashes;
- exact program binaries/version hashes;
- token mints, token programs, decimals и extensions;
- source generation, fetch timestamps и provenance;
- pmm-sim SHA, Magnus revision, Cargo.lock digest и local patches.

Скопировать этот snapshot в локальный harness. Для всех профилей включить local account/program mode (jit-accounts=false, jit-programs=false); не давать отдельному profile подгрузить более свежий state из RPC.

### B. Сравнить все caller profiles на одном snapshot

Для каждого market × direction × amount:
1. DIRECT;
2. MAGNUS_NATIVE;
3. JUPITER_SIM;
4. DFLOW_SIM;
5. OKX_SIM;
6. TITAN_SIM.

Сравнивать точный raw input amount и точную mint/token-program identity. Делать amount grid, который покрывает реальные route sizes и область глубины, а не только один маленький swap. Для каждого профиля повторить один и тот же deterministic fixture.

Upstream CLI содержит benchmark с call-type=cpi, spoof=<profile>, jit-accounts=false и jit-programs=false. Использовать только local snapshot mode. Не включать upstream defaults, которые могут неявно запрашивать RPC.

### C. Что сохранять

Для каждой строки:
- AMM name + version + program ID + market ID;
- direction, raw amount in/out, decimals;
- slot, account snapshot digest, program digest;
- caller profile / router instruction variant;
- spread/round-trip result, spread bps, CU;
- simulator return/error and logs;
- run/build metadata and source commit.

Расчёт преимущества против прямого вызова:
caller_delta_bps = (out_profile - out_direct) / out_direct * 10_000.

Также сравнить MAGNUS_NATIVE baseline. Сохранять все failures and negative results; не выкидывать неудобные профили.

### D. Не смешивать caller premium с другими эффектами

Разница в выходе может возникать из-за:
- другого router instruction discriminator / route semantics;
- неверного или различного account ordering;
- разных program versions/accounts;
- stale account state or different slot;
- wrong pool identity / token decimals;
- liquidity state changed by simulation order;
- token extensions or fee config.

До вывода о whitelist caller profile тест должен доказать идентичный underlying AMM state и корректный router instruction/account layout.

Повторить матрицу минимум на нескольких независимых snapshots/slots, чтобы отличить устойчивую policy от временного market state.

## Как превратить результат в конкурентный route

Результат SIM profile отвечает только на вопрос «какой caller path стоит изучить». Для production нужен реальный, разрешённый caller integration:

- Если JUPITER_SIM профиль показывает устойчивое преимущество — использовать официальный Jupiter Swap API V2 /order или /build, получить настоящую Jupiter-built instruction route и пересимулировать её в репозитории. Не переписывать program_id на Jupiter.
- Если DFlow / OKX / Titan профиль показывает преимущество — проверить официальный provider API/SDK и способность вернуть настоящую транзакцию/route, которая действительно вызывает PMM от этого aggregator. Без подтверждённого официального route integration profile остаётся research-only.
- Если DIRECT лучше — использовать официальный direct instruction builder после program/account/min-out conformance.
- Если MAGNUS_NATIVE лучше — использовать существующий проверенный router only if its deployed program and identity are genuinely the same and approved; do not assume this.
- Сравнивать реальные direct / official aggregator builds ещё раз на R13 normalized quote path и R05 exact simulation.

## Ограничение benchmark

Upstream pmm-sim benchmark измеряет локальное исполнение/round-trip и CU. Его benchmark SwapArgs использует permissive expect_amount_out=1 и min_return=1; это не production slippage guard и не flashloan repayment guard. Любой выбранный route должен пройти существующие точные quote, transaction build, R05 simulation, all-in economics и same-transaction repayment assertions.

## Обязательный deliverable

Создать в репозитории:
- research/pmm-sim-caller-profile/README.md;
- research/pmm-sim-caller-profile/market_matrix_v1.json;
- immutable per-slot snapshot/provenance records;
- per-market/per-amount Parquet/CSV and summary Markdown;
- plots of output vs amount and caller_delta_bps;
- explicit BEST_SIMULATED_CALLER_PROFILE, BEST_REAL_EXECUTABLE_ROUTE, NO_DIFFERENCE or BLOCKED label per row.

Не объявлять конкретный aggregator best только по README, одной картинке, одному slot или локальной симуляции. Верифицировать именно численные результаты.

## Safety boundary

Разрешено: локальная LiteSVM симуляция synthetic caller profiles, анализ цены и CU, чтение/реплей approved account snapshots.

Запрещено: отправлять mainnet transaction с подменённым aggregator ID, деплоить router binary под чужой ID, использовать чужой API key/program authority, обходить whitelist/anti-abuse controls или выдавать собственный router за настоящий Jupiter/DFlow/OKX/Titan.

Все signing/sending/borrowing/live flags остаются false.
