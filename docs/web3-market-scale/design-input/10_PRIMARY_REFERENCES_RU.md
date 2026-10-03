# Источники и происхождение

Design input: [Google Doc](https://docs.google.com/document/d/1f-asFbZuFDnlWfi0aGKWV8Zjkj739hsPN2t220uUD7k/edit). Используются заданные пользователем требования и текущая реализация owners; точная техническая квалификация описана в01. Google Doc не редактировался.

Кодовые первоисточники — immutable GitHub permalinks в data/owner_map.json и01_CURRENT_STATE_AND_OWNERS_RU.md. Каждый файл имеет SHA-256 локально проверенных bytes. Source catalogue — snapshot repo `src/resources/market_source_catalog.json` с checked_at2026-10-02, сохранён без повышения статусов. Его43 external primary references не перепроверены поголовно при создании этого нового планового ZIP.

Ниже первичные документы, открытые для нынешнего планирования2026-10-02 UTC. Они подтверждают устройство продуктов/данных, а не доходность, право исполнения или бесплатный production tier:

- [Uniswap v2 pricing](https://developers.uniswap.org/docs/protocols/v2/concepts/pricing): amount-dependent pool pricing.
- [Pendle AMM](https://docs.pendle.finance/pendle-v2/ProtocolMechanics/LiquidityEngines/AMM): PT/SY и связанные PT/YT operations.
- [Aave flash loans](https://www.aave.com/docs/aave-v3/guides/flash-loans): protocol financing terms; current contract parameters отдельно pin перед evaluation.
- [CoW Protocol](https://docs.cow.fi/cow-protocol): intent/batch-solver protocol context.
- [Hyperliquid WebSocket](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket): data connection and reconnect documentation.
- [dYdX feeds](https://docs.dydx.xyz/interaction/data/feeds): indexer feeds and channel lifecycle.
- [SQD](https://docs.sqd.dev/en/home): indexer/data API infrastructure.
- [Envio](https://docs.envio.dev/): indexer/RPC/data product documentation.
- [Deribit](https://docs.deribit.com/): derivatives API reference; source access dossier ещё нужен.
- [Arbitrum chain overview](https://docs.arbitrum.io/launch-arbitrum-chain/overview/introduction): infrastructure options, не основание создавать chain без спроса.

Два watchlist URL (Sui DeepBook и Injective) не были доступны через использованный механизм чтения. Их contents/free access не считаются проверенными. Все ограничения и timestamps сохранены в data/source_expansion_watchlist.json. Ни один новый live API integration smoke для этого ZIP не запускался.

Исследовательские выводы о приоритетах, architecture, proposed bounds и acceptance criteria являются инженерными предложениями этого пакета, а не утверждениями внешних источников. Исчерпывающий market-wide список или гарантированная прибыль не заявляются.
