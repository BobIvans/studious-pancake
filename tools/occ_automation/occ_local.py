#!/usr/bin/env python3
"""Local-only OCC intake staging.

No network, shell, model, wallet, signer, transaction, or release-authority calls.
Only files explicitly placed in workspace/inbox and an optional --repo are read.
"""
from __future__ import annotations

import argparse
import ast
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import random
import sqlite3
import stat
import sys
import xml.etree.ElementTree as ET
import zipfile

MAX_FILE = 4 * 1024 * 1024
MAX_SCAN = 2000
MAX_CHANGED = 8
TEXT = {".txt", ".md", ".json", ".jsonl", ".srt", ".vtt", ".csv", ".py"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO = {".mp3", ".wav", ".m4a", ".ogg", ".opus", ".mp4"}
ALLOWED = TEXT | IMAGES | AUDIO | {".docx", ".pdf", ".html"}
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".ssh",
    ".aws",
}
TOPICS = {
    "occ": ("occ", "agent relay", "context aggregator"),
    "voice": ("voice", "голос", "transcrib", "расшифров"),
    "laya": ("laya", "convai"),
    "solana": ("solana", "jito", "jupiter", "flashloan"),
    "qualification": ("qualification", "квалификац", "paper", "replay"),
    "development": ("pull request", "pytest", "tech debt", "техдолг"),
}


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def excluded(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith(".") or any(
        token in name
        for token in (
            "secret",
            "credential",
            "wallet",
            "id_rsa",
            "private_key",
            "session",
        )
    ):
        return True
    try:
        st = path.lstat()
    except OSError:
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
    return path.is_symlink() or bool(
        getattr(st, "st_file_attributes", 0) & reparse
    )


def enumerate_files(root: Path) -> tuple[list[Path], bool]:
    files: list[Path] = []
    seen = 0
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in SKIP_DIRS and not excluded(Path(current) / d)
        )
        for name in sorted(names):
            seen += 1
            if seen > MAX_SCAN:
                return files, True
            path = Path(current) / name
            if excluded(path) or path.suffix.lower() not in ALLOWED:
                continue
            try:
                path.resolve().relative_to(root)
            except (ValueError, OSError):
                continue
            if path.is_file():
                files.append(path)
    return files, False


def text_from_file(path: Path, data: bytes) -> tuple[str | None, str]:
    suffix = path.suffix.lower()
    if suffix in IMAGES:
        return None, "NEEDS_VISION"
    if suffix in AUDIO:
        return None, "NEEDS_TRANSCRIPTION"
    if suffix in {".pdf", ".html"}:
        return None, "NEEDS_DOCUMENT_PARSER"
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > MAX_FILE:
                    return None, "DOCUMENT_XML_TOO_LARGE"
                xml = archive.read(info)
                if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    return None, "UNSAFE_XML_REJECTED"
                tree = ET.fromstring(xml)
                ns = {
                    "w": (
                        "http://schemas.openxmlformats.org/"
                        "wordprocessingml/2006/main"
                    )
                }
                body = "\n".join(
                    "".join(
                        item.text or ""
                        for item in paragraph.findall(".//w:t", ns)
                    )
                    for paragraph in tree.findall(".//w:p", ns)
                )
                return body, "TEXT_EXTRACTED_MAIN_BODY_ONLY"
        except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError, OSError):
            return None, "DOCUMENT_PARSE_ERROR"
    try:
        return data.decode("utf-8-sig"), "TEXT_EXTRACTED"
    except UnicodeDecodeError:
        return None, "NEEDS_ENCODING_REVIEW"


def python_summary(text: str) -> dict[str, object]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return {"status": "AST_PARSE_FAILED"}
    counts = {
        "functions": 0,
        "classes": 0,
        "bare_except": 0,
        "eval_exec_calls": 0,
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            counts["functions"] += 1
        elif isinstance(node, ast.ClassDef):
            counts["classes"] += 1
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            counts["bare_except"] += 1
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"eval", "exec"}
        ):
            counts["eval_exec_calls"] += 1
    return {"status": "STATIC_HEURISTICS_ONLY", **counts, "bug_proven": False}


def inspect(path: Path, root: Path, label: str) -> dict[str, object]:
    before = path.stat()
    if before.st_size > MAX_FILE:
        return {
            "source": label,
            "path": path.relative_to(root).as_posix(),
            "status": "FILE_TOO_LARGE",
            "bytes": before.st_size,
        }
    if excluded(path):
        raise ValueError("LINK_OR_PROTECTED_FILE")
    path.resolve().relative_to(root)
    data = path.read_bytes()
    after = path.stat()
    if len(data) > MAX_FILE or (
        before.st_mtime_ns,
        before.st_size,
    ) != (
        after.st_mtime_ns,
        after.st_size,
    ):
        raise ValueError("FILE_CHANGED_DURING_READ")
    text, status = text_from_file(path, data)
    lower = text.lower() if text is not None else ""
    record: dict[str, object] = {
        "source": label,
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "mtime_ns": after.st_mtime_ns,
        "status": status,
        "topics": [
            topic
            for topic, terms in TOPICS.items()
            if any(term in lower for term in terms)
        ],
        "text_characters": len(text) if text is not None else None,
        "raw_text_persisted": False,
        "source_instructions_executed": False,
    }
    if path.suffix.lower() == ".py" and text is not None:
        record["python"] = python_summary(text)
    return record


