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
| Runtime container | `implemented`, safe-idle | Multi-stage non-root image запускает только process-liveness supervisor, без RPC/подписи |
| Runtime discovery | `implemented`, paper/shadow input | Supported CLI выполняет bounded discovery и передаёт evidence в paper/shadow runner |
| Paper/shadow composition root | `active`, sender-free | `build_paper_shadow_runtime(config)` соединяет discovery с stage mapping; missing atomic deps блокируются, а не превращаются в synthetic success |
| Atomic vertical stages | `wired behind dependency gate` | `CAPITAL_SIZING → PLANNER → COMPILER → FINAL_SIMULATION → RECONCILIATION` доступны через PR-075 suite при supplied verified deps |
| MarginFi flash-loan integration | `evidence-blocked` | Verified build hash есть, но полный IDL/SDK/RPC/human-review proof ещё должен быть supplied до shadow execution-capable |
| Jupiter router library | `implemented`, gated | Код существует; executable Jupiter V2 build должен быть supplied как verified PR-089 dependency |
| Live execution / Jito | unavailable | Live hard-denied; sender modules не входят в supported paper/shadow composition root |
| Pump/Kamino/orderbook extensions | `fixture/evidence-gated` | Нельзя включить env-флагом; требуется отдельный protocol promotion PR |

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
flashloan-bot paper-shadow --json
```

`python arb_bot.py ...` сохранён только как backward-compatible thin wrapper.
Запуск без аргументов эквивалентен `run --mode shadow` и сейчас завершается кодом
`3` с `NO_EXECUTABLE_STRATEGIES`, если стратегия не включена явно. Это ожидаемое
безопасное поведение.

### Режимы продукта

- `disabled` — inspection/safe-idle, доступен.
- `paper` — запускает тот же sender-free PR-089 paper/shadow composition root.
- `shadow` — доступен только для явно включённой `shadow-ready` стратегии; live
  submission, signer и sender остаются вне supported composition root.
- `live` — hard-denied и не может быть включён переменной окружения.

Legacy env-флаги сохранены только для старых скриптов и fixtures. Установленный
launcher не использует их для promotion.

## PR-089 paper/shadow composition boundary

PR-089 добавляет поддерживаемый composition root:

```text
runtime discovery → detector candidates or verified empty market
→ PaperShadowRunner
→ CAPITAL_SIZING → PLANNER → COMPILER → FINAL_SIMULATION → RECONCILIATION
→ durable paper outcome
```

Если рынок проверен и кандидатов нет, результат остаётся `healthy_idle`. Если
кандидат найден, но verified dependencies для atomic vertical ещё не supplied,
рантайм пишет `stage_blocked` с причиной
`blocked_pr089_atomic_dependencies_missing` и выходит non-zero. Это честнее, чем
останавливаться на `blocked_missing_stage_capital_sizing` или записывать
synthetic fill.

При полной dependency injection `PaperShadowRuntimeDependencies` использует
`AtomicVerticalRuntimeStageSuite.stage_handlers()`. Эта stage suite наследует
PR-075 проверку identity/hash между planner, compiler, final simulation и
reconciliation.

## PR-033 snapshot detector boundary

PR-033 добавляет безопасную границу для первого реального detector path:

```text
market snapshots → two-leg circular detector → ranker → config-only capital precheck
→ shadow result sink
```

Эта граница принимает только уже полученные snapshots или recorded fixtures. Она
не вызывает Jupiter/RPC сама, не строит MarginFi/Jupiter plan, не компилирует
transaction, не симулирует и не отправляет payload. Слабый edge становится
`NO_TRADE`/`rejected` до shadow handler.

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
market/dependency readiness**.

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
- До real shadow soak/release evidence используйте репозиторий только для
  разработки, offline проверки и sender-free paper/shadow evidence.

## License

MIT License.
