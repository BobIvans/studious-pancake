# Adapter contracts, data shape и acceptance tests

Цель — дать Codex implementation-ready contracts, но подключать их через текущих owners. Это не инструкция создать отдельный production stack.

## A. Feed source contract

Proposed boundary: Shred/Geyser feed adapters return immutable observations to existing source governance / market capture owner.

Required observation envelope:
- provider_id, product_id, operator_id, correlation_group_id;
- endpoint_region and transport_kind (UDP_SHREDS, GEYSER_GRPC, WS, PREPROCESSED_TX);
- schema_version, provider_session_id, sequence/packet identity;
- slot, parent/root/commitment status, shred/FEC index and completeness metadata where available;
- provider timestamp, local monotonic receive timestamp, decode-ready timestamp;
- raw_payload_hash, decoded_payload_hash, source config generation;
- gap, duplicate, reorder, reconnect and backfill flags;
- terms/quota profile id and source authority id.

Rules:
- Unknown timestamp/fork/order/completeness must remain typed UNKNOWN.
- A tentative shred is not a complete rooted account state.
- Store enough raw payload/hash to replay and independently verify.
- On gaps/reorgs, invalidate dependent quotes rather than silently retaining the last good price.
- Two feeds from one provider/operator or shared upstream must not be counted as independent quorum members.
- Keep the existing provider catalog and durable store; no new source registry.

Tests:
1. duplicate/reordered packets are deterministic and idempotent;
2. gap invalidates the affected account generation;
3. root/slot rollback removes stale dependent quote;
4. parser reconnect does not produce synthetic complete state;
5. independent-provider quorum respects correlation groups;
6. source freshness expiry blocks candidate creation;
7. exact raw bytes replay to identical parsed event hashes.

## B. Parser contract

Use an adapter to the repository’s existing canonical parser/events, not an alternate market model.

Every emitted event binds:
- chain/genesis and slot;
- signature + transaction index + instruction index + inner-instruction path where available;
- program id, account keys, pool id and canonical mint/token program identities;
- token decimals/extensions and raw integer amount units;
- input/output direction, event type and raw event hash;
- parser crate version/commit and schema version;
- feed source provenance and state generation.

Tests:
- protocol version discrimination;
- malformed/truncated account/log rejection;
- decimals and Token-2022 transfer-fee/hook cases;
- inner CPI and top-level direct instruction paths are distinguished;
- unknown discriminator fails closed;
- parser output is compared with independent fixtures and current repo decoder;
- benchmark p50/p95/p99 on the exact production hardware/profile. Do not assert 10–20 μs as guaranteed.

## C. Anomaly hint contract

KADES/CADES is not a verified dependency today. The optional external hint schema must be:
- provider/model version + endpoint/product;
- observation and source-generation identifiers;
- pool/program identity and event window;
- signal type, score, explanation code and expiry;
- false-positive/recall benchmark dataset and confidence interval;
- terms for retention and model training.

Hint consumer may increase analysis priority only. It cannot build, route, fund, sign or send a transaction. Missing/expired hints have no effect on correctness.

## D. Simulation contract

A pmm-sim scenario is immutable:
- upstream repo URL, commit SHA, LICENSE digest, build-toolchain and cargo.lock digest;
- pmm-sim version and LiteSVM/Magnus commit pins;
- venue, program id, instruction variant, token programs, pool id;
- complete account set, data hashes, owner/rent/lamports and context slot;
- route kind (direct, single, multi) and amount grid;
- expected result, logs, CU, error/rejection, output balance delta;
- source evidence generation and fixture-vs-live label.

Tests:
1. one direct route per supported AMM instruction version;
2. multi-route nested CPI correctness;
3. unsupported program/version rejection;
4. differential against the repository’s exact quote kernel / independent test vector;
5. compare simulator to RPC simulate only within the same state generation;
6. stale account / missing bin / missing tick / changed oracle / altered fee produce typed rejection;
7. split route results aggregate exactly with shared resources reserved once;
8. simulator never upgrades fixture evidence to live qualification.

