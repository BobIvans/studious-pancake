# Строгие capability-флаги перед AI-автоматизацией

База: `75e78b2b0f8af5884df5e0859b7ac9a42ca1a5b4`.

## Изменение

`ComponentCapability.from_dict` ранее приводил значения через `bool(...)`.
Например, строка `"false"` превращалась в `True`. В `runtime_modes` тип поля
`available` вообще не проверялся. Это дефект проверки входного контракта;
данный PR не утверждает, что был доказан обход всех остальных live-гейтов.

Теперь `active_in_supported_entrypoint`, `quarantined`, необязательный
`required_in_installed_package` и `runtime_modes.*.available` принимают только
настоящие JSON boolean. Строки, числа, null, массивы и объекты отклоняются с
`CapabilityContractError`. Отсутствующий optional required-флаг по-прежнему
имеет значение true. Некорректная форма component/mode также отклоняется.

Изменён существующий владелец `src/capabilities.py`: нового registry, scheduler,
signer или release authority нет. Конфигурационные JSON и default modes не меняются.

## Проверки

Целевой набор: `tests/runtime/test_capability_boolean_contract.py`.

```sh
python -m pytest -q tests/runtime/test_capability_boolean_contract.py
```

В изолированной рабочей копии точного исходника: до исправления 65 failed / 4 passed,
после исправления 69 passed. Git blob исходника проверен:
`f0d766a8b26edb5f21ce5ed2ebec14d5b0bc761b`.

Это не полный CI репозитория. Полная установка, regression suite, форматирование,
installed-package проверка и exact-head CI остаются условиями review/merge.
Сетевые ограничения исследовательского контейнера не позволили получить полный clone;
это не основание отмечать недоступные проверки как PASS.

## Следующая итерация

Подключить read-only capability/status/preflight результаты к очереди qualification.
Laya может предлагать категорию задачи, но не менять допуск режима и не считать
слова модели доказательством. Перед выполнением требуются актуальный SHA, проверенная
спецификация, разрешённая команда, результат проверки и ограниченный бюджет.

Live-торговля, кошелёк, автоматический merge, расходы и непрерывный сервер этим PR
не включаются. Завершение этого изменения не означает production readiness.
