# MASTER CONTEXT

## Текущее состояние

- Base snapshot pack: `main = ac6297e3f174d073c524099f599490edfe30f7b1`. Если main новее — работать от нового descendant и пересчитать drift.
- PR #566 merged: Odos удалён из automatic runtime registry, Pyth Hermes получает Bearer auth через secret reference, catalog truth переведён на Project0 SDK, generic RPC independence усилена provider/operator checks.
- Native Raydium CPMM path существует, но qualification report по дизайну остаётся `BLOCKED`: one-shot capture, missing deployment-source binding, no forward holdout, no continuous subscription, unknown financing/cost evidence.
- Repo-wide static snapshot scan: 2703 файлов; 137 direct SQLite connects, из них 85 не approved текущей persistence policy; 554 broad `except Exception`; 260 `time.time`, 51 `datetime.now`, 176 direct `os.getenv`, ~140 raw aiohttp-style calls. Эти числа — debt indicators, не утверждение, что всё находится в active runtime.
- GitHub имеет много open PR; несколько foundational PR сильно diverged от current main и не должны мержиться напрямую.

## Что считать успехом ближайшей итерации

Не “production ready”. Ближайший успех:

1. Campaign manifest привязан к exact current main/release/policy.
2. Можно добавить новый source через один typed dossier/profile workflow.
3. Можно собрать real non-synthetic data без signer/sender.
4. Discovery sources строят rolling universe, но не подменяют exact state.
5. Native collector умеет использовать независимый RPC quorum либо честно маркирует single-source capture как `BLOCKED_SINGLE_SOURCE`.
6. Все success/failure/gap/drift events durable и replayable без сети.
7. Через 24h получаем problem report, а не маркетинговый PASS.

## Не делать

- Не запускать live sender ради “проверки”.
- Не объявлять indexed API price/depth точной executable liquidity.
- Не считать два endpoint одного оператора независимыми.
- Не merge stale foundational PR напрямую — сначала reuse/supersede audit against current main.
- Не переписывать весь persistence слой перед первым campaign; сначала один approved campaign evidence authority, затем migration.
