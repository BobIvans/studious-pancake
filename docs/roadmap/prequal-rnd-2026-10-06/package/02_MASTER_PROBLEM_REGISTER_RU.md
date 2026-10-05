# Master Problem Register

Полная machine-readable версия: `data/problem_register.csv`.

| ID | Priority | Gate | Finding | Direction |
|---|---|---|---|---|
| `AUTH-001` | **P0** | CAMPAIGN_START | Release qualification и runtime используют разные authority truth | Свести к одному canonical RuntimeAuthority artifact и одному digest, который одновременно проверяют release, runtime и campaign manifest. |
| `DATA-001` | **P0** | CAMPAIGN_START | Native qualification hardcoded к одному anonymous public RPC | ProviderProfile + RpcQuorumProfile; >=2 независимых provider/operator для qualification verdict; single-source разрешить только как EXPERIMENTAL/BLOCKED capture. |
| `DATA-002` | **P1** | CAMPAIGN_START | Hardcoded RPC hostname расходится с текущей Solana документацией | Endpoint только из reviewed provider profile; hostname/version входят в source_generation и evidence. |
| `PERS-001` | **P0** | PRODUCTION_PROMOTION | 137 direct SQLite connects; 85 не approved текущей persistence policy | Два этапа: CampaignPersistenceAuthority сейчас; затем migrate active lifecycle/economic/provider stores через approved factories. |
| `PROT-001` | **P0** | QUALIFICATION_VERDICT | Project0 truth и MarginFi executable conformance смотрят на разные source generations | Новый Project0 protocol dossier: SDK version, source commit, program version, IDL/layout, deployed program/programdata, golden vectors, oracle setup coverage. |
| `QUAL-001` | **P0** | QUALIFICATION_VERDICT | Native report остаётся BLOCKED: one-shot capture, нет continuous subscription | Добавить bounded continuous capture producer с cursor/gap/barrier semantics и immutable receipts. |
| `QUAL-002` | **P0** | QUALIFICATION_VERDICT | Deployment-source binding отсутствует | Program owner + programdata + deployment slot + binary hash + source/reproducible-build evidence. |
| `QUAL-003` | **P1** | QUALIFICATION_VERDICT | Forward holdout не материализован | Time-based holdout partition, no-lookahead cutoff, sealed before replay scoring. |
| `QUAL-004` | **P1** | QUALIFICATION_VERDICT | Execution costs and financing = UNKNOWN | Compute unit, priority fee, Jito optional landing cost, flash-loan fee, account/rent impacts, route/provider fees; conservative unknown => reject. |
| `QUAL-005` | **P0** | PRODUCTION_PROMOTION | Нет release-bound real 24h/72h campaign evidence | Сначала 24h campaign для system problem discovery; затем 72h release-bound soak для promotion evidence. |
| `PROV-001` | **P1** | CAMPAIGN_START | OpenOcean runtime request не совпадает с conformance contract | Один typed request builder должен использоваться и runtime, и conformance probe; добавить gasPriceDecimals source/semantics для Solana. |
| `AUTH-002` | **P1** | CAMPAIGN_START | runtime_authority_map содержит stale PR queue | Вынести PR queue в development-only inventory; runtime authority = только executable ownership/policy. |
| `CLI-001` | **P1/P2** | CAMPAIGN_START | CLI ищет строку run через membership/index вместо parsed subcommand | Один argparse dispatch owner; tests для run как value, config filename, trailing args. |
| `PROOF-001` | **P1** | PRODUCTION_PROMOTION | Proof islands не всегда являются runtime authorities | Каждый proof должен либо быть consumed by runtime/release authority, либо явно diagnostic-only. |
| `DEBT-001` | **P2** | HYGIENE | Global debt ledger ещё содержит obsolete Odos debt | Retire/supersede debt ID with migration receipt; historical artifacts remain audit-only. |
| `SRC-001` | **P0** | CAMPAIGN_START | Нет единого Source Intake Contract для быстрых новых data sources | SourceDossier -> ProviderProfile -> probe -> discovery-only adapter -> rooted verifier -> promotion; blank slots included in this pack. |
| `SRC-002` | **P1** | CAMPAIGN_START | Documentation/source-generation drift не автоматизирован | checked_at + official URL + package/program version + semantic request fingerprint + renewal TTL + drift verdict. |
| `SLOT-001` | **P0** | QUALIFICATION_VERDICT | Generic rooted RPC quorum не wired в native capture | Native collector принимает RootedSnapshotProvider вместо URL; exact same slot/root evidence across independent sources. |
| `ORACLE-001` | **P1** | QUALIFICATION_VERDICT | Oracle upgrades требуют protocol-specific rebinding | OracleSetup registry with source generation, accounts, freshness/confidence, required extra accounts and negative tests. |
| `TOKEN-001` | **P1** | VENUE_EXPANSION | Token-2022 extension coverage не единообразна по venues | Canonical TokenSemantics evidence; unsupported extension => fail closed; exact transfer-fee amount coupling. |
| `VENUE-001` | **P1** | VENUE_EXPANSION | Current real native path в основном Raydium CPMM | Add one venue family at a time with current deployed vectors, complete mutable state and differential quote tests. |
| `ORDERBOOK-001` | **P2** | VENUE_EXPANSION | Phoenix/OpenBook market subscriptions не qualified | Snapshot+delta protocol, reconnect resync, lot/tick/fee verification, no fill-priority assumptions. |
| `OBS-001` | **P1** | CAMPAIGN_START | Negative evidence должно быть first-class для всех sources | Persist timeout/401/403/429/5xx/schema drift/gap/stale/quorum disagreement with source generation and availability time. |
| `RATE-001` | **P1** | CAMPAIGN_START | Quota/budget semantics должны быть едиными для новых sources | Physical-attempt quota lease keyed by provider generation; retry consumes budget; daily/monthly caps explicit. |
| `LIC-001` | **P2** | SOURCE_ADMISSION | License/terms review нужен как часть source admission | terms_url, license_class, redistribution_allowed, commercial_use, attribution, reviewed_at. |
| `PR-001` | **P1** | HYGIENE | 30 open PR; несколько foundational PR сильно diverged | Не merge stale PR напрямую; harvest unique tests/contracts, rebuild on current main, then close/supersede. |
| `LEGACY-001` | **P2/P3** | HYGIENE | Большой quarantined legacy/ingest слой | Keep quarantine manifest strict; delete/split only after evidence no active imports. |
| `EXC-001` | **P2** | HYGIENE | 554 broad except Exception в snapshot | Lint only canonical active graph first; exceptions must map to typed failure codes, preserve cancellation. |
| `TIME-001` | **P2** | QUALIFICATION_VERDICT | 260 time.time + 51 datetime.now calls в snapshot | Campaign-critical paths use injected trusted wall+monotonic clocks and slot time; quarantine rest. |
| `NET-001` | **P2** | SOURCE_ADMISSION | 140 raw aiohttp-style calls в snapshot | Active providers only through governed transport; legacy calls remain quarantined. |
| `ENV-001` | **P2** | SOURCE_ADMISSION | 176 os.getenv direct reads в snapshot | Active graph reads typed config/secret references; direct env allowed only bootstrap layer. |

## Ключевой принцип приоритизации

**P0 для первого campaign** — только то, что влияет на identity/provenance, source admission, rooted state и durable evidence.  
**P0 для production promotion** — persistence-wide migration, 72h soak, proof-island cutover.  
Так мы не блокируем сбор real evidence из-за долга, который не нужен read-only capture.
