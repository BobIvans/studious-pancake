# Offline local intelligence V2

Use the existing isolated checkout; do not create a worktree unless requested.
Python 3.13 is required. Install `requirements.lock` and `requirements-dev.lock`
(these include the analytics extra), then install the project with `--no-deps`.

The state directory defaults to `/workspace/local-intelligence-data`, outside the
checkout. Override it with the global `--state-root` argument. No daemon is needed.

```bash
python -m src.intelligence.cli repo scan --repo .
python -m src.intelligence.cli repo benchmark
python -m src.intelligence.cli repo export --mode RUNTIME_PATH --seed paper-shadow --out /workspace/paper-context
python -m src.intelligence.cli storage status --journal /path/to/agg02.db
python -m src.intelligence.cli storage rollups --journal /path/to/agg02.db --out /workspace/rollups.json
python -m src.intelligence.cli storage compact --journal /path/to/agg02.db --out /workspace/raw.parquet
python -m src.intelligence.cli storage retention-dry-run --journal /path/to/agg02.db --before 24h
python -m src.intelligence.cli report bundle --campaign /path/to/campaign.json --out /workspace/report
python scripts/verify_local_intelligence_v2.py --out /workspace/acceptance
```

The snapshot uses committed Git objects at the pinned SHA. Uncommitted edits are
not silently represented as committed source. Scan again after committing changes.
Source parsing currently covers Python. Other languages, submodules, symlinks,
secret metadata and oversized files are explicit coverage gaps. Tests/config
relations use a declared filename heuristic; import edges come from static ASTs.
Dynamic imports are not inferred. Context budgets count exact source bytes;
JSON hex encoding adds transport overhead. Continuation is bound to snapshot and
selection parameters. `repo backup` and `repo restore` operate on a new SQLite copy.

Market bytes stay in AGG-02. Compaction uses its publisher and replay reader with
ZSTD. Reversible pruning removes inline SQLite payloads, preserving all envelopes,
cursors and gaps, and keeping exact payload replay in the verified Parquet file.
Keep that file and its manifest together with the journal; moving or deleting it
breaks replay and raises an explicit error. Pruning does not VACUUM the SQLite file,
so logical payload savings are distinct from filesystem space reclaimed.

`prune` is dry-run unless `--execute` is specified. Execute requires `--journal`,
`--records`, `--references`, `--compaction`, `--retention` and `--out`. The references
file has `records` and `inventory_complete`; unknown ownership coverage blocks
execution. Retention records must prove age, representation, provenance,
compaction, replay, sample survival and absence of experiment/evidence references.
Do not assert those facts without checking the applicable owners. Journal pins
are checked again under the write lock. This first release does not permanently
destroy Parquet payloads. Tombstones are written before mutation and completion
receipts afterwards. Failed prepared receipts are reconciled against the owner.

Storage capacities were doubled at the operator's request: the default data
allowance is now up to 60 GB (previously 30 GB), using at most the free disk above
the unchanged reserve of max(30 GB, 25% of total disk). The nominal healthy
allowance is 16 GB rather than 8 GB; smaller measured capacity reports pressure.
This doubles the previous dynamic allowance, including on small disks, without
claiming more physical space than exists. Explicit configured budgets must fit
the measured spare disk. Parquet partitions default to 20,000 rows / 128 MiB raw
payload, repository blobs to 16 MiB, and portable repository archives to 1 GiB
uncompressed content. Context/inference budgets and evidence ages retain their
separate meanings. Historical receipts record the limits at their generation.

There is no automatic "delete the oldest 25%" rule. Pruning is dry-run by
default; explicit execution checks each event's age (default 24 hours), pins,
reference inventory, samples, representation, compaction and exact replay proof.
Only eligible payloads in the supplied verified partition are offloaded. Exact
Parquet payloads remain available for replay; this is not permanent erasure or
a guarantee that SQLite immediately shrinks. The 25% number is a disk reserve,
not a deletion fraction. Admission at a configured journal cap blocks new events;
it does not silently evict old data. Permanent archive expiry is not implemented.

For bounded ingestion instantiate `DurableRawJournal(path, max_journal_bytes=...)`.
The measured dynamic allowance is a policy/report value; it is not automatically
wired to every existing journal writer. Journal byte enforcement requires that
explicit cap. An omitted cap keeps the existing owner's uncapped default. The
CLI does not install a background expiry loop, and caller-supplied journal caps
remain exact byte values rather than silently being multiplied.
Admission stops with `AGG02_STORAGE_PRESSURE_ADMISSION_BLOCKED` before a new event
when the measured journal/WAL plus reserved expansion would exceed its cap. The
caller must handle pressure by pausing collection/verified compaction; it must not
silently drop evidence. Existing journal callers retain their current defaults.

Episode receipts wrap the canonical `MarketEpisode`; source raw IDs are pinned in
the same AGG-02 journal. Use `build_market_episode` with a sealed existing research
manifest and availability-bound decisions. PRE_QUOTE features reuse the canonical
dataset validator. Terminal outcomes are labels, not earlier-stage features.

Campaign JSON contains `experiment` (sealed identity), `episodes` (sealed receipts),
optional `provider_rows`, `qualification` (AGG-04 episodes/variants/probes and
`survival_horizon_ms`), `paired_results`, `delay_samples`, `laya_triage`, `findings`,
`window` and `data_kind`. Reports mark absent measurements NOT_OBSERVED rather
than manufacturing zero. Paired comparison and stress reuse qualification owners.

