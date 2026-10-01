# FAST-Q1: один запуск с отчётом по установленному CLI

Оператору нужен воспроизводимый ответ: какие проверки реально выполнялись,
какой блокер первый и почему следующий этап не запускался. `status` с кодом 0
не доказывает готовность paper-пути. Новый потребитель собирает evidence уже
существующих владельцев, сохраняя их причины отказа.

После установки wheel в Python 3.13:

```bash
flashloan-bot qualify-and-report --project-root /path/to/studious-pancake --output-dir /path/to/reports --timeout-seconds 30
```

Команда выводит JSON и создаёт отдельную папку `qualification-*` с файлами:

- `qualification_report.json`: состояние, первый и все блокеры, identity исходного
  checkout и установленного пакета, хеши receipts;
- `01_status.json` … `06_paper-shadow.json`: команды, exit codes, JSON evidence,
  длительность и причины; пропущенная команда имеет `state=skipped`;
- `summary_ru.txt`: короткий русский результат;
- `paper-shadow.jsonl`: журнал существующего runner, только если preflight прошёл.

Фиксированный план: `status --json`, `capabilities --json`, `config doctor --json`,
`runtime-admission --command flashloan-bot.run --mode paper --json`,
`paper-vertical check`. Только если все пять проверок passed, допускается один
`paper-shadow --journal-path <папка запуска>/paper-shadow.jsonl --json`.

Код 0 означает `paper-check-passed`, 3 — `blocked`, 2 — ошибку запуска или evidence.
Каждый subprocess имеет deadline от 1 до 300 секунд. Коды процесса и смысловые
поля JSON проверяются вместе; неправильная схема, смешанные логи, дубликаты JSON
и противоречие exit code/payload не дают положительного результата. Лимит размера
проверяется после завершения subprocess и не является потоковой квотой памяти.

Используется console script текущего Python-окружения с target
`src.cli_pr189:main`. При отсутствии установки fallback в source-only runtime нет.
Рабочая директория дочерних команд — новая папка отчёта. `PYTHONPATH`, API keys,
RPC URLs, wallet references, proxy и унаследованный `FLASHLOAN_CONFIG_FILE`
не передаются. RPC startup verification и провайдеры явно выключены.
Пользовательский YAML и произвольные команды этот профиль не принимает.
Это фиксированный offline-профиль; сравнение с персональным runtime-config —
отдельный следующий шаг. Environment isolation не является OS sandbox.

`source.commit` и `installation.record_sha256` описывают разные объекты.
`source_equivalence_verified=false`: отчёт не утверждает, что wheel воспроизводимо
собран из указанного commit. `production_qualification_passed`,
`release_claim_allowed`, `live_enabled`, `laya_inference_performed` всегда false.
Успешная paper-проверка не закрывает экономические, подписные или release gates.

Первое исправление следует брать из `first_blocker`, приложив нужный receipt к
задаче для Codex. В следующем PR можно добавить выбор готовых Laya actions и
receipt-driven task generation; текущий модуль не исполняет LLM-команды.
