#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mpr_close_04_runtime import publish_backup, validate_backup


def _probe(work: Path) -> dict[str, object]:
    source = work / "source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "state.json").write_text('{"terminal":"paper_rejected"}\n', encoding="utf-8")
    publish_backup(source, work / "backup", "generation-0001")
    return validate_backup(work / "backup", "generation-0001")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify MPR-CLOSE-04 backup/restore protocol")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--work-dir")
    args = parser.parse_args(argv)
    if args.work_dir:
        report = _probe(Path(args.work_dir))
    else:
        with tempfile.TemporaryDirectory() as tmp:
            report = _probe(Path(tmp))
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"accepted={report['accepted']}")
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
