# CLI + Reports

## Repo intelligence

~~~bash
python -m src.intelligence.cli repo scan --repo .
python -m src.intelligence.cli repo status
python -m src.intelligence.cli repo export --mode WHOLE_REPO_INDEXED --out out/repo
python -m src.intelligence.cli repo export --mode INTERCONNECTED_FILES --seed src/paper_shadow/runner.py --out out/paper
python -m src.intelligence.cli repo export --mode RUNTIME_PATH --seed paper-shadow --out out/runtime-path
python -m src.intelligence.cli repo delta --from <snapshot>
python -m src.intelligence.cli repo benchmark
~~~

## Storage

~~~bash
python -m src.intelligence.cli storage status
python -m src.intelligence.cli storage forecast --since 6h
python -m src.intelligence.cli storage retention-dry-run --before 24h
python -m src.intelligence.cli storage compact --before 24h
python -m src.intelligence.cli storage prune --dry-run
~~~

Prune without --dry-run must require a verified compaction/retention receipt.

## Laya

~~~bash
python -m src.intelligence.cli laya triage-observations --since 1h
python -m src.intelligence.cli laya triage-episodes --since 24h
python -m src.intelligence.cli laya score-repo --goal "qualification blocker"
~~~

Laya input is compact retrieved state, not raw whole-corpus text.

## Reports

~~~bash
python -m src.intelligence.cli report build --since 24h --out out/report
python -m src.intelligence.cli report compare --baseline <experiment-A> --candidate <experiment-B>
python -m src.intelligence.cli report bundle --experiment <id> --formats md,txt,json,zip
~~~

Expected bundle:

- 00_SUMMARY.md
- REPORT.txt
- MANIFEST.json
- STORAGE.json
- RETENTION.json
- FUNNEL.json
- STRATEGY_METRICS.json
- PROVIDER_UTILITY.json
- DATA_QUALITY.json
- RESOURCE_USAGE.json
- NEGATIVE_EXAMPLES.jsonl
- TOP_EPISODES.jsonl
- LAYA_TRIAGE.jsonl
- FINDINGS.jsonl
- EVIDENCE_REFS.jsonl
- CHANGE_VS_BASELINE.json

## Required 24h answers

The report must answer with evidence:
- bytes seen / retained / compacted;
- estimated disk days remaining;
- observations → candidates → simulation → reconciliation → paper outcomes;
- top rejection reasons;
- provider latency/stale/error/quota;
- provider unique candidate contribution;
- top pairs/routes;
- strategy baseline comparison;
- rare negative examples;
- new failure classes;
- Laya-pinned episodes;
- exact repo/config/experiment identity.

No missing data should be turned into zero.
Use UNKNOWN / NOT_OBSERVED / BLOCKED explicitly.
