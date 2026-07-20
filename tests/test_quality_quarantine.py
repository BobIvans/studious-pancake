"""Architecture checks for PR-024 quality debt quarantine."""

from __future__ import annotations

import ast
import configparser
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_f821_is_not_globally_ignored() -> None:
    parser = configparser.ConfigParser()
    parser.read(ROOT / ".flake8")
    ignored = parser["flake8"].get("extend-ignore", "")
    assert "F821" not in {item.strip() for item in ignored.split(",")}

    per_file = parser["flake8"].get("per-file-ignores", "")
    assert "src/legacy_arb_bot.py:F821" in per_file.replace(" ", "")


def test_quarantined_legacy_module_is_not_imported_by_active_python() -> None:
    payload = json.loads(
        (ROOT / "config/quality_quarantine.json").read_text(encoding="utf-8")
    )
    quarantined = {entry["path"] for entry in payload["entries"]}
    assert quarantined == {"src/legacy_arb_bot.py"}

    violations: list[str] = []
    for base in (ROOT / "src", ROOT / "scripts", ROOT / "tests"):
        for path in base.rglob("*.py"):
            relative = path.relative_to(ROOT).as_posix()
            if relative in quarantined:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name for alias in node.names}
                    if "src.legacy_arb_bot" in names:
                        violations.append(relative)
                elif isinstance(node, ast.ImportFrom):
                    if node.module == "src.legacy_arb_bot":
                        violations.append(relative)
    assert not violations, f"active modules import quarantine: {violations}"


def test_typecheck_quarantine_matches_mypy_sections() -> None:
    payload = json.loads(
        (ROOT / "config/typecheck_quarantine.json").read_text(encoding="utf-8")
    )
    config_text = (ROOT / "mypy.ini").read_text(encoding="utf-8")
    for entry in payload["entries"]:
        assert f"[mypy-{entry['module']}]" in config_text
        assert entry["owner_prs"]
