# Атлас возможностей и требований к капиталу

28 карточек расширяют предыдущие 12 market classes. Это типы механизмов, не 28 работающих стратегий. Прибыльность каждой UNKNOWN. P0/P1/P2/P3 — очередность исследования относительно текущего кода, не размер потенциальной доходности.

| ID / карточка | Механизм | Класс | Flashloan | Очередь |
| --- | --- | --- | --- | --- |
| [OP-01](opportunity_atlas/OP-01.md) | 3/4-hop AMM cycles | ATOMIC_CONDITIONAL | PRINCIPAL_WITHIN_TX | P0 |
| [OP-02](opportunity_atlas/OP-02.md) | Two-path split flow | ATOMIC_CONDITIONAL | PRINCIPAL_WITHIN_TX | P0 |
| [OP-03](opportunity_atlas/OP-03.md) | Stable-pair routing | ATOMIC_CONDITIONAL | PRINCIPAL_WITHIN_TX | P1 |
| [OP-04](opportunity_atlas/OP-04.md) | DEX versus immediate mint/redeem | ATOMIC_CONDITIONAL | ONLY_IMMEDIATE_CONVERSION | P1 |
| [OP-05](opportunity_atlas/OP-05.md) | Liquidation plus unwind | ATOMIC_CONDITIONAL | REPAY_THEN_SELL_COLLATERAL | P1 |
| [OP-06](opportunity_atlas/OP-06.md) | Wrapper and liquid staking conversions | MIXED | IMMEDIATE_LEGS_ONLY | P1 |
| [OP-07](opportunity_atlas/OP-07.md) | LP-share mint/burn decomposition | ATOMIC_CONDITIONAL | IF_ALL_LEGS_CLOSE | P2 |
| [OP-08](opportunity_atlas/OP-08.md) | PT/YT/SY split/merge | ATOMIC_CONDITIONAL | IMMEDIATE_SPLIT_MERGE_ONLY | P2 |
| [OP-09](opportunity_atlas/OP-09.md) | Complete conditional-outcome sets | ATOMIC_CONDITIONAL | ONLY_ATOMIC_COMPLETE_SET | P2 |
| [OP-10](opportunity_atlas/OP-10.md) | Debt refinance and collateral swap | SERVICE_OR_COST_SAVING | INTRA_TX_BRIDGE | P2 |
| [OP-11](opportunity_atlas/OP-11.md) | Intent/batch clearing | EXECUTION_SERVICE | OPTIONAL_BRIDGE_LIQUIDITY | P1 |
| [OP-12](opportunity_atlas/OP-12.md) | AMM/CLOB exact-depth loop | ATOMIC_CONDITIONAL | IF_SAME_DOMAIN_SETTLEMENT | P1 |
| [OP-13](opportunity_atlas/OP-13.md) | CEX–DEX basis | INVENTORY_STRATEGY | LOCAL_ATOMIC_LEG_ONLY | P2 |
| [OP-14](opportunity_atlas/OP-14.md) | Spot–perpetual funding basis | INVENTORY_STRATEGY | NOT_CARRY_FINANCING | P2 |
| [OP-15](opportunity_atlas/OP-15.md) | Perpetual and dated-future calendars | INVENTORY_STRATEGY | NOT_TERM_FINANCING | P2 |
| [OP-16](opportunity_atlas/OP-16.md) | Options parity and vertical spreads | INVENTORY_STRATEGY | RARE_ATOMIC_SUBSET_ONLY | P3 |
| [OP-17](opportunity_atlas/OP-17.md) | Fixed/floating rate claims | INVENTORY_STRATEGY | ATOMIC_ENTRY_ONLY | P2 |
| [OP-18](opportunity_atlas/OP-18.md) | Cross-chain intent and rebalancing | INVENTORY_SERVICE | LOCAL_SETTLEMENT_ONLY | P2 |
| [OP-19](opportunity_atlas/OP-19.md) | RWA/NAV and issuer redemption | INVENTORY_OR_ACCESS_GATED | ONLY_PROVEN_INSTANT_SUBSET | P3 |
| [OP-20](opportunity_atlas/OP-20.md) | Passive CLOB market making | MARKET_MAKING | NOT_RESTING_INVENTORY | P2 |
| [OP-21](opportunity_atlas/OP-21.md) | RFQ market making | MARKET_MAKING | ONLY_ATOMIC_HEDGE | P2 |
| [OP-22](opportunity_atlas/OP-22.md) | Concentrated-liquidity market making | MARKET_MAKING | NOT_PERSISTENT_LP_CAPITAL | P2 |
| [OP-23](opportunity_atlas/OP-23.md) | Private/proprietary AMM quotes | CONDITIONAL_QUOTE_SERVICE | ONLY_FIRM_ATOMIC_QUOTE | P1_DISCOVERY_ONLY |
| [OP-24](opportunity_atlas/OP-24.md) | New-chain market launch | MARKET_ADMISSION | ONLY_QUALIFIED_LOCAL_LENDER | P2 |
| [OP-25](opportunity_atlas/OP-25.md) | Cross-venue collateral and shared liquidity | CAPITAL_EFFICIENCY_RESEARCH | NOT_UNLIMITED_LEVERAGE | P2 |
| [OP-26](opportunity_atlas/OP-26.md) | Verifiable computation procurement | SERVICE_MARKET | NO | P2 |
| [OP-27](opportunity_atlas/OP-27.md) | Mechanism-design and clearing laboratory | R_AND_D_PRODUCT | NO | P2 |
| [OP-28](opportunity_atlas/OP-28.md) | Blockspace and data-cost procurement | COST_OPTIMIZATION | NO | P1 |

## Универсальное правило композиции

Путь допустим, если каждый выход имеет тот же canonical asset/claim identity и time-domain, который требует следующий вход. Для basket transformations нужна векторная операция: mint/redeem, collateral/debt и maturity нельзя сплющивать в фиктивный scalar swap. Все обязательства на конец атомарной операции должны быть закрыты отдельно по активам.

Для новых рынков сначала создаётся product-rights dossier: что именно принадлежит владельцу, когда он может получить деньги, какие fees/caps/permissions и кто меняет правила. Только после этого строятся отношения графа. Название вроде «USD», «ETH yield» или «BTC perp» не доказывает эквивалентность требований.

## Emerging-market watchlist

Текущий DEX dashboard содержит BisonFi, Tessera V, Manifest Trade и другие новые для нашего набора venues. Они заслуживают discovery dossiers по объёму наблюдаемой активности, но эта запись не утверждает их архитектуру, открытость API или доступную точную математику. До чтения первичного кода/документации и revision-bound state они остаются OP-23 discovery-only.

Предыдущие dossiers уже охватывают Aqua, Fluid v2, UniswapX, Morpho V2/Midnight, OIF/Across, Sui/DeepBook, HIP-3, Boros и x402. Здесь они включаются через права, состояние и общие ресурсы; их наличие в документации не даёт автоматического доступа или капитала. См. [17_PROTOCOL_DOSSIERS_AND_SOURCES_RU.md](17_PROTOCOL_DOSSIERS_AND_SOURCES_RU.md).

## Что даёт наибольший инженерный рычаг сейчас

Сначала OP-01/02 с qualification и shared-state capacity; рядом — OP-28 стоимость данных/расчёта и OP-23 discovery. Затем доступные stable/claim/liquidation преобразования. Market making и carry остаются самостоятельными инвестиционными моделями с inventory. Все три Market-of-Markets продукта могут использовать тот же evidence layer без запуска сделок.
