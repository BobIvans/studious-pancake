"""OCA-W4B tokenizer/retrieval benchmark over a pinned-SHA graph build.

Compares the W4B task_context pack (real tokenizer when configured, labelled
estimator otherwise) against a whole-repository read baseline on golden
questions. Deterministic given identical inputs; latency is informational.

Run from the repository root after building the graph:

    python benchmarks/intelligence/w4b_token_benchmark.py \
        --state-root artifacts/w4b --questions <golden_questions.jsonl> \
        --token-profile tiktoken:o200k_base --out w4b_receipt.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.intelligence.repo_graph.service import QueryBackend, resolve_repo_sha
from src.intelligence.repo_graph.tokenizers import resolve_tokenizer

CRITICAL_NEEDLES = ("10_000", "fee", "slippage", "decimals")


def whole_repo_baseline(repo_root: Path, adapter: Any) -> int:
    total = 0
    for path in repo_root.rglob("*"):
        if path.is_dir() or any(
            part in {".git", ".venv", "__pycache__", "artifacts"} for part in path.parts
        ):
            continue
        if path.suffix.lower() not in {
            ".py",
            ".md",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
        }:
            continue
        try:
            total += adapter.count(path.read_bytes()[:262_144])
        except OSError:
            continue
    return total


def run(
    state_root: str,
    repo_root: str,
    questions_path: Path,
    token_profile: str | None,
    budget_tokens: int,
) -> dict[str, Any]:
    adapter, meta = resolve_tokenizer(token_profile)
    repo = Path(repo_root).resolve()
    sha = resolve_repo_sha(str(repo), "HEAD")
    backend = QueryBackend(state_root, str(repo))
    questions = [
        json.loads(line)
        for line in questions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    hits = 0
    latencies: list[float] = []
    pack_tokens: list[int] = []
    missed: list[dict[str, Any]] = []
    critical_omissions = 0
    for question in questions:
        started = time.perf_counter()
        envelope = backend.task_context(
            question["task"], repo_sha=sha, budget_tokens=budget_tokens
        )
        latencies.append(time.perf_counter() - started)
        got = {ref["path"] for ref in envelope["included_refs"]} | {
            ref["path"] for ref in envelope["omitted_refs"]
        }
        required = question["required_refs"]
        ok = all(
            ref in got or any(g.startswith(ref.rstrip("/") + "/") for g in got)
            for ref in required
        )
        if ok:
            hits += 1
        else:
            missed.append({"id": question["id"], "required": sorted(required)})
        pack_tokens.append(envelope["token_estimate"])
        # Critical omission probe: financial needles in retrieved FULL targets.
        for path, content in envelope.get("_content", {}).items():
            if path.endswith("sizing.py") or path.endswith("non_monotonic_sizing.py"):
                for needle in CRITICAL_NEEDLES:
                    if needle in path or needle in json.dumps(question):
                        if needle not in content and needle not in path:
                            critical_omissions += 1
    latencies.sort()
    return {
        "schema": "studious.w4b.token-benchmark.v1",
        "repo_sha": sha,
        "tokenizer": meta["tokenizer"],
        "tokenizer_uncertainty": meta["tokenizer_uncertainty"],
        "budget_tokens": budget_tokens,
        "questions": len(questions),
        "recall": round(hits / len(questions), 4),
        "critical_omissions": critical_omissions,
        "misses": missed,
        "pack_tokens_median": statistics.median(pack_tokens) if pack_tokens else 0,
        "latency_p50_s": round(statistics.median(latencies), 3) if latencies else 0,
        "latency_p95_s": (
            round(latencies[int(len(latencies) * 0.95) - 1], 3) if latencies else 0
        ),
        "determinism_note": "run twice and compare recall + pack sizes (receipt field)",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", default="artifacts/w4b")
    parser.add_argument("--repo", default=".")
    parser.add_argument(
        "--questions",
        default=r"C:\Users\ivans\Downloads\studious-pancake-main (IDE)\sp-worktrees\oca-w0a\benchmarks\intelligence\golden_questions.jsonl",
    )
    parser.add_argument("--token-profile", default=None)
    parser.add_argument("--budget-tokens", type=int, default=2000)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = run(
        args.state_root,
        args.repo,
        Path(args.questions),
        args.token_profile,
        args.budget_tokens,
    )
    adapter, _ = resolve_tokenizer(args.token_profile)
    report["whole_repo_baseline_tokens"] = whole_repo_baseline(Path(args.repo), adapter)
    Path(args.out).write_text(
        json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({k: v for k, v in report.items() if k != "misses"}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
