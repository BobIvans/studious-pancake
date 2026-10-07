# Studious Pancake — PRE-QUALIFICATION R&D MASTER PACK

**Дата:** 2026-10-06  
**Текущий main:** `ac6297e3f174d073c524099f599490edfe30f7b1`  
**PR #566:** merged в этот main; Odos retirement, Pyth auth, Project0 catalog truth и RPC independence baseline не считаются незакрытым PR-A повторно.

## Цель

Этот пакет — единый source of truth для перехода от зелёного offline CI к **реальному, read-only, replayable Qualification Campaign** и быстрому подключению новых источников данных без повторного архитектурного дрейфа.

Главное разделение:

1. **Campaign-Start Gate** — минимальный набор, после которого можно безопасно запускать real-data problem testing. Кампания может оставаться `BLOCKED` и всё равно быть полезной.
2. **Qualification-Verdict Gate** — условия, после которых данные позволяют делать сильные выводы о стратегии/venue/protocol.
3. **Production-Promotion Gate** — полный persistence/release/runtime closure + 72h release-bound evidence. Это НЕ нужно ждать для первого read-only run.

## Читай в таком порядке

1. `01_MASTER_CONTEXT_RU.md`
2. `02_MASTER_PROBLEM_REGISTER_RU.md`
3. `03_FASTEST_QUALIFICATION_PATH_RU.md`
4. `11_SOURCE_PLUGIN_ARCHITECTURE_RU.md`
5. `17_PR_SEQUENCE_RU.md`
6. `18_CODEX_START_HERE.md`
7. `data/acceptance_gates.json`
8. `data/free_source_slots.csv`

## Главная архитектурная идея

```text
FREE / LOW-COST DISCOVERY SOURCES
DEX Screener | GeckoTerminal | Jupiter | Raydium/Meteora indexed APIs | future slots
                         │
                         ▼
                Candidate Universe
             (120–160 rolling pairs)
                         │
                         ▼
             Rooted Verification Lane
        RPC provider A  +  independent RPC B
                         │
          same finalized state / provenance
                         ▼
        Protocol / Venue Exact State Decoders
   Raydium CPMM → CLMM → Meteora DLMM → Orca → books
                         │
             Oracle / Protocol Context
              Pyth + Project0/Kamino/etc
                         │
                         ▼
             Immutable Evidence Journal
       success + no-trade + timeout + gap + drift
                         │
                         ▼
               Offline Replay / Holdout
                         │
                         ▼
                 Qualification Gate
```

**Discovery API data не является executable quote.** Оно только говорит, *куда смотреть*. Exact state должен быть подтверждён on-chain/rooted evidence.
