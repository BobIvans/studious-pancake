#!/usr/bin/env python
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.decision.dataset import DecisionDatasetBuilder
from src.decision.model import train_model, evaluate_model, replay_quota, load_artifact


def main() -> int:
    p = argparse.ArgumentParser(prog="bot")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("decision-dataset-build")
    b.add_argument("--from", dest="sources", nargs="+", required=True)
    b.add_argument("--as-of", required=True)
    b.add_argument("--out", required=True)
    t = sub.add_parser("decision-model-train")
    t.add_argument("--dataset", required=True)
    t.add_argument("--config")
    t.add_argument("--out", required=True)
    e = sub.add_parser("decision-model-evaluate")
    e.add_argument("--dataset", required=True)
    e.add_argument("--artifact", required=True)
    e.add_argument("--as-of", required=True)
    e.add_argument("--report", required=True)
    r = sub.add_parser("decision-model-replay")
    r.add_argument("--dataset", required=True)
    r.add_argument("--artifact", required=True)
    r.add_argument("--quota-policy", required=True)
    r.add_argument("--json", action="store_true")
    i = sub.add_parser("decision-model-inspect")
    i.add_argument("--artifact", required=True)
    i.add_argument("--json", action="store_true")
    d = sub.add_parser("decision-model-disable")
    d.add_argument("--reason", required=True)
    a = p.parse_args()
    if a.cmd == "decision-dataset-build":
        out = DecisionDatasetBuilder().build(a.sources, as_of=a.as_of, out_dir=a.out)
    elif a.cmd == "decision-model-train":
        out = train_model(a.dataset, a.out, a.config)
    elif a.cmd == "decision-model-evaluate":
        out = evaluate_model(a.dataset, a.artifact, a.report, a.as_of)
    elif a.cmd == "decision-model-replay":
        out = replay_quota(
            a.dataset, a.artifact, json.loads(Path(a.quota_policy).read_text())
        )
    elif a.cmd == "decision-model-inspect":
        out = load_artifact(a.artifact)
    else:
        out = {
            "model_status": "MODEL_DISABLED",
            "reason": a.reason,
            "scope": "decision-intelligence advisory only",
        }
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
