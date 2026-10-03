# Экспериментальные дизайны и приёмка

Все DP и DT имеют статус **PLANNED_NOT_RUN**. Старые89 T сохранены; 36 DT добавлены отдельно, всего125 спроектированных acceptance scenarios. Проверка ZIP не является выполнением этих тестов.

| ID | Эксперимент | Зависимости | Gate |
| --- | --- | --- | --- |
| DP-01 | CPMM qualification boundary and amount-local rejection | none | Unknown identity/state rejects route; expected economic rejection is reported per amount without claiming unsampled capacity. |
| DP-02 | Shared resource alias and sequential split | DP-01 | No double consumption; state read/write keys complete; joint result equals tiny exhaustive oracle within declared finite grid. |
| DP-03 | Incremental event-driven graph | DP-01, DP-02 | Same qualified candidates/evidence after each watermark; omissions only explicit budget truncation, no false completeness. |
| DP-04 | Fast state vs canonical state | DP-03 | Generation/commitment separation; p99 arrival-to-evidence reported with reject/backfill costs; no hindsight advantage. |
| DP-05 | Claims and vault semantics | DP-01 | Strict units and rights match; multi-input/output conservation; future claims excluded from spendable cash. |
| DP-06 | Credit and collateral prefix constraints | DP-05 | Every required boundary feasible; debt/fee/residual closure; flash and term funding segregated. |
| DP-07 | Versioned intents and clearing | DP-02, DP-05 | Per-user constraints and no-worse comparator; no duplicate order consumption; feed coverage explicitly bounded. |
| DP-08 | Settlement-time capital | DP-06, DP-07 | Peak and time-integrated inventory measured by asset/domain; restart never makes unknown funds available. |
| DP-09 | Cross-product payoff equivalence | DP-05 | No guaranteed-arbitrage label when residual exposure remains; stress margin and exit costs included. |
| DP-10 | Verified service unit economics | DP-01 | Verification correctness and total delivery cost measured separately from demand; no real payments. |
| DP-11 | Mechanism response and competition | DP-07, DP-10 | Per-user/LP/provider outcomes separated; no causal advantage claim from frozen order flow; losses retained. |
| DP-12 | Budgeted scale and product selection | DP-03, DP-10 | Cost per fresh validated opportunity and workflow measured; finite optimum scope explicit; unknown outcome stays unknown. |

## Планируемые проверки

