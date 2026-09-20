# Внешние подключения: единый офлайн-профиль

Этот каталог — место для описания Jupiter, Solana RPC, Helius и будущих внешних API. Файлы содержат **только ссылки и проверенные ограничения**, никогда значения ключей. Все примеры выключены и не проверены: они не дают ни одного разрешения на сетевой запрос. Указанные `.invalid` адреса — намеренные заглушки.

## Одно место для заполнения

Скопируйте `config/external_connections/profile.example.json` в `config/external_connections/profile.local.json` и заполняйте только этот локальный файл. Он исключен из Git локальным `.gitignore`. Комбинированный пример содержит все пять выключенных заготовок; файлы `profiles/` — отдельные дополнительные образцы.

Установленная офлайн-команда: `flashloan-connections config/external_connections/profile.local.json`. Эквивалент: `python -m src.provider_governance.cli config/external_connections/profile.local.json`. Команда ничего не подключает.

Структуру проверяет единая установленная authority `src.contracts.registry`, schema `mpr2602.connections.v1`; отдельной schema authority нет.

## Как подготовить профиль

1. Скопируйте нужные записи из `profiles/*.example.json` в один локальный JSON-файл с `schema_version: "mpr2602.connections.v1"` и массивом `connections`.
2. Вставьте сведения о плане провайдера, точном HTTPS endpoint и допустимых операциях. Не вставляйте API key, private key, seed phrase, mnemonic, cookies или Authorization headers. Для ключа запишите только `credential.ref`, `credential.generation` и **имя** переменной `credential.env_name`, например `JUPITER_API_KEY`. Загрузчик не читает даже эту переменную.
3. Укажите `quota_pool_ref`: разные ссылки на один внешний тариф должны использовать один и тот же проверенный пул. `review_ref` — ссылка на рассмотренные условия/конфигурацию, а не утверждение о готовности.
4. Замените `entitlement: null` объектом с полями из таблицы ниже. Значения берутся из фактического тарифа и утвержденного локального бюджета. Не выводите платный бюджет или квоты из наличия API key.
5. Сохраните `enabled: false` и `reviewed: false` до проверки. После проверки заполненной записи их можно явно изменить. Это разрешает только формирование ссылочного объекта policy, **не запускает сеть** и не доказывает readiness.
6. Запустите из корня репозитория: `python -m scripts.validate_external_connections путь/к/профилю.json`. Отчет выводит только статусы, hash и счетчики; ключи и URL не печатает.

| Поле `entitlement` | Требование |
|---|---|
| `generation` | Непустая версия проверенного разрешения |
| `operations` | Непустой массив из `discovery`, `refinement`, `finalization`, `backfill`, `health_probe` |
| `window_seconds` | Положительное целое: окно внешней квоты, секунды |
| `request_limit` | Положительное целое: число запросов за окно |
| `cost_unit_limit` | Положительное целое: лимит единиц стоимости |
| `spend_limit_micros` | Целое ≥ 0: утвержденный бюджет в микроденежных единицах; 0 не означает безлимит |
| `max_concurrency` | Положительное целое: максимум одновременно активных attempts |
| `expires_at_epoch_seconds` | Положительное целое: UTC Unix seconds, не milliseconds |
| `spend_window_seconds` | Положительное целое: отдельное окно денежного бюджета, секунды |

`http_methods` — проверенный поднабор `GET`, `POST`. `query_parameters` — точные имена допустимых параметров; ключи/токены в URL запрещены даже при явном перечислении. Endpoint должен быть без query, fragment и userinfo. Параметры запроса передаются отдельно.

Для `outbound_rpc` требуется `POST` и непустой `rpc_methods`. Максимально допустимый sender-free набор: `simulateTransaction`, `getMultipleAccounts`, `getLatestBlockhash`, `isBlockhashValid`, `getBlockHeight`, `getFeeForMessage`, `getGenesisHash`, `getSlot`, `getTransaction`. Укажите только нужный проверенный поднабор. `sendTransaction`, `sendRawTransaction`, airdrop и любые другие методы запрещены. Разрешение запросить данные не означает разрешение использовать непроверенный ответ.

Неизвестный `provider_id` всегда получает `disabled_unknown_provider`. Добавление нового сервиса требует интеграции его consumer/contract, а не только записи JSON. Inbound webhook всегда получает `disabled_inbound_unimplemented`: исходящая квота не заменяет проверку подписи/ACK/replay/gap входящих событий.

## Единый путь загрузки

`src.provider_governance.profile.load_connection_profile(path)` возвращает immutable `entitlements`, `credential_bindings`, `credential_env_names`, безопасные `statuses` и `profile_sha256`. `ProviderGovernance.from_profile(path, store=...)` использует тот же загрузчик. Для существующего `ProviderRegistry` передайте runtime как `governance`, а `runtime.connection_profile.credential_bindings` — как `credential_bindings`. Значения credentials отдельно разрешает поддерживаемый credential resolver; этот профиль не загружает ключи и не активирует адаптеры автоматически.

Ограничения: JSON ≤ 64 KiB, ≤ 64 подключений, ограниченная глубина и строки; дубликаты, неизвестные поля, нецелые числа и bool вместо числа отвергаются. Истечение entitlement проверяет authority по своему доверенному времени. Проверка файла полностью офлайн; DNS pinning, доступность провайдера, внешняя qualification, контрактные доказательства и production readiness ею не подтверждаются.
