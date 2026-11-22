"""Read-only repo-intel CLI: build / card / task-context / expand-context / verify.

Build writes local derived artifacts under the state root; query commands are
strictly read-only. No signing, sending, provider-enablement, or network model
access is possible from this surface (analyst profile, contract 1.10).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .graph_build import build_graph
from .service import QueryBackend, resolve_repo_sha
from .store import dangling_edge_count, load_manifest, artifact_path


def _emit(payload: dict[str, Any]) -> None:
    rendered = payload.get("_content")
    printable = {key: value for key, value in payload.items() if key != "_content"}
    print(json.dumps(printable, sort_keys=True, indent=1))
    if rendered:
        for path, content in sorted(rendered.items()):
            print(f"\n===== {path} =====")
            print(content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument(
        "--state-root",
        default=str(Path("artifacts") / "intelligence"),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build the deterministic graph artifact")
    build.add_argument("--ref", default="HEAD")

    card = sub.add_parser("card", help="print the T0 repo card (SHA-bound)")
    card.add_argument("--sha", default=None)
    card.add_argument("--ref", default="HEAD")

    task = sub.add_parser("task-context", help="bounded task context pack")
    task.add_argument("text")
    task.add_argument("--sha", default=None)
    task.add_argument("--ref", default="HEAD")
    task.add_argument("--budget-tokens", type=int, default=2000)

    expand = sub.add_parser("expand-context", help="exact refs by stable ID")
    expand.add_argument("refs", nargs="+")
    expand.add_argument("--sha", default=None)
    expand.add_argument("--ref", default="HEAD")
    expand.add_argument("--depth", default="full")

    verify = sub.add_parser("verify", help="artifact integrity + dangling edges")
    verify.add_argument("--sha", default=None)
    verify.add_argument("--ref", default="HEAD")

    args = parser.parse_args(argv)
    repo = str(Path(args.repo).resolve())

    if args.command == "build":
        receipt = build_graph(repo, args.state_root, ref=args.ref)
        print(json.dumps(receipt, sort_keys=True, indent=1))
        return 0

    sha = args.sha or resolve_repo_sha(repo, args.ref)
    backend = QueryBackend(args.state_root, repo)
    if args.command == "card":
        _emit(backend.repo_card(sha))
        return 0
    if args.command == "task-context":
        _emit(
            backend.task_context(
                args.text, repo_sha=sha, budget_tokens=args.budget_tokens
            )
        )
        return 0
    if args.command == "expand-context":
        _emit(backend.expand_context(args.refs, repo_sha=sha, depth=args.depth))
        return 0
    if args.command == "verify":
        manifest = load_manifest(args.state_root, sha)
        target = artifact_path(args.state_root, sha)
        dangling = dangling_edge_count(str(target))
        print(
            json.dumps(
                {
                    "repo_sha": manifest["repo_sha"],
                    "generation": manifest["generation"],
                    "canonical_checksum": manifest["canonical_checksum"],
                    "counts": manifest["counts"],
                    "dangling_edges": dangling,
                    "ok": dangling == 0,
                },
                sort_keys=True,
                indent=1,
            )
        )
        return 0 if dangling == 0 else 1
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
