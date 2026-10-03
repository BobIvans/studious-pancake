# 64 дополнительных acceptance scenarios

**DESIGNED_NOT_RUN.** Это критерии будущих изменений, не выполненные tests. Исходные T-01..89 и DT-01..36 сохранены; всего в архиве 189 planned acceptance scenarios. Проверка целостности ZIP не означает прохождение этих сценариев.

| ID | Этап | Сценарий | Дано | Ожидание |
| --- | --- | --- | --- | --- |
| PT-001 | PM-01 | Canonical identity | Same ticker on two chains or token programs | Reject cross-identity coupling even if decimals match |
| PT-002 | PM-01 | Amount-local rejection | First amount has zero/negative output; later amount is valid | Return a per-amount reason and retain valid samples; unknown state rejects all affected samples |
| PT-003 | PM-01 | Sizing owner | SOL/WSOL and USDC amounts passed to PR118 boundary | Lamports accepted only with proper identity; other units require an explicit reviewed owner extension |
| PT-004 | PM-01 | Route invariants | Reordered edges, repeated venue, stale leg and slot mismatch fixtures | Stable semantic ID where appropriate; changed evidence ID; invalid route rejects without quote scaling |
| PT-005 | PM-02 | Stock versus flow | TVL, OI, volume and stablecoin cap loaded together | Store distinct metric types; aggregation into one size is invalid |
| PT-006 | PM-02 | Routed flow | Aggregator hop and underlying DEX fill describe one trade | Underlying gross volume and user flow remain separate without double counting |
| PT-007 | PM-02 | Available-at | A revised historical series appears after the research cutoff | Earlier decision receives only the earlier available version |
| PT-008 | PM-02 | Missing coverage | A venue disappears from one source | Coverage decreases or is unknown; absent data never becomes zero activity |
| PT-009 | PM-03 | Retry budget | One job causes three physical attempts and two billable responses | Charge actual request/credit units through the existing authority |
| PT-010 | PM-03 | Entitlement expiry | Provider key plan or license generation changes | Cancel or re-admit affected jobs; do not keep stale rights |
| PT-011 | PM-03 | Unlimited free assumption | Mainnet paid stream selected by a free profile | Reject profile or require separately budgeted eligible source; no purchase |
| PT-012 | PM-03 | Quota fairness | Discovery flood competes with near-deadline hot work | Bound queue and preserve policy fairness without unbounded retries |
| PT-013 | PM-04 | Orderbook gap | Snapshot and sequence updates have a missing range | Invalidate book and dependent candidates until documented resync |
| PT-014 | PM-04 | Absolute level size | Coinbase level size changes from 7 to 3 | New size is 3, not 10; zero removes it |
| PT-015 | PM-04 | Fork/reorg | Removed log or Solana fork invalidates an applied update | Retract dependent evidence and reconstruct from valid ancestor |
| PT-016 | PM-04 | Crash restore | Process dies between raw append, state application and cursor commit | Recovery reconstructs a consistent hash without skipping or double applying |
| PT-017 | PM-05 | Rights aliases | Two stablecoins share peg text but different redemption access | Do not create an exact conversion relation |
| PT-018 | PM-05 | Maturity claim | PT/YT or RWA claim pays later | Separate dated cashflow from immediate assets and flashloan closure |
| PT-019 | PM-05 | Vector transformation | LP split has two outputs and one input | All asset deltas and conservation constraints explicit; no single-edge scalar approximation |
| PT-020 | PM-05 | Eligibility drift | Whitelist or product cap changes | Invalidate relation eligibility generation before candidate admission |
| PT-021 | PM-06 | Worker determinism | Same valid frame searched with 1, 2 and 4 workers | Same bounded candidate set and stable ordering, independent of completion order |
| PT-022 | PM-06 | Bound exhaustion | Expansion/candidate limit reached | Report truncation and explored coverage; no full-graph completeness claim |
| PT-023 | PM-06 | Targeted invalidation | One pool changes while an unrelated component is stable | Invalidate all dependent candidates and preserve unaffected work |
| PT-024 | PM-06 | Evidence identity | Same semantic route with new state or amount | Semantic/evidence identities handled separately without duplicated logical opportunity |
| PT-025 | PM-07 | Shared pool capacity | Two paths draw from the same pool reserves | Joint transitions recompute outputs; independent quote sums rejected |
| PT-026 | PM-07 | Order sensitivity | A→B and B→A path execution orders differ | Evaluate both bounded orders and bind selected evidence to order |
| PT-027 | PM-07 | Finite optimality | Best amount lies outside sampled integer grid | Report best sampled point only; do not assert continuous optimum |
| PT-028 | PM-07 | Cost additivity | Extra path repeats base fee assumption or adds one fixed cost | Charge correct transaction-level and per-leg costs without double counting |
| PT-029 | PM-08 | Read/write locks | One candidate reads an account another writes | Conflict even if their writable sets do not intersect |
| PT-030 | PM-08 | Read/read sharing | Independent routes read the same immutable/versioned oracle | No lock conflict solely for read/read; stale oracle still rejects |
| PT-031 | PM-08 | Lender and payer | Disjoint swap pools share reserve cash or fee payer | Conflict/capacity restriction survives separate worker IDs |
| PT-032 | PM-08 | Hidden accounts | Adapter omits a hook, fee recipient or shared margin account | Qualification rejects incomplete footprint instead of assuming independence |
| PT-033 | PM-09 | Two-process reservation race | Two workers reserve same attempt identity | Exactly one authoritative reservation and version transition |
| PT-034 | PM-09 | Zombie worker | Old worker completes after a new fencing generation is granted | Reject old output and retain current authority state |
| PT-035 | PM-09 | Pre-submission expiry | Pure compute job expires before any external side effect | Release only its allowed reservations through canonical authority |
| PT-036 | PM-09 | Unknown external outcome | Future lifecycle evidence cannot determine settlement | Keep economic hold; compute TTL never reuses uncertain funds |
| PT-037 | PM-10 | Overload | Input rate exceeds processing budget for sustained interval | Bound memory/queue and expose dropped/coalesced work without hiding state gaps |
| PT-038 | PM-10 | Tail deadline | A high-score job finishes after its route deadline | Discard admission despite valid old simulation |
| PT-039 | PM-10 | Cache identity | Same pool amounts but decoder/fee/frame version changed | Cache miss or invalidation; never reuse evidence across versions |
| PT-040 | PM-10 | Network partition | Remote stateless worker loses coordinator access | Cannot reserve or promote work locally; results remain unadmitted |
| PT-041 | PM-11 | Finite selection optimum | Six-route illustrative fixture in this archive | Selected B,C,E score20 versus greedy18 at max3; shared payer admits only best single candidate |
| PT-042 | PM-11 | Missing budget dimension | Claim includes margin or data quota absent from supplied budgets | Reject incomplete budget rather than implicitly treating it as unlimited |
| PT-043 | PM-11 | Correlated stress | Two strategies depend on same oracle/provider/collateral | Joint scenario loss includes common shock; additive tail score not labeled CVaR |
| PT-044 | PM-11 | Sequential reuse | Loan repaid in one modeled wave then another route considered | Recompute new state/capacity; do not use pending or failed repayment as cash |
| PT-045 | PM-12 | Flash premium change | Governance or reserve revision changes premium | Recompute exact repayment; reject stale terms binding |
| PT-046 | PM-12 | Multiasset debt | One borrowed asset is short by one atom but USD total is positive | Reject closure; no cross-asset scalar offset |
| PT-047 | PM-12 | Shared lender cash | Several Morpho markets map to one contract token balance | Count capacity once under common resource identity |
| PT-048 | PM-12 | Scope boundary | Flash principal expected to persist across a bridge, bundle transaction or resting order | Reject unsupported funding scope; inventory path remains separate |
| PT-049 | PM-13 | Look-ahead join | Faster feed arrives before a delayed source timestamp suggests | Use available_at plus transport history; no future observation enters features |
| PT-050 | PM-13 | Multiple testing | Many pairs/lag windows tried and only winners retained | Register all trials and control chosen test family with dependence-aware validation |
| PT-051 | PM-13 | Serial dependence | Many overlapping trades derived from one shock | Report effective independent episodes and purged/embargoed holdout |
| PT-052 | PM-13 | Null and latency controls | Independent series and injected feed delays generate apparent lead/lag | Reject unstable relation or mark insufficient evidence; cost-adjusted result remains separate |
| PT-053 | PM-14 | Queue optimism | Quote touches best price without consuming queue ahead | No automatic full fill; simulate explicit queue bounds |
| PT-054 | PM-14 | Cancel race | Market moves during cancel acknowledgment delay | Account for fills during delay and persist residual inventory |
| PT-055 | PM-14 | Cash classification | Resting maker quote funded only by temporary flash principal | Reject funding plan; owned inventory/eligible credit and collateral required |
| PT-056 | PM-14 | Markout accounting | Earned fees accompany adverse price moves | Report total mark-to-market PnL, hedges and inventory costs, not fees alone |
| PT-057 | PM-15 | Per-user clearing | Aggregate surplus positive but one order limit violated | Reject allocation; collective objective cannot override individual constraints |
| PT-058 | PM-15 | Compute evidence fraud/error | Provider signs result that fails independent semantic check | Reject payment eligibility in model; signature alone is not correctness |
| PT-059 | PM-15 | Strategic response | Mechanism changes incentives from frozen historical flow | Report sensitivity over response models, not a causal guarantee |
| PT-060 | PM-15 | Subsidy removal | Service appears used only while rewarded | Separate paid retained demand from incentives and internal self-trades |
| PT-061 | PM-16 | New-chain identity | Chain name/ID matches but genesis or deployment differs | New qualification required; never auto-enable by ticker/chain label |
| PT-062 | PM-16 | All-free coverage claim | Catalog contains public, paid and unverified endpoints | Expose access tiers and tested coverage denominator; no full-market claim |
| PT-063 | PM-16 | Disabled runtime boundary | Research profile loaded with orderbook or live options | No activation; existing disabled strategy and execution boundary preserved |
| PT-064 | PM-16 | Scale success criterion | More workers raise requests but not useful timely evidence | Fail scale gate or reduce workers; no success based on raw throughput alone |

Фикстуры должны использовать fake clocks, pinned raw evidence и детерминированный порядок. Для process races нужны контролируемые barriers/crash points вместо случайных sleeps. Property tests применять там, где проверяется экономический инвариант, а не зеркалируется implementation. Network smoke подтверждает только конкретный endpoint/payload в момент запуска; он не заменяет replay и qualification.

Из готового проверено только: числовая иллюстрация выбора шести вымышленных работ, размеры данных, целостность JSON/links/dependencies/hashes и существование указанных paths в main. Repository modules и новые стратегии при упаковке не запускались.
