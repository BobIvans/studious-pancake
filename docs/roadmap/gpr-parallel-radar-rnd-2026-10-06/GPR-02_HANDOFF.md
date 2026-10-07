# GPR-02 Solana handoff — verified code, bounded observed research

GPR-02 is implemented and verified offline. Public discovery and same-bank
structural data were observed in three retained read-only campaigns. Full exact
qualification remains blocked: authenticated quotes, independently operated RPC
profiles, reviewed startup policies, Token-2022 exact pool semantics and current
JLP NAV proof are missing. No profit, anomaly recurrence, live eligibility or
production readiness is claimed. Stop before GPR-04.

## Commit and ownership receipt

| Role | Exact SHA |
|---|---|
| Published GPR-01 base | `8c59759b491b6318f259138671dccfea25f2752e` |
| First capture producer | `319773d92df7cfb01c36781d3f35146a82214199` |
| Manifest bound correction / second producer | `c070dc4f86e3b502b814a963ddbae52ef70b1523` |
| Shared Manifest generation / third producer | `e4c3e0dee6d8ff54832f1a9258dd9ffa8c0161d0` |
| Portable exporter | `da9d71998c3294fd661d780f0fe9704e874125b2` |
| Final tested code / physical issue guard | `78bac3d27e98ed634f27ee36cc0fe062d2aa21d4` |

The final report commit is the head of
`impl/gpr02-solana-radar-2026-10-06`. Its full SHA and remote verification are
recorded externally in `/workspace/shared/gpr/GPR-02_HEAD_RECEIPT.json`, avoiding
a self-referential tracked commit hash. All capture manifests bind their original
clean producer commits. Later freshness/export hardening did not produce those
physical reads. A later physical issue observer also leaves original archive
bytes unchanged. Original capture summaries and current deterministic replay
summaries are retained separately.

Changed files are enumerated in `GPR-02_HANDOFF.json`: nine isolated
`src/solana_parallel_radar` modules, one scoped CI workflow, one contract-pin
configuration, one test module, four GPR-02 reports and four portable evidence
files. Shared GPR-01, QPR-02/QPR-03, exact-graph owners, dependency declarations
and lockfiles remain unchanged from the verified base.

## Independent validation

The handoff JSON retains the exact pytest command. **306 tests passed**, with
80 GPR-02 tests and 226 GPR-01/QPR/shadow regressions, including all seven V2.2
delta tests; no failures or skips. Runtime was 15.19 seconds. Mypy passed for
nine modules; Black checked ten files; fatal lint and diff checks passed.

Tests exercise governed radar reads, exact pair and amount correlation, retained
raw reconstruction, quote freshness before and after awaited state collection,
final slot alignment, independent QPR collector delegation, actual HARD_BOUND
receipt reconstruction and existing ingest rejection. A slow collector test
advances wall time beyond quote TTL while returning fresh state and verifies
that receipts and exact handoff are denied. Positive full funnel evidence is
synthetic bytes served through existing governed collectors and independent
mock profiles; it is not mainnet qualification.

Token-2022 negatives cover unsupported extensions, TLV duplicates/padding,
malformed metadata pointer/self-mint binding, mint/freeze/fee authorities,
transfer-fee ceiling/cap and epoch rollover. Portable tests cover deterministic
replay, hash tampering, private fields and path traversal. All three real portable
archives replayed offline with hash, journal, generation and report checks.
Canonical guard dependency-generation and quota denial tests verify no wire
calls and physical_attempt=false despite logical_attempt_started=true. Successful
issue is marked only after the unchanged canonical guard grants; quote provenance
requires physical_attempt=true and HTTP 200. A nonphysical retained quote fails
before native collection.

## Retained real-data findings

| Producer | UTC interval, 2026-10-06 | Reserved attempts / HTTP 200 | Candidate observations / unique pools |
|---|---|---|---|
| `319773d9` | 05:29:15.775177–05:29:20.346949 | 8 / 7 | 28 / 27 |
| `c070dc4f` | 05:34:40.647857–05:34:45.608158 | 7 / 6 | 63 / 62 |
| `e4c3e0de` | 05:37:28.836614–05:37:34.742793 | 7 / 7 | 63 / 62 |

The first Manifest response failed the existing 20,000-node bound. A narrow
Manifest-only transport policy pins 120,000 nodes, 5,000 rows and 8,000,000 bytes;
the latest observed payload contains 37,725 nodes, 3,826 rows and 1,284,006
canonical bytes. Normalized candidates remain bounded and exact-mint filtered.
The second book invocation failed durable generation matching before a wire
read; it is a retained negative invocation, not a claimed HTTP response. Sharing
the actual provider generation and quota bucket fixed this in the third slice.
Original archive physical_attempt flags used the producer's invocation semantics;
the final code separates logical start from confirmed canonical issue. Budget
reservations and actual HTTP outcomes above remain distinct.

Latest source counts are Manifest 35, DEX Screener 10, Meteora DLMM 10 and
Raydium 8. All nine requested priority pairs appear in discovery observations:
USDG/USDC 1, USD1/USDT 1, USD1/USDC 3, xBTC_OKX/cbBTC 2, JLP/USDC 3,
BNSOL/WSOL 2, bbSOL/WSOL 2, hSOL/WSOL 1 and dSOL/WSOL 1. These counts
are source observations and may repeat a pool; the complete graph has 62 unique
pools. Index source correlation is retained; discovery does not imply depth,
fees, program ownership, exact math or startup receipt qualification.

