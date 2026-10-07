# RCN-00 → DIN: Main Reconciliation + Governed Data Integration (2026-10-07)

**Статус этого пакета:** проверенный GitHub-аудит + implementation assignment; **не** выполненный merge или proof of production readiness. Опубликован отдельным документационным PR в `main`.

## Немедленный следующий шаг

**Сначала RCN-00 (восстановление QPR/GPR в `main`); только затем DIN-00 (подключение внешних источников).**

Читайте в таком порядке:
1. [MASTER_CONTEXT.md](MASTER_CONTEXT.md) — проверенная картина веток, уже существующие owners и приоритеты.
2. [CODEX_START_HERE.md](CODEX_START_HERE.md) — исполняемая задача Codex.
3. [BRANCH_RECONCILIATION.md](BRANCH_RECONCILIATION.md) — пошаговая безопасная интеграция, контроль конфликтов.
4. [DATA_INTEGRATION_PLAN.md](DATA_INTEGRATION_PLAN.md) — маршрутизация данных, граф, квоты и архитектура.
5. [SOURCE_MATRIX.md](SOURCE_MATRIX.md) — источники, роли, документы, авторизация, риски.
6. [PROVIDER_CATALOG.json](PROVIDER_CATALOG.json) — machine-readable backlog; **не** runtime allowlist.
7. [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) — узкие PR и зависимости.
8. [QUALITY_GATES.md](QUALITY_GATES.md) — тесты, диагностика, 24-часовой campaign и criteria.

## Canonical adjacent references
- Main Dynamic Universe PR #576: `docs/roadmap/dynamic-universe-master-2026-10-07/CODEX_START_HERE.md` and `IMPLEMENTATION_REPORT.md`.
- QPR/GPR implementation stack: PRs #568–#573, source branch `rnd/gpr-parallel-radar-2026-10-06`.
- UXE specifications: PR #575, `docs/roadmap/universal-source-execution-rnd-2026-10-07/` on radar branch.
- Provider cleanup and live safety truth: PR #566; storage admission: PR #577.

**Non-negotiable:** `sign_enabled=false`, no transaction send, no secrets in Git, no promoting indexed quotes to exact executable evidence, no forced merge to `main`.