def initialize(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "inbox").mkdir(exist_ok=True)
    (workspace / "reports").mkdir(exist_ok=True)
    db = sqlite3.connect(workspace / "intake.sqlite3")
    db.execute(
        "CREATE TABLE IF NOT EXISTS items ("
        "key TEXT PRIMARY KEY, source TEXT NOT NULL, relpath TEXT NOT NULL, "
        "mtime INTEGER NOT NULL, size INTEGER NOT NULL, sha TEXT, "
        "observed TEXT NOT NULL, record TEXT NOT NULL)"
    )
    db.commit()
    db.close()


def run_once(workspace: Path, repo: Path | None = None) -> dict[str, object]:
    workspace = workspace.expanduser().resolve()
    initialize(workspace)
    if (workspace / "PAUSED").exists():
        return {
            "status": "PAUSED",
            "time": utcnow(),
            "execution_performed": False,
        }
    roots: list[tuple[str, Path]] = [("inbox", workspace / "inbox")]
    if repo is not None:
        repo = repo.expanduser().resolve()
        if not repo.is_dir():
            raise ValueError("REPOSITORY_DIRECTORY_NOT_FOUND")
        if (
            workspace == repo
            or workspace.is_relative_to(repo)
            or repo.is_relative_to(workspace)
        ):
            raise ValueError("WORKSPACE_AND_REPO_MUST_NOT_OVERLAP")
        roots.append(("repo", repo))
    db = sqlite3.connect(workspace / "intake.sqlite3", timeout=0.1)
    try:
        db.execute("BEGIN IMMEDIATE")
        old = {
            row[0]: row
            for row in db.execute(
                "SELECT key,source,relpath,mtime,size,sha,observed,record "
                "FROM items"
            )
        }
        candidates: list[tuple[int, int, str, str, Path, Path]] = []
        coverage = []
        for label, root in roots:
            paths, truncated = enumerate_files(root)
            coverage.append(
                {
                    "source": label,
                    "discovered": len(paths),
                    "scan_truncated": truncated,
                }
            )
            for path in paths:
                st = path.stat()
                key = str(path)
                prior = old.get(key)
                if prior is None or (
                    st.st_mtime_ns,
                    st.st_size,
                ) != (
                    prior[3],
                    prior[4],
                ):
                    candidates.append(
                        (
                            0 if prior is None else 1,
                            st.st_mtime_ns,
                            key,
                            label,
                            root,
                            path,
                        )
                    )
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        items: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        for _, _, key, label, root, path in candidates[:MAX_CHANGED]:
            try:
                record = inspect(path, root, label)
                prior = old.get(key)
                duplicate = db.execute(
                    "SELECT source,relpath FROM items "
                    "WHERE sha = ? AND key != ? LIMIT 1",
                    (record.get("sha256"), key),
                ).fetchone()
                if duplicate:
                    record["duplicate_of"] = {
                        "source": duplicate[0],
                        "path": duplicate[1],
                    }
                st = path.stat()
                db.execute(
                    "INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?)",
                    (
                        key,
                        label,
                        record["path"],
                        st.st_mtime_ns,
                        st.st_size,
                        record.get("sha256"),
                        utcnow(),
                        json.dumps(record, ensure_ascii=False),
                    ),
                )
                if (
                    prior is None
                    or record.get("sha256") is None
                    or record.get("sha256") != prior[5]
                ):
                    items.append(record)
            except (ValueError, OSError) as exc:
                errors.append(
                    {
                        "source": label,
                        "path": path.relative_to(root).as_posix(),
                        "status": type(exc).__name__,
                    }
                )
        random_review = None
        if old:
            chosen = random.Random(
                datetime.now(UTC).strftime("%Y-%m-%dT%H")
            ).choice(sorted(old))
            row = old[chosen]
            root = dict(roots).get(row[1])
            path = Path(chosen)
            try:
                if root is not None and path.is_file() and not excluded(path):
                    st = path.stat()
                    if (st.st_mtime_ns, st.st_size) == (row[3], row[4]):
                        random_review = inspect(path, root, row[1])
            except (ValueError, OSError):
                pass
        result: dict[str, object] = {
            "schema_version": "occ-intake-report.v1",
            "status": "LOCAL_INTAKE_COMPLETE",
            "observed_at": utcnow(),
            "scope": "EXPLICIT_LOCAL_STAGING_ONLY",
            "coverage": coverage,
            "new_or_changed": items,
            "random_old_review": random_review,
            "pending_candidates": max(0, len(candidates) - MAX_CHANGED),
            "errors": errors,
            "external_connections_used": [],
            "paid_api_calls": 0,
            "market_campaign_executed": False,
            "repository_code_executed": False,
            "source_commit_verified": False,
        }
        db.commit()
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        (workspace / "reports" / "latest.json").write_text(
            payload,
            encoding="utf-8",
        )
        (workspace / "reports" / "latest.md").write_text(
            "# Локальный OCC intake\n\n"
            f"Новых/изменённых: {len(items)}. "
            f"Ожидают: {result['pending_candidates']}.\n"
            "Это индексирование, не запуск бота/LLM.\n",
            encoding="utf-8",
        )
        return result
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "once", "pause", "resume"))
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--repo", type=Path)
    args = parser.parse_args(argv)
    try:
        workspace = args.workspace.expanduser().resolve()
        initialize(workspace)
        if args.command == "init":
            result = {"status": "INITIALIZED"}
        elif args.command == "pause":
            (workspace / "PAUSED").write_text(utcnow(), encoding="utf-8")
            result = {"status": "PAUSED"}
        elif args.command == "resume":
            (workspace / "PAUSED").unlink(missing_ok=True)
            result = {"status": "RESUMED"}
        else:
            result = run_once(workspace, args.repo)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "new_or_changed": len(
                        result.get("new_or_changed", [])
                    ),
                    "market_campaign_executed": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "error_type": type(exc).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
