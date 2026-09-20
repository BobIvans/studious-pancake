from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

INCONCLUSIVE = {
    "NOT_COVERED",
    "BASELINE_FAILED",
    "INVALID_MUTANT",
    "IMPORT_COLLECTION_ERROR",
    "SETUP_TEARDOWN_ERROR",
    "TIMEOUT",
    "INTERRUPTED",
    "SKIPPED",
    "XFAILED",
    "PENDING_REVIEW",
}


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    prefix = f"blob {len(data)}\0".encode()
    return hashlib.sha1(prefix + data).hexdigest()


def load_manifest(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    ids = [item["id"] for item in raw["mutants"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate mutant id")
    return raw


def _suite_counts(xml_path: Path) -> dict[str, int]:
    if not xml_path.exists():
        return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        return {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}
    return {
        key: sum(int(s.attrib.get(key, "0")) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def classify(exit_code: int, counts: dict[str, int], *, timed_out: bool = False) -> str:
    if timed_out:
        return "TIMEOUT"
    if counts["tests"] == 0:
        return "NOT_COVERED"
    if counts["errors"]:
        return "IMPORT_COLLECTION_ERROR"
    if counts["failures"]:
        return "KILLED_BY_ASSERTION"
    if counts["skipped"] >= counts["tests"]:
        return "SKIPPED"
    if exit_code == 0:
        return "SURVIVED_SELECTED_TESTS"
    return "PENDING_REVIEW"


def run_pytest(worktree: Path, tests: list[str], timeout: int, report: Path) -> dict:
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    for name in (
        "SOLANA_PRIVATE_KEY",
        "WALLET_PRIVATE_KEY",
        "WALLET_PATH",
        "JUPITER_API_KEY",
        "HELIUS_API_KEY",
        "OPENAI_API_KEY",
    ):
        env.pop(name, None)
    cmd = [sys.executable, "-m", "pytest", "-q", *tests, f"--junitxml={report}"]
    try:
        completed = subprocess.run(
            cmd,
            cwd=worktree,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        counts = _suite_counts(report)
        return {
            "command": cmd,
            "exit_code": completed.returncode,
            "counts": counts,
            "classification": classify(completed.returncode, counts),
            "output_tail": completed.stdout[-12000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": cmd,
            "exit_code": None,
            "counts": {"tests": 0, "failures": 0, "errors": 0, "skipped": 0},
            "classification": "TIMEOUT",
            "output_tail": (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else "",
        }


def apply_mutant(path: Path, anchor: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(anchor)
    if count != 1:
        raise ValueError(f"anchor count must be 1, got {count}")
    path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")


def verify_source(repo: Path, mutant: dict) -> dict[str, str]:
    path = repo / mutant["path"]
    if not path.is_file():
        raise ValueError(f"missing source: {mutant['path']}")
    git_sha = git_blob_sha1(path)
    expected_git = mutant["expected_git_blob_sha1"]
    if git_sha != expected_git:
        raise ValueError(
            f"source drift for {mutant['id']}: expected git blob {expected_git}, got {git_sha}"
        )
    return {"git_blob_sha1": git_sha, "sha256": sha256_path(path)}


def campaign(repo: Path, out: Path, manifest_path: Path) -> dict:
    manifest = load_manifest(manifest_path)
    out.mkdir(parents=True, exist_ok=False)
    original_hashes: dict[str, str] = {}
    for mutant in manifest["mutants"]:
        source = repo / mutant["path"]
        original_hashes.setdefault(mutant["path"], sha256_path(source))
        verify_source(repo, mutant)

    baseline_dir = out / "baseline"
    baseline_dir.mkdir()
    baseline = run_pytest(repo, manifest["existing_tests"], manifest["timeout_seconds"], baseline_dir / "junit.xml")
    if baseline["classification"] != "SURVIVED_SELECTED_TESTS":
        baseline["classification"] = "BASELINE_FAILED"
        result = {"schema": "mpr2606.campaign.v1", "baseline": baseline, "mutants": [], "complete": False}
        (out / "campaign.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        return result

    results = []
    for mutant in manifest["mutants"]:
        run_dir = out / mutant["id"]
        run_dir.mkdir()
        with tempfile.TemporaryDirectory(prefix="mpr2606-") as temp:
            clone = Path(temp) / "checkout"
            shutil.copytree(repo, clone, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
            source = clone / mutant["path"]
            try:
                verify_source(clone, mutant)
                apply_mutant(source, mutant["anchor"], mutant["replacement"])
            except ValueError as exc:
                results.append({**mutant, "classification": "INVALID_MUTANT", "error": str(exc)})
                continue
            run = run_pytest(clone, mutant["tests"], manifest["timeout_seconds"], run_dir / "junit.xml")
            results.append({
                "id": mutant["id"],
                "path": mutant["path"],
                "critical": mutant.get("critical", True),
                "witness": mutant["witness"],
                "original_sha256": sha256_path(repo / mutant["path"]),
                "mutated_sha256": sha256_path(source),
                **run,
            })

    after_hashes = {path: sha256_path(repo / path) for path in original_hashes}
    unchanged = after_hashes == original_hashes
    critical_survivors = [r["id"] for r in results if r.get("critical") and r["classification"] != "KILLED_BY_ASSERTION"]
    result = {
        "schema": "mpr2606.campaign.v1",
        "baseline": baseline,
        "mutants": results,
        "source_hashes_before": original_hashes,
        "source_hashes_after": after_hashes,
        "source_checkout_unchanged": unchanged,
        "critical_not_killed": critical_survivors,
        "complete": unchanged and not critical_survivors,
        "production_ready": False,
    }
    (out / "campaign.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="MPR-2606 developer-only mutation pilot")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("pilot_mutants.json"),
    )
    args = parser.parse_args()
    try:
        result = campaign(args.repo.resolve(), args.out.resolve(), args.manifest.resolve())
    except Exception as exc:
        print(f"MPR2606_INCOMPLETE: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"complete": result["complete"], "production_ready": False}, sort_keys=True))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
