"""Offline golden-question retrieval benchmark (OCA-W0A).

LLM-free, network-free, deterministic ranking baseline. Measures how much of
each golden question's required reference set a bounded lexical retrieval pack
contains, versus the naive whole-repository reading baseline the pack replaces.

Token counts use a labelled byte estimate (utf-8 bytes / 4). No model
tokenizer, embeddings, or network access is used anywhere in this harness;
see LLM_FREE_DETERMINISTIC_INDEXING_CONTRACT_RU.md (PR #666 head 6214202b).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".txt",
    ".sql",
    ".sh",
}
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "artifacts"}
MAX_CONTENT_SCAN_BYTES = 262_144
STOPWORDS = {
    "which",
    "where",
    "what",
    "module",
    "file",
    "the",
    "a",
    "an",
    "is",
    "are",
    "owns",
    "own",
    "owner",
    "defined",
    "defines",
    "implemented",
    "contains",
    "covers",
    "test",
    "tests",
    "with",
    "for",
    "of",
    "and",
    "in",
    "to",
    "that",
}


def iter_tracked_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.name.startswith("baseline_report_"):
            # Never scan this harness's own output artifacts: they contain
            # environment-dependent latency values and would create a
            # nondeterministic feedback loop into the ranking input.
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.stat().st_size > MAX_CONTENT_SCAN_BYTES:
            continue
        files.append(path)
    return files


def task_tokens(task: str) -> list[str]:
    words = []
    for word in task.lower().split():
        cleaned = "".join(ch for ch in word if ch.isalnum())
        if len(cleaned) >= 4 and cleaned not in STOPWORDS:
            words.append(cleaned)
    return sorted(set(words))


def score_path(path: Path, root: Path, tokens: list[str]) -> int:
    score = 0
    lowered = path.as_posix().lower()
    name = path.name.lower()
    for token in tokens:
        if token in name:
            score += 8
        elif token in lowered:
            score += 4
    if score == 0 or not tokens:
        return score
    try:
        content = path.read_bytes()[:MAX_CONTENT_SCAN_BYTES]
    except OSError:
        return score
    for token in tokens:
        score += min(content.lower().count(token.encode()), 5)
    return score


def relative_path(ref: str, root: Path) -> Path:
    return (root / ref).resolve()


def evaluate(
    root: Path,
    questions: list[dict[str, Any]],
    budget_tokens: int,
) -> dict[str, Any]:
    files = iter_tracked_files(root)
    contents = {path: path.read_bytes() for path in files}
    repo_bytes = sum(len(data) for data in contents.values())
    missing_refs: list[str] = []
    resolved: dict[str, list[str]] = {}
    for question in questions:
        found = []
        for ref in question["required_refs"]:
            target = relative_path(ref, root)
            if target.is_dir():
                matches = [
                    path.as_posix()
                    for path in files
                    if target in path.parents or path == target
                ]
            elif target.is_file():
                matches = [target.relative_to(root).as_posix()]
            else:
                missing_refs.append(f"{question['id']}:{ref}")
                matches = []
            if matches:
                found.extend(matches)
        resolved[question["id"]] = sorted(set(found))
    results = []
    started = time.perf_counter()
    for question in questions:
        tokens = task_tokens(question["task"])
        scored = [(score_path(path, root, tokens), path) for path in files]
        scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: (-item[0], item[1].as_posix()))
        budget_bytes = budget_tokens * 4
        pack: list[str] = []
        expansion: list[str] = []
        pack_bytes = 0
        for _, path in scored:
            size = len(contents[path])
            relative = path.relative_to(root).as_posix()
            if size > budget_bytes or pack_bytes + size > budget_bytes:
                # Does not fit: returned as an exact omitted/expansion ref
                # (BUDGET_LIMITED), never silently dropped or mid-truncated.
                if len(expansion) < 10:
                    expansion.append(relative)
                continue
            pack.append(relative)
            pack_bytes += size
        required = resolved[question["id"]]
        hits = [ref for ref in required if ref in pack or ref in expansion]
        recall = len(hits) / len(required) if required else 0.0
        results.append(
            {
                "id": question["id"],
                "required_refs": sorted(required),
                "pack_refs": pack,
                "expansion_refs": expansion,
                "budget_limited": bool(expansion),
                "recall": round(recall, 4),
                "missed_required_refs": sorted(set(required) - set(hits)),
            }
        )
    elapsed = time.perf_counter() - started
    mean_recall = (
        round(sum(item["recall"] for item in results) / len(results), 4)
        if results
        else 0.0
    )
    return {
        "schema": "studious.intelligence.benchmark-report.v1",
        "repo_root": root.name,
        "tokenizer": "byte-estimate-v1 (utf-8 bytes / 4; no model tokenizer installed)",
        "budget_tokens": budget_tokens,
        "budget_bytes": budget_tokens * 4,
        "questions": len(questions),
        "files_scored": len(files),
        "repo_bytes": repo_bytes,
        "tokens_before_whole_repo": repo_bytes // 4,
        "tokens_after_budget_cap": budget_tokens,
        "mean_recall": mean_recall,
        "latency_seconds": round(elapsed, 3),
        "latency_note": "environment-dependent; informational only",
        "unresolved_required_refs": sorted(set(missing_refs)),
        "results": results,
    }


def load_questions(path: Path) -> list[dict[str, Any]]:
    questions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            questions.append(json.loads(line))
    questions.sort(key=lambda item: item["id"])
    return questions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument(
        "--questions",
        type=Path,
        default=Path(__file__).with_name("golden_questions.jsonl"),
    )
    parser.add_argument("--budget-tokens", type=int, default=2000)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    root = args.repo.resolve()
    questions = load_questions(args.questions)
    report = evaluate(root, questions, args.budget_tokens)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
