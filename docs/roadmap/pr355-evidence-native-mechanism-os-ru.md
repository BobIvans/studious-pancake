# PR-355 — Evidence-Native Financial Mechanism OS: дизайн и эксплуатация

## 1. Назначение

PR-355 расширяет уже существующие research/evidence owners и не создаёт второй journal, PIT-store, graph, forecast ledger, model registry, strategy registry, signer, sender, capital или release authority.

Все новые MarketPack-и остаются `DISABLED`. Merge означает только code/research integration и не означает external qualification, profitability или live authorization.

## 2. Canonical owners

- EVO-09 остаётся единственным owner residual-anomaly/bot-feedback loop.
- RND-00…RND-11 остаются canonical mechanism-discovery owners.
- PR-355 добавляет child/specialization contracts в `src/mechanism_discovery`.
- `NXF-001…NXF-072` — requirement IDs, а не NF. Новые NF-1185+ не назначены.
- Точный mapping IG/NXF/MarketPack находится в `config/pr355_owner_map.json`.

## 3. Data contracts

Основные exact-value contracts:

- `CashflowSpec` — fixed/floating cashflows, schedules, maturity, collateral, eligibility и clocks.
- `ClaimRightSpec` — holder/beneficiary, issuer/counterparty, redemption, transfer/custody/jurisdiction и capacity.
- `LiquidityShapeSpec` — support/range, liquidity, dynamic fee, caller context, transitions и dependencies.
- `AccessAndCustodySpec` — NAV revision lifecycle, subscription/redemption, jurisdiction/allowlist/custody.
- `ResearchResourceSpec` — ZERO_COST/MOCK/TESTNET resources; production payment запрещён.
- `ResearchReceipt` — source/raw/code/tree/config/model/environment/output identity.

Float financial payloads не используются как authoritative exact money.

## 4. MarketPacks

| Pack | Mode | Code status | External status |
|---|---|---|---|
| MP-N01 Boros | read_only_replay | FIXTURE_TESTED | BLOCKED_EXTERNAL |
| MP-N02 Hybrid Liquidity | fork_and_replay_only | CONTRACT_IMPLEMENTED | BLOCKED_EXTERNAL |
| MP-N03 M0 | read_only_shadow | CONTRACT_IMPLEMENTED | BLOCKED_EXTERNAL |
| MP-N04 Ethena | research_only | CONTRACT_IMPLEMENTED | BLOCKED_EXTERNAL |
| MP-N05 RWA/Horizon | research_only | CONTRACT_IMPLEMENTED | BLOCKED_EXTERNAL |
| MP-N06 Aave V4 | fork_read_only | CONTRACT_IMPLEMENTED | BLOCKED_EXTERNAL |
| MP-N07 Research Resources | testnet_or_zero_cost_mock | FIXTURE_TESTED | BLOCKED_EXTERNAL |
| MP-N08 Proof Research | offline_only | FIXTURE_TESTED | BLOCKED_EXTERNAL |
| MP-N09 Incident Corpus | offline_only | FIXTURE_TESTED | BLOCKED_EXTERNAL |

Каждый pack подключается через instrument/data/rights/target/evidence owner references в `marketpack_adapters.py`.

## 5. Boros vertical

Offline fixture path:

`bounded ingest → raw checksum → revisioned PIT state → CashflowSpec → forecast-before-outcome → mature label → independent episodes → purged walk-forward → simple/local/pooled/mechanism-transfer comparison → FDR/calibration → fees/margin/liquidity stress → source-value report → ResearchReceipt → BLOCKED_EXTERNAL verdict`.

Причина blocker: primary historical dataset, immutable pin, entitlement/terms и реальный point-in-time corpus не материализованы. Fixture нельзя повышать до QUALIFIED.

## 6. EVO-09 semantic rules

- missing outcome ≠ zero PnL;
- unsent candidate сохраняет unknown `actual_landed`;
- `label_available_at > training_cutoff` не допускается в training;
- censored/missing/future labels считаются отдельно и не превращаются в zero;
- financial atoms не складываются с latency milliseconds или PPM;
- stability/FDR/persistence требуют evidence refs;
- secret/signed payload не допускается в research telemetry.

## 7. Statistical protocol

Для transfer benchmark обязательны четыре comparator-а:

1. simple baseline;
2. target-market local-only;
3. pooled-markets;
4. shared mechanism representation + local adapter.

Используются independent episodes, purged walk-forward + embargo, FDR control, calibration/interval coverage и explicit negative-transfer result.

## 8. Upstream и incident policy

Pendle/Boros, HOT, Bunni, M0, Ethena, Centrifuge, Aave Horizon/V4, x402 и SP1 остаются REFERENCE_ONLY, пока отсутствует exact immutable pin/version, artifact-level license/terms, entitlement и conformance evidence.

Bunni v2 хранится как quarantined incident/reference corpus. Это не production adapter.

## 9. Операционный порядок

Проверки:

```bash
python scripts/verify_pr355.py --json
python -m pytest -q tests/mechanism_discovery/test_pr355_evidence_native.py tests/mechanism_discovery/test_pr355_completion.py
python scripts/verify_pr353_strategy_evolution.py --json
python scripts/verify_pr354_mechanism_discovery.py --json
python scripts/verify_repo.py
```

При любом неизвестном entitlement/deployment/license/custody/finality статус остаётся BLOCKED_EXTERNAL или INCONCLUSIVE.

## 10. Rollback

1. отключить все PR-355 packs/features;
2. detach optional collectors/adapters/consumers;
3. вернуть предыдущую research model selection;
4. quarantine invalid source/deployment/model/proof evidence;
5. сохранить append-only raw/evidence/receipt history.

Rollback не требует signing, fund recovery или remote transaction reversal, потому что PR-355 не добавляет effectful execution.

## 11. Неподтверждённые внешние действия

Не выполнялись: paid production resources, real x402 payment, wallet funding/access, transaction signing/submission, production proof backend, real Boros/HOT/M0/Ethena/RWA/Aave qualification.

`MERGED != QUALIFIED != AUTHORIZED_LIVE`.