## E. Route builder contract

Both Jupiter /build and 1000xsh/swaps adapters must emit an intermediate plan and cannot submit.

Required plan fields:
- input/output mint + token-program identity;
- raw amount_in and min_amount_out in base units;
- route legs, protocol/program/pool ids and account metas;
- input state hashes, slot, source generation and quote expiry;
- instruction bytes/hash and lookup table addresses with provenance;
- CU estimate and actual simulation CU;
- fee/tip/rent components, lender id/fee and repayment mint/amount;
- output guard type: explicit venue min-out, wrapper min-out, or same-tx post-balance assertion;
- reason for BLOCKED/NO_TRADE and unsupported venue feature flags.

Hard gate: if a venue ignores or omits min-out (e.g., HumidiFi caveat in upstream swaps notes), do not trust builder-provided minimum. Require a same-transaction post-balance/repayment assertion proven against exact semantics; otherwise reject.

Tests:
- same-input/same-context route comparisons;
- no quote extrapolation across amount or slot;
- output floor actually trips in simulation;
- all account owners/program ids match;
- Token-2022 fee/hook and decimals applied;
- compute and packet-size caps;
- same-transaction borrow/repay invariant;
- no transaction signing or RPC submission within route-builder module.

## F. Relay sender contract

Future interface may normalize provider operations, but it must preserve provider semantics. Proposed fields:
- provider_id, product_id, endpoint_region, auth_profile reference (never secret value);
- submission_mode (RPC_SEND, SWQOS, SINGLE_BUNDLE, MULTI_TX_BUNDLE);
- accepted transaction format and whether provider transforms/forwards bytes;
- tip mechanism, tip account/instruction requirements, min/max and dynamic policy;
- separate off-chain/provider fees, per-landed fees, refund/rebate terms and evidence;
- rate limit, idempotency behavior, retry semantics, expiry behavior;
- ACK type, landing status API, settlement source and finality semantics.

A normalized result must distinguish:
- REJECTED_BEFORE_ACCEPT;
- ACCEPTED_BY_PROVIDER;
- FORWARDED_OR_AUCTIONED;
- SIGNATURE_SEEN_ON_CHAIN;
- CONFIRMED;
- FINALIZED_AND_ECONOMICALLY_RECONCILED.

No result before the last state is “success”. ACK or bundle id is not settlement.

## Global acceptance / test gates

- no secret in code, logs, config template or repo;
- no credentials probing; provider access and quotas come from authorized operator manifest;
- source provenance + replay + negative evidence preserved;
- all amounts use raw integer base units and exact rounding rules;
- one current state generation across full route;
- each lender capacity and fee proven through R02 and builder conformance through R03;
- each candidate exact simulation passes R05;
- all fees and failure costs enumerated;
- all shared pools/resources reserved by existing owner;
- all shadow/paper outcomes durable and idempotent;
- production installed composition only; no parallel runner;
- send_enabled, sign_enabled, live_enabled, borrow_enabled remain false.


## G. Prop AMM caller-profile differential test (pmm-sim)

Use pmm-sim synthetic caller profiles only inside local LiteSVM. Compare DIRECT, MAGNUS_NATIVE, JUPITER_SIM, DFLOW_SIM, OKX_SIM and TITAN_SIM on one immutable slot/account/program snapshot, per market/version/direction/amount. Save caller delta bps, raw outputs, round-trip spread, CU, errors, program/account hashes and provenance.

The simulator caller profile is a local Magnus router binary loaded under the selected aggregator ID. It is not the genuine Jupiter/DFlow/OKX/Titan executable and cannot be used in a production transaction.

Acceptance:
- all profiles use exact same raw amount, mints, token programs, market and snapshot digest;
- direct/CPI instruction account ordering is verified;
- every Prop AMM variant is benchmarked independently;
- failures and zero/no-difference profiles are preserved;
- at least multiple independent slots are tested before claiming persistent preference;
- report best simulated caller and best real executable route separately;
- any production route must use the official genuine aggregator route/build and pass R13/R05; no spoofed program ID.
