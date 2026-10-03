# Native CPMM capture и qualification

Продолжение PR563 от main `85fcb0f3be36d6e3716f4194896ff2a9fc6e36ff`.
Реализован полный ограниченный путь для одного protocol pack: governed public
read → raw journal → восстановленный CPMM state → amount-coupled graph → report.
Весь исходный ZIP пока не завершён: нужны остальные protocol packs, verified
subscriptions и внешние qualification campaigns. Его 189 acceptance cases не
объявлены PASS по результатам unit tests. Архивные документы сохранены без изменений.

## Owners и ограничения

- `src/providers/raydium_cpmm_native.py` проверяет account owners, Anchor layouts,
  config/oracle PDA, vault authority/mint/state, WSOL backing, pause/open-time,
  mint decimals, fee counters, genesis и единственный finalized context slot.
  Поддерживаются только SPL Token v1 и pinned CPMM layout; неизвестные layouts,
  Token-2022, CLMM/DLMM и stable pools отклоняются.
- `src/direct_venue/cpmm_math.py` и `QualifiedRaydiumCpmmAdapter` сохраняют владение
  integer math. Каждая новая сумма и каждый следующий leg пересчитываются.
  `src/economics/non_monotonic_sizing.py` сохраняет владение PR118 amount grid
  и economic sizing; нового optimizer или capital ledger нет.
- Collector использует `HttpxJsonTransport`, `ProviderGovernance` и PR02 shared
  quota authority. RPC/discovery имеют общую квоту 8 physical attempts/60s,
  concurrency 1, monetary spend 0, конечный deadline и UTC expiry. Retry не
  освобождает квоту. Неизвестный outcome сохраняет claim до reconciliation.
  Правила TLS, host allowlist, запрет redirects/ambient credentials сохраняются.
- В одном bank читаются pool, config, оба vault/mint, LP mint, observation,
  program/programdata и Clock: не более 8 pools и 100 accounts. Preflight
  pointers проверяются повторно. `getBlock` разрешён только как read-only RPC
  в существующем governance owner. Нет sender/signer/submission.
- Journal хранит raw account values, request/response fingerprints, acquisition
  times и slot/block metadata. Hash response обозначает canonical JSON, а не
  исходные wire bytes. Provider-reported block hash не является независимым
  криптографическим доказательством связи account state с bank.
- Replay восстанавливает state из raw bytes. Availability cutoff исключает
  будущие записи. Outage/cancellation/finalized-bank conflict записывают durable
  barrier; новый full snapshot после barrier восстанавливает eligibility.
  Rejected data не продвигают принятый cursor. Barrier history также ограничена
  storage budget; исчерпание бюджета блокирует campaign.
- Topology scan ограничен 32 plans/1024 expansions, оценка — 64 route/amount
  pairs; seed grid содержит до 8 integer points. Existing graph detector
  ограничивает edges/expansions/candidates отдельно. Budget exhaustion явно
  обозначается в report и не выдаётся за полный поиск рынка.
- Graph/source traces сохраняют underlying venue identity и raw response hash.
  `OrderbookAmmStrategy` остаётся disabled; subscriptions не включены.

## Запуск

Коллекция выполняется только с явным флагом. Directory — evidence одного
source release и policy: повторный запуск переиспользует durable quota, а
смена release/manifest может потребовать существующий upgrade/reconciliation
workflow. Удаление authority DB не является допустимым способом обновления квоты.

```bash
python -m src.paper_shadow.native_cpmm_qualification \
  --collect --pool <canonical-CPMM-pool-address> \
  --output /path/to/native-campaign
```

Вместо explicit pools можно указать `--collect --discover`: ровно одна bounded
страница Raydium metadata, фильтрация по CPMM program ID, максимум 8 addresses.
Отсутствующие markets или ошибка discovery блокируют campaign; metadata не
становятся quote. Этот prefix не обещает арбитражных кругов или coverage всего рынка.

```bash
python -m src.paper_shadow.native_cpmm_qualification \
  --replay /path/to/native-campaign/raw.sqlite \
  --partition <partition-from-report> --as-of-ns <availability-cutoff> \
  --output /path/to/replay.json \
  --lower-amount 10000 --upper-amount 1000000
```

Replay не делает network requests. TTL finalized snapshot ограничен 120 seconds;
вне него report BLOCKED. Ошибка capture/replay возвращает exit 2 вместе с JSON.
Успешный shadow replay возвращает 0, сохраняя overall qualification BLOCKED.

## Полученная evidence

`native_public_read_attempt.json` сохраняет реальную попытку 3 октября 2026:
discovery вернул `transport-error`, markets отсутствуют, native snapshots — 0.
Outcome удержан в существующей quota authority. Это исторический receipt с
source digest попытки, не успешная data qualification текущего release.

Два `examples/native-cpmm-*hop.synthetic.json` — явно synthetic raw-account
corpus. Соответствующие reports показывают exact amount coupling, source traces
и deterministic identity; это не mainnet captures. Tests проверяют полный путь
с mock RPC, перезапуск, stale/future rejection, hash/context/owner faults,
pointer drift, pause/fees, repeated venue и cancelled durable quota. Installed
package smoke повторяет raw-state replay из нового wheel без source checkout.

Report отделяет raw decode от deployment-source binding, continuous subscription,
cost/financing evidence и forward holdout. Deployed binary SHA256 сам по себе
не связывает binary с pinned source. Поэтому gross shadow candidates не являются
проверенной net profitability или execution permission. Для завершения ZIP
остаётся код дополнительных protocol packs и реальный полный qualification corpus;
это больше, чем только получение данных.
