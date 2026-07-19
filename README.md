# Flash-loan Arbitrage Bot — runtime truth (PR-023)

Этот репозиторий содержит заготовки Solana arbitrage-системы: доменные модели,
strategy registry, часть Jupiter/MarginFi/routing/execution-кода, тесты и legacy
модули. **Текущий снимок не является production-ready ботом и не выполняет
реальные арбитражные сделки end-to-end.**

## Текущий честный статус

| Возможность | Статус | Что это означает |
|---|---|---|
| Supported launcher | `implemented` | `python arb_bot.py` показывает status/capabilities и fail-closed запускает runtime |
| LST/circular detectors | `disabled` | Активные detector shells не создают реальные opportunities |
| MarginFi flash-loan integration | `fixture-only` | Binary account/instruction conformance с deployed mainnet ещё не доказана |
| Jupiter router library | `implemented`, inactive | Код существует, но не подключён к поддерживаемому execution pipeline |
| Paper trading | `disabled` | Legacy paper script quarantined; canonical paper runner ещё не реализован |
| Shadow execution | unavailable | Нет единой вертикали planner → compiler → exact simulation → reconciliation |
| Live execution / Jito | unavailable | Live hard-denied; sender modules не входят в supported entrypoint |
| Pump/Kamino/orderbook extensions | `fixture-only`, quarantined | Нельзя включить env-флагом; требуется отдельный protocol promotion PR |

Полная machine-readable матрица находится в
[`config/capabilities.json`](config/capabilities.json). Runtime проверяет её
против зарегистрированных стратегий до запуска.

## Единственный поддерживаемый entrypoint

```bash
python arb_bot.py status
python arb_bot.py status --json
python arb_bot.py capabilities
python arb_bot.py capabilities --json
```

Запуск без аргументов эквивалентен:

```bash
python arb_bot.py run --mode shadow
```

Пока нет ни одной стратегии, одновременно включённой и отмеченной
`shadow-ready`/`live-ready`, команда завершается с кодом `3` и диагностикой
`NO_EXECUTABLE_STRATEGIES`. Это ожидаемое безопасное поведение, а не ошибка
рынка или RPC.

### Режимы продукта

- `disabled` — inspection-only, доступен.
- `paper` — недоступен до canonical paper runner (roadmap PR-038).
- `shadow` — запрашиваемый default, но сейчас завершается безопасно, потому что
  исполнимая стратегия отсутствует.
- `live` — hard-denied и не может быть включён переменной окружения.

Legacy env-флаги (`PAPER_TRADING_ONLY`, `LIVE_TRADING_ENABLED`, `JITO_ENABLED`,
`KAMINO_LIQUIDATION_ENABLED`) сохранены только для старых скриптов и тестовых
fixtures. Поддерживаемый `arb_bot.py` намеренно не использует их для promotion.

## Проверка репозитория

Ожидаемая версия для текущего baseline — Python 3.13.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
make verify
```

Также можно отдельно проверить PR-023 контракт:

```bash
make status
make capabilities
python -m pytest tests/test_pr023_runtime_truth.py -q
```

`make verify` проверяет зависимости, syntax/import smoke и offline tests. Он не
доказывает mainnet, paper, shadow или live readiness.

## Quarantine

Quarantine означает, что код остаётся в дереве для миграции, fixtures и
исследований, но не считается production capability и не импортируется
поддерживаемым composition root. Список и правила:

- [`docs/quarantine_pr023.md`](docs/quarantine_pr023.md)
- [`config/capabilities.json`](config/capabilities.json)

В частности, `src/legacy_arb_bot.py`, legacy transaction/Jito routers,
`scripts/paper_trader.py`, Pump, Kamino/liquidation и Phoenix/OpenBook paths не
могут быть promoted одним env-флагом.

## Что должно появиться дальше

Ближайшая production-safe цель — одна доказуемая vertical:

```text
quotes → opportunity → capital-aware sizing → atomic MarginFi/Jupiter plan
→ canonical v0 message → exact simulation → economic reconciliation
→ durable paper outcome
```

Порядок работ и acceptance criteria находятся в сохранённом аудите:
[`docs/audits/FLASHLOAN_BOT_PRODUCTION_AUDIT_AND_PR_ROADMAP_2026-07-19.md`](docs/audits/FLASHLOAN_BOT_PRODUCTION_AUDIT_AND_PR_ROADMAP_2026-07-19.md).

## Безопасность

- Не помещайте seed phrase/private key в `.env`, логи, issue или prompt.
- Не считайте RPC/Jito acknowledgement доказательством landed/settled сделки.
- Не включайте legacy scripts для реальных средств.
- До PR-038/PR-039 используйте репозиторий только для разработки и offline
  проверки.

## License

MIT License.
