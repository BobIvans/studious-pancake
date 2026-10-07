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

For bounded ingestion instantiate `DurableRawJournal(path, max_journal_bytes=...)`.
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