One Manifest book was observed at market
`Dcz5oZKtqc3xJGzNJ22dwdtfCLCGqu765L7WgVuEmWZs`, source timestamp
`1791265053`, with two bid and five ask rows. It remains DISCOVERY_ONLY, with
depth and fees unverified. Widely varying displayed price rows are not treated
as profitable or executable depth.

Three Sanctum-list stake pools passed strict owner, mint, token program,
decimals, supply and current-epoch checks in the same finalized batch at
**slot 453809316, epoch 1050**, observed at
**2026-10-06T05:37:33.782285+00:00**
(`1791265053782285443` ns):

| LST | Lamports per raw token unit, exact rational |
|---|---|
| dSOL | `706065928359484 / 579483198588143` |
| hSOL | `951000346731657 / 799298249388265` |
| bbSOL | `1375087927761482 / 1171791457387481` |

These are research staking exchange-rate references. They have no redemption
fee adjustment or independent RPC quorum. BNSOL fails the strict supply check:
pool supply `9052244322004013` versus mint supply `9052244321498178`, a
505,835 raw-unit difference. Pool updated epoch and current epoch are both 1050,
so this observed rejection is a supply mismatch, not a stale-epoch finding.
The code preserves its broader fail-closed reason
`SANCTUM_RATE_STALE_OR_SUPPLY_MISMATCH`.

Both USDG and PYUSD were observed with the Token-2022 owner and decimals 6.
Their actual TLV `(type,length)` sequence was `(3,32), (12,32), (1,108),
(4,65), (16,129), (14,64), (18,64), (19,174)`: MintCloseAuthority,
PermanentDelegate, TransferFeeConfig, ConfidentialTransferMint,
ConfidentialTransferFeeConfig, TransferHook, MetadataPointer and TokenMetadata.
The conservative validator rejects types 12/4/16/14. No observed extension hash
is adopted as reviewed policy, and no full startup HARD_BOUND receipt exists.

JLP remains `CURRENT_AUM_SUPPLY_ORACLE_STATE_REVIEW_REQUIRED`; a current
pool reference or arithmetic helper does not prove current NAV. Zero 0x/Jupiter
quotes were collected: no public 0x taker/credential was configured and
`JUPITER_API_KEY` was absent. Source outcomes retain each missing input.
The official 0x economic POST contract is implemented without consuming unsigned
instructions; it lacks a source context slot. The first Raydium native capability
probe retained account owner/executable/size mismatch and BLOCKED_SINGLE_SOURCE.
That probe was never a fully stage-qualified handoff.

There are no measured quote disagreements, direct-versus-synthetic residuals,
forward recurrence, exact-qualified assets or JLP NAV residuals.

## Portable evidence

`gpr02-evidence/INDEX.json` hashes all three archives and records capture/export
heads, campaign IDs and journal heads. Each compressed archive includes original
manifest, raw events, immutable raw blobs, original capture summary, replay
summary and member SHA-256 index. Combined size is **1,131,302 bytes**:

| Archive | Compressed bytes | SHA-256 |
|---|---:|---|
| `campaign-319773d9.tar.gz` | 149,577 | `1c9597c6e6b39bb45bc165281a6666ca960206808515af75e65601b53d10d213` |
| `campaign-c070dc4f.tar.gz` | 490,451 | `eeab807d9a781dcd3d289441c60b4a9d5847eee0bb8a990e47d673aaf2ebb45d` |
| `campaign-e4c3e0de.tar.gz` | 491,274 | `b57144aa984d9e605ed689d420ebeb56b8eba91dd5e0990f7da27ae4a7162946` |

The recursive export audit passed public/redacted credential-field and request
header checks. No credential values were inspected; raw headers remain redacted.
Virtual environments, caches, proxy values, authority SQLite and database locks
are excluded. Replay reads no provider network:

```bash
.venv/bin/python -m src.solana_parallel_radar.portable replay \
  --archive docs/roadmap/gpr-parallel-radar-rnd-2026-10-06/gpr02-evidence/campaign-e4c3e0de.tar.gz
```

## Blockers and recommended next actions

`GPR-02_PROBLEMS.json` retains open blockers and resolved negative observations.
Securely bind `JUPITER_API_KEY` and `ZEROX_API_KEY`, configure an explicit public
0x taker, and run a new bounded matched quote slice. Supply reviewed independent
RPC profiles, exact pool bindings and startup policies before invoking the full
configured funnel. Keep USDG/PYUSD blocked until issuer authorities, observed
transfer semantics and the exact pool decoder are reviewed. Investigate BNSOL
with later bounded same-bank reads, retaining the supply equality check.

Review current JLP custody/AUM/supply/oracle proof and collect bounded repeated
quote/state observations before ranking economic anomalies. Compare Solana and
Sui measured coverage, costs, failure classes and qualification gaps to decide
GPR-04/05/06/07/08 priorities. Their implementation waits for that comparison.

Heat, execution_class and evidence_state remain independent; HARD_BOUND startup
receipts remain mandatory. CCTP, Wormhole and USDT0 transport stay non-atomic
REBALANCE_ONLY/CROSS_CHAIN_SIGNAL. Signer, sender, submission, live capital and
production promotion are disabled. No shared owner or subsequent roadmap stage
was implemented here.