Laya is optional. Python callers supply a local backend callable; CLI accepts
recorded typed responses via `--decisions`, keyed by compact-state SHA, and an
explicit `--model-version`. No model/runtime is bundled or downloaded. Without
one the workflow works offline and reports NOT_OBSERVED for model scores. Calls
receive only compact retrieved states (16 KiB maximum), not the raw corpus.
Typed scores are cached by state/model/prompt/policy. High-confidence decisions
can extend retention and queue review; low confidence does not shorten it. Model
receipts cannot grant deletion, signing, submission or live trading authority.

Offline acceptance fixtures demonstrate mechanics, not a real 24h market campaign
or profitable strategy. A real campaign must supply measured owner receipts.

For the initial sender-free Mainnet campaign the configured RPC is
`SOLANA_RPC_HTTP=https://api.mainnet.solana.com` per the operator's choice. Supply
`FLASHLOAN_WALLET_PUBLIC_KEY` through environment settings using a dedicated
research wallet you control. No private key or seed is needed. The ordinary paper
runtime remains fail-closed without the public address. Native capture now derives
its RPC endpoint and host admission from the existing public-read entitlement, so
switching RPC providers requires configuration rather than code changes. HTTPS,
genesis checks, read-method admission and provider quota ownership remain required.
Endpoints requiring credentials must use the existing reviewed credential route;
URL user-info and query credentials are denied by the anonymous capture path.

The shared HTTP transport honors 429 and numeric/HTTP-date Retry-After. A server
delay longer than the bounded retry window blocks the retry and retains a host
cooldown; it is never truncated into an early retry. Short backoff stays within
the total request deadline, and each physical attempt is charged by the existing
governance hooks. Terminal 429 is a typed retryable failure even for non-JSON error
bodies. Repeated calls during cooldown do not perform another HTTP request.

Run the bounded installed paper owner with:
`python -m src.intelligence.cli campaign run --out /workspace/paper-campaign --timeout-seconds 30`.
The output directory must be empty. Missing public configuration writes a sealed
BLOCKED receipt without starting a child process. This bounded readiness run is
not a measured 24-hour campaign: qualification still requires the canonical
paper vertical, measured observations, and its acceptance receipts.


## Automatic storage-pressure manager

The manager is invoked explicitly by the operator/runtime supervisor; it chooses
the pressure action automatically from measured managed bytes versus the current
safe intelligence budget:

- below 80%: `NORMAL`, no action;
- 80–90%: `COMPACT`, target 75%;
- 90–95%: `PRUNE`, target 80%;
- 95% or above: `CRITICAL`, target 85%; insufficient safe reclaim requires
  admission pause instead of evidence loss.

These targets are hysteresis points, not percentages of rows to delete. The
manager calculates the byte shortfall and selects the oldest *eligible* inline
payloads only until that byte target is covered. Owner pins are checked before
selection and again before mutation.

Dry-run:

```bash
python -m src.intelligence.cli storage pressure \
  --journal /path/to/agg02.db \
  --records /path/to/retention-records.json \
  --references /path/to/reference-inventory.json \
  --out /workspace/pressure
```

Execute:

```bash
python -m src.intelligence.cli storage pressure \
  --journal /path/to/agg02.db \
  --records /path/to/retention-records.json \
  --references /path/to/reference-inventory.json \
  --out /workspace/pressure \
  --execute
```

Execution requires a complete references inventory. It creates an exact
event-scoped ZSTD Parquet partition, verifies replay, rebuilds the retention
receipt with compaction/replay proof, and only then offloads eligible inline
payloads. The Parquet copy remains authoritative for exact replay.

The manager never runs `VACUUM` automatically. Offloaded SQLite pages become
reusable, but physical file shrink is not guaranteed. A separate maintenance
operation may later qualify physical compaction when enough temporary disk
headroom exists and the writer is stopped.

At CRITICAL pressure, if there are not enough safe reclaim candidates or there is
not enough reserve-preserving headroom to create the verified Parquet partition,
the result is `ADMISSION_PAUSE_REQUIRED`. New evidence must pause rather than
silently evict protected data.

Pressure retries can supply `--batch-id <stable-owner-batch-id>`. The manager
locks the existing journal inode across processes, persists its original plan,
clock and selection before compaction, and seals a terminal receipt. Reusing a
batch with different inputs fails closed. A restart after an offload resumes the
same partition/tombstone rather than creating duplicate archives; cached success
also re-verifies exact Parquet replay. CLI admission-pause verdicts exit with 3.
NORMAL performs read-only measurement and creates neither directories nor locks.
Output partitions on another filesystem are rejected. Compaction requires safe
reserve-preserving headroom; post-operation physical pressure is measured again.
Logical page reuse cannot clear an unchanged CRITICAL physical verdict.

The existing `RepeatedInstalledPaperService` invokes an owner-supplied
`storage_pressure_boundary` before each durable collection batch and after the
typed `AGG02_STORAGE_PRESSURE_ADMISSION_BLOCKED` has unwound the append transaction.
`StoragePressureBoundary` uses the same manager, retention, Parquet and tombstone
receipts as the CLI, with an authoritative inventory callback. The A3 service and
CORE-V1 materialized batch source forward this explicit source capability. The
supervisor remains sequential, and its canonical durable authority records pause
incidents; both installed entrypoints return a blocked exit code on pressure stop.
An admission-blocked batch is not retried blindly even if compaction completes.

Runtime collection binding is `BLOCKED_NOT_WIRED` when the source has no pressure
port. The current reviewed installed dependency resolver produces a qualified
draft source, not a long-running AGG-02 raw collector with a complete retention
inventory. Native CPMM qualification is bounded capture and has no AGG-02 raw
journal binding. No journal path, reference inventory or new scheduler is guessed
for these sources. Owners supplying that binding expose the explicit port; a
missing/invalid inventory blocks reclamation, and CRITICAL pauses admission.
