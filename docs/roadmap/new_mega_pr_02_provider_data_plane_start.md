# NEW-MEGA-PR-02 start — Provider Data Plane, Durable Ingress, Quota и Production Container Wiring

Этот стартовый документ открывает отдельный review thread для NEW-MEGA-PR-02 на базе текущего `main`.

## Цель

Собрать один canonical provider/data-plane boundary:

- writable non-root container state paths под UID 10001;
- typed secret/config ingestion без generic environment secret materialization;
- удаление или жёсткая блокировка legacy production entrypoints;
- single-open secure file reads для management secrets и CA material;
- bounded provider HTTP transport;
- durable Helius ingress и provider handoff state machines;
- rooted RPC quorum evidence;
- durable account-wide Jupiter quota/cache/cooldown;
- readiness, отражающую worker/DB/queue/provider состояние, а не только liveness.

## Scope captured from roadmap

1. Перенести SQLite, JSONL, artifacts и logs в writable `/var/lib` / `/var/log` paths и доказать restart persistence.
2. Подключить mounted runtime.env/secret files через typed config.
3. Заблокировать `setup_flashloan.sh`, PM2, `arb_bot.py` и другие legacy entrypoints.
4. Использовать O_NOFOLLOW single-open boundary для security-sensitive files.
5. Сделать CA trust immutable и привязанным к release evidence.
6. Ввести единый bounded HTTP transport с deadlines, body limits, redirect policy и method-aware retries.
7. Санитизировать credential-bearing URLs.
8. Сделать durable enqueue before ACK для Helius webhook intake.
9. Реализовать claim/lease/ACK/NACK/retry/DLQ для webhook/provider handoff paths.
10. Сделать Jupiter quota/cache/cooldown durable и account-wide между процессами и рестартами.
11. Привязать provider independence к transport-level evidence, а не caller flags.
12. Поднять /ready до workload readiness с учётом ingress worker, DB writability, lag и rooted evidence freshness.

## Safety boundary

Этот стартовый PR не должен:

- включать live trading;
- включать signer/private-key loading;
- включать transaction submission;
- объявлять paper-ready, shadow-qualified или production-ready статус.

## Expected next implementation slice

Следующий кодовый patch поверх этой ветки должен добавить reviewable implementation для:

- container persistence and secret boundary;
- canonical provider transport;
- durable Helius inbox and repair;
- provider handoff and rooted quorum;
- durable Jupiter quota/cache.
