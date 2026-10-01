# FAST-Q1: установленная диагностика и квитанция qualification

Новая команда расширяет `flashloan-checks` и использует существующий
`flashloan-bot` через установленный console script. Она выполняет четыре
ограниченные offline-проверки: status, capabilities, config doctor,
runtime-admission для paper. Параметры команд фиксированы в доверенном коде.

```bash
flashloan-checks qualify-and-report inspect \
  --repo-root /absolute/checkout \
  --output-root /absolute/runs \
  --request-id qualification-001 \
  --expected-sha YOUR_40_CHARACTER_COMMIT_SHA
```

Нужны установленный пакет на Python 3.13 и чистый checkout. Каталог результатов
должен находиться вне checkout. Пакет и исходники проверяются по entrypoint и
хешам четырёх владельцев CLI. Перед запуском нужно обновить expected SHA до
реальной версии ветки. Это не поддержка произвольного пакета со старым кодом.

Сохраняются `baseline.json`, `run_manifest.json`, `qualification_receipt.json`,
`BLOCKERS_RU.txt`, исходные stdout/stderr и их SHA-256. Повтор request ID с теми
же входами возвращает квитанцию после проверки целостности; изменённый вход
отклоняется. Незавершённый запуск требует сверки перед повтором.

`execution_status=COMPLETE` означает завершённую диагностику. `domain_verdict`
бывает BLOCKED или INSPECTED. Даже INSPECTED сохраняет `qualified=false`,
`live_authorized=false`, `market_run_performed=false`. Этот первый срез FAST-Q1
не закрывает полный market soak или sender-free vertical: они остаются
отдельным следующим действием с собственным admission. В режиме inspect exit 0
может сопровождать BLOCKED; режим check возвращает PR-189 код блокировки.

Каждый дочерний процесс имеет timeout, ограничение stdout/stderr и запуск без
унаследованных ключей/API override/runtime env. Doctor запускается без online
и check-secrets. Это ограничение доверенных команд, а не универсальная OS
песочница для произвольного кода.

Проверка: `python -m pytest -q tests/test_fast_q1_qualification_report.py`.
Тесты включают отказ admission, повреждённый JSON, подмену квитанции, повтор
задания, незавершённый запуск, dirty/stale baseline, timeout и output limit.

Следующий предметный PR выбирается по реальному blocker. Отсутствующие внешние
protocol/account evidence становятся задачей на данные, а не поводом переписать
торговое ядро. Live/quarantine/release authority эта команда не изменяет.