| ID | Experiment | Input | Expected |
| --- | --- | --- | --- |
| DT-01 | DP-01 | WSOL symbol with wrong mint/genesis/token program/decimals | Reject settlement eligibility; symbol and revision text alone cannot qualify identity. |
| DT-02 | DP-01 | One gross-negative amount precedes a later feasible amount | Report economic rejection for first point and preserve bounded evaluation of later points; unexpected evaluator errors fail explicitly. |
| DT-03 | DP-01 | Fee denominator or protocol fee segregation outside pinned model | Reject unsupported state semantics; do not silently round fee to basis points. |
| DT-04 | DP-02 | Two virtual capacities 80+80 share real balance100 | Joint allocation cannot spend160; later path receives updated available balance. |
| DT-05 | DP-02 | Two paths share one pool but have different provider labels | Reuse canonical pool state; second path output uses first transition; evidence identity includes order. |
| DT-06 | DP-02 | Distinct singleton pools with a shared mutable hook | Do not collapse all pools as one venue; do include hook dependency and conflict when relevant. |
| DT-07 | DP-03 | Allowance/config update with no swap event | Invalidate all dependent routes, including those without a changed pool reserve. |
| DT-08 | DP-03 | Correction + retraction + duplicate event in different arrival orders | At same resolved watermark full and incremental engines produce same canonical evidence; duplicate causes no extra consumption. |
| DT-09 | DP-03 | Queue overflow, crash and durable cursor without state snapshot | Declare gap/incomplete, reload checkpoint plus backfill; no admission from cursor alone. |
| DT-10 | DP-04 | Flashblock later removed or changed | Invalidate descendant route evidence and pending capacity; no promotion to finalized truth. |
| DT-11 | DP-04 | Historical record timestamp earlier than actually available_at | Do not expose record to earlier replay decisions; report latency without look-ahead. |
| DT-12 | DP-04 | Provider loses WSS/access while HTTP discovery still works | Downgrade freshness/coverage; no inferred verified subscription. |
| DT-13 | DP-05 | Vault with zero max-functions and special documented semantics | Generic adapter quarantines; qualified product-specific limit path must provide its own proof before admission. |
| DT-14 | DP-05 | Claim pending until tomorrow or unresolved expired outcome | Exclude claim proceeds from current atomic repayment, regardless of displayed NAV or probability. |
| DT-15 | DP-05 | Two claims have same symbol but different maturity/condition/controller | Distinct identity; reject false merge/netting; account for each residual asset. |
| DT-16 | DP-06 | Unhealthy intermediate prefix but healthy final state | Reject unless the exact protocol/context explicitly defers that check; never generalize across calls. |
| DT-17 | DP-06 | Loan fee and pool fee already embedded in output | Repayment and other costs each counted exactly once with unit/source tags. |
| DT-18 | DP-06 | Shared collateral borrowed through two adapters | Combined health/caps applied once over common underlying account; no doubled credit. |
| DT-19 | DP-07 | Exclusive order presented to non-eligible filler | Reject or price valid soft override according to pinned reactor; never bypass exclusivity. |
| DT-20 | DP-07 | 50 cached recent orders labeled complete market feed | Coverage remains unknown/truncated; missing order cannot be treated as absent market demand. |
| DT-21 | DP-07 | Batch raises aggregate surplus but worsens one user | Reject under the declared per-user comparator and fill constraints. |
| DT-22 | DP-08 | Destination fill succeeds but repayment proof still pending | Keep capital committed; receivable is not spendable inventory. |
| DT-23 | DP-08 | Duplicate fill/refund evidence arrives after restart | Idempotent reconcile; no duplicate credit or second allocation of unsettled funds. |
| DT-24 | DP-08 | Fast fill then long proof delay, timeout or origin reorg | Stress capital-time and failure cost; no flashloan or instant turnover classification. |
| DT-25 | DP-09 | Two BTC perps use different oracle/index/session/margin domain | Do not call payoff equivalent from ticker; keep basis and funding exposure. |
| DT-26 | DP-09 | Three of four rate-hedge legs fill, then exchange halts | Track residual exposure and stress exit loss; no completed hedge claim. |
| DT-27 | DP-09 | Exact same notionals but different accrual day-count/settlement periods | Reconcile cashflow units and calendar; difference remains explicit until proved zero. |
| DT-28 | DP-10 | Valid payment receipt but incorrect exact output or wrong state | Verifier rejects result independently of payment or supplier identity. |
| DT-29 | DP-10 | Two suppliers return identical data from one upstream | Evidence lineage counts one source; failure correlation is shared. |
| DT-30 | DP-10 | Cheap quote costs more after verification/retry/support | Local baseline wins; marketplace not promoted on nominal bid alone. |
| DT-31 | DP-11 | Dynamic fee looks better only under frozen exogenous flow | Label conditional replay; require elastic response stress before broader conclusion. |
| DT-32 | DP-11 | Auction fee transfer shown as newly created welfare | Separate trader, LP, supplier and solver accounting; no double-counted surplus. |
| DT-33 | DP-11 | Profit disappears after subsidies or competitor response | Record failed hypothesis; no autonomous expansion from pre-subsidy score. |
| DT-34 | DP-12 | Candidate uses a resource dimension absent from budget | Reject incomplete resource model; unknown budget is not unlimited capacity. |
| DT-35 | DP-12 | Queue/search/amount/provider budget exhausts mid-run | Return explicit truncation reason and evaluated subset; do not label no-opportunity or global optimum. |
| DT-36 | DP-12 | LLM suggests new chain/provider/model or data contains instructions | Treat as untrusted proposal; no auto-admission, remote mutation, signer or schedule creation. |

## Единый result capsule для будущего запуска

Обязательные поля: experiment ID, commit/tree, model and decoder revisions, raw data IDs/hashes/rights, source lineage, available_at, exact units, declared universe, seed, baseline, budgets, truncation, result, error classification, independent verifier result, measured runtime/cost и unresolved limitations. Выходы сейчас null/NOT_RUN.

Для correctness нужны независимые protocol vectors или pinned differential traces, а не второй вызов той же формулы. Для speed нужен одинаковый аппаратный и workload context. Для profit требуется after-cost cashflow ledger; benchmark pass не является доказательством спроса. Для mechanism claims фиксируется behavioral model и различаются conditional replay и causal inference.

## Когда расширять исследование

Изменять только одну из осей за итерацию: новый model, domain, product, latency tier или число одновременно рассматриваемых markets. Если невозможно локализовать ошибку до exact action/state evidence, expansion останавливается. Live gate в этой программе отсутствует.
