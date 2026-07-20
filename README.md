# Flash-loan Arbitrage Bot — runtime truth and packaging baseline

Этот репозиторий содержит заготовки Solana arbitrage-системы: доменные модели,
strategy registry, часть Jupiter/MarginFi/routing/execution-кода, тесты и legacy
модули. **Текущий снимок не является production-ready ботом и не выполняет
реальные арбитражные сделки end-to-end.**

## Текущий честный статус

| Возможность | Статус | Что это означает |
|---|---|---|
| Installed launcher | `implemented` | `flashloan-bot` показывает status/capabilities и fail-closed запускает runtime |
| Reproducible package | `implemented` | `pyproject.toml`, console scripts и CPython 3.13 contract являются единым package boundary |
| Runtime container | `implemented`, safe-idle | Multi-stage non-root image запускает только process-liveness supervisor, без RPC/детекторов/подписи |
| LST/circular detectors | `disabled` | Активные detector shells не создают реальные opportunities |
| MarginFi flash-loan integration | `fixture-only` | Binary account/instruction conformance с deployed mainnet ещё не доказана |
| Jupiter router library | `implemented`, inactive | Код существует, но не подключён к поддерживаемому execution pipeline |
| Paper trading | `disabled` | Legacy paper script quarantined; canonical paper runner ещё не реализован |
| Shadow execution | unavailable | Нет единой вертикали planner → compiler → exact simulation → reconciliation |
| Live execution / Jito | unavailable | Live hard-denied; sender modules не входят в supported entrypoint |
| Pump/Kamino/orderbook extensions | `fixture-only`, quarantined | Нельзя включить env-флагом; требуется отдельный protocol promotion PR |

Полная machine-readable матрица находится в
[`config/capabilities.json`](config/capabilities.json) и дублируется как package
resource для установленного wheel. Runtime проверяет её против strategy registry.

## Поддерживаемый entrypoint

После установки используйте console command:

```bash
flashloan-bot status
flashloan-bot status --json
flashloan-bot capabilities
flashloan-bot capabilities --json
```

`python arb_bot.py ...` сохранён только как backward-compatible thin wrapper.
Запуск без аргументов эквивалентен `run --mode shadow` и сейчас завершается кодом
`3` с `NO_EXECUTABLE_STRATEGIES`. Это ожидаемое безопасное поведение.

### Режимы продукта

- `disabled` — inspection/safe-idle, доступен.
- `paper` — недоступен до canonical paper runner (roadmap PR-038).
- `shadow` — недоступен, пока нет стратегии, прошедшей capability promotion.
- `live` — hard-denied и не может быть включён переменной окружения.

Legacy env-флаги сохранены только для старых скриптов и fixtures. Установленный
launcher не использует их для promotion.

## Установка

Поддерживается **CPython 3.13.x**. Runtime lock не содержит analytics/ML,
web-service или test toolchain.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --requirement requirements.txt
python -m pip install --no-deps .
flashloan-bot status
```

Профили зависимостей:

```bash
# Runtime only
make install

# Runtime + offline analytics/ML
make install-analytics

# Runtime + analytics + service adapters + test/quality tools
make install-dev
```

`pyproject.toml` — единственный источник прямых зависимостей. Exact lock-файлы
создаются для Python 3.13 через pinned `uv`:

```bash
make lock
git diff -- pyproject.toml requirements*.txt config/requirements-lock.json
```

Процедура и правила обновления описаны в
[`docs/packaging/PR-025.md`](docs/packaging/PR-025.md).

## Container

```bash
docker build -t studious-pancake:pr025 .
docker run --rm --name flashloan-bot studious-pancake:pr025
```

Образ:

- построен из exact Python patch image в двух stages;
- устанавливает только `requirements.txt` и wheel/package;
- работает от `10001:10001`;
- по умолчанию запускает `flashloan-bot container`;
- не подключается к RPC, не обнаруживает сделки и ничего не подписывает;
- использует heartbeat process probe `flashloan-bot-healthcheck`.

Этот healthcheck подтверждает только живой safe-idle процесс. Он **не является
market/dependency readiness**; `/health` и `/ready` с реальными dependency
states остаются scope PR-042.

Проверка образа:

```bash
make image-smoke
```

## Проверка репозитория

```bash
make verify
make package-smoke
```

`make verify` проверяет dependency consistency, quality gates, syntax, capability
contract и offline tests. Он не доказывает mainnet, paper, shadow или live
readiness.

## Quarantine

Quarantine означает, что код остаётся в дереве для миграции, fixtures и
исследований, но не считается production capability и не импортируется
поддерживаемым composition root:

- [`docs/quarantine_pr023.md`](docs/quarantine_pr023.md)
- [`config/capabilities.json`](config/capabilities.json)

## Следующая доказуемая vertical

```text
quotes → opportunity → capital-aware sizing → atomic MarginFi/Jupiter plan
→ canonical v0 message → exact simulation → economic reconciliation
→ durable paper outcome
```

Полный порядок работ находится в сохранённом аудите:
[`docs/audits/FLASHLOAN_BOT_PRODUCTION_AUDIT_AND_PR_ROADMAP_2026-07-19.md`](docs/audits/FLASHLOAN_BOT_PRODUCTION_AUDIT_AND_PR_ROADMAP_2026-07-19.md).

## Безопасность

- Не помещайте seed phrase/private key в `.env`, логи, issue или prompt.
- Не считайте RPC/Jito acknowledgement доказательством landed/settled сделки.
- Не включайте legacy scripts для реальных средств.
- До PR-038/PR-039 используйте репозиторий только для разработки и offline
  проверки.

## License

MIT License.
