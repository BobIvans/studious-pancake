# MASTER-00 → P0/R02/R03 → whole-project execution (RU)

## Главное решение
**P0-1, P0-2 и P0-3 — это три параллельные задачи первой волны реализации после MASTER-00, а не содержимое одного первого мегазадания.** MASTER-00 сначала фиксирует общий контракт идентичности/evidence и реальную картину репозитория. После фиксации три агента могут независимо работать в своих worktree. Интеграция и продвижение к exact state зависят от доказательств, а не от очередности PR.

## Почему так
- P0-1 уже имеет открытый PR #593, но он не в main и его ветку нужно rebase/review. Второй агент не должен реализовывать ту же cadence/coverage.
- P0-2 имеет существующий GPR quote owner: Jupiter V1 и 0x. Его работа — миграция owner к V2, same-size quote comparison и replay, не новый quote engine.
- P0-3 уже имеет Raydium CPMM native owner и evidence schemas; пробелы — CLMM, DLMM и точная глубина. Orca требует legal decision.
- Три задачи используют общий canonical AssetIdentity/MarketIdentity/evidence generation, поэтому интерфейс лучше заморозить в MASTER-00, а venue/quote/intake adapters строить независимо.
- R-02 CAP-A/B/C/D — ещё один независимый read-only поток. R-03-00 и offline builders могут развиваться параллельно, но live route promotion ждёт совпадения R-02/R-03 proof.

## Выполнять одновременно в отдельных worktrees
- P0-1 (review/rebase #593)
- P0-2 (Jupiter V2 + 0x)
- P0-3 (Raydium CLMM / Meteora DLMM; Orca license)
- R02 A-D (Jupiter/Kamino/NAVI/P0)
- R03-00 unsigned contract + offline protocol adapters
- R09 (Sui/TON/EVM/CEX/oracle source research)
- R10 (stablecoin/LST/wrapper/CLOB/vault/liquidation/funding/event/cross-chain strategy coverage)
- R11/R12 (platform and dependency security)

Каждый агент работает только на своей зоне. Совместная правка source catalog, AssetResolver, quote models, FlashCapitalGraph или runtime authority требует одного owner и согласованного interface PR.

## Последовательность зависимостей (не равна последовательности запуска агентов)
MASTER-00 interface freeze → parallel P0/R02/R03/data-source/strategy work → integration review → R04 route/capital/size selector → R05 complete unsigned transaction/PTB simulation → QPR-readiness-gated R06 paper campaign → one-by-one R07 provider expansion and human review.
