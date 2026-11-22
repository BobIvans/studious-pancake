"""Evidence-backed test selection and verification gates (OCA-W18).

Symbol-to-test mapping comes from repo-graph TESTED_BY / TEST_CANDIDATE edges
(derived read-only view). Selection can shrink a run but never permanently
removes critical tests: the always-run policy overrides quarantine, and
quarantine entries require an owner + expiry.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

SCHEMA = "studious.verification.selection.v1"


class FlakyRegistry:
    """Durable flaky-test registry with owner + expiry (no silent quarantine)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._entries: dict[str, dict[str, Any]] = {}
        if self._path.exists():
            self._entries = json.loads(self._path.read_text(encoding="utf-8"))

    def quarantine(
        self, test_id: str, *, owner: str, expires_at: float
    ) -> dict[str, Any]:
        if expires_at <= time.time():
            raise ValueError("quarantine expiry must be in the future")
        entry = {
            "owner": owner,
            "expires_at": expires_at,
            "schema": SCHEMA,
            "note": "selection may skip while quarantined; always-run overrides this",
        }
        self._entries[test_id] = entry
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._entries, sort_keys=True, indent=1) + "\n", encoding="utf-8"
        )
        return entry

    def is_quarantined(self, test_id: str, *, now: float | None = None) -> bool:
        entry = self._entries.get(test_id)
        if entry is None:
            return False
        if (now if now is not None else time.time()) >= entry["expires_at"]:
            del self._entries[test_id]
            self._path.write_text(
                json.dumps(self._entries, sort_keys=True, indent=1) + "\n",
                encoding="utf-8",
            )
            return False  # expired quarantine lifts automatically
        return True


def symbol_to_tests(
    connection: Any, target_path: str, *, include_candidates: bool = True
) -> dict[str, Any]:
    """Map one target path to its evidence-backed tests via graph edges.

    TESTED_BY = structural import evidence; TEST_CANDIDATE = naming/graph
    heuristic (PROPOSED provenance, reported separately, never conflated).
    """
    predicate = "TESTED_BY"
    if include_candidates:
        predicate = "('TESTED_BY', 'TEST_CANDIDATE')"
    rows = connection.execute(
        f"""
        SELECT DISTINCT n2.path, e.relation, n1.path
        FROM edges e
        JOIN nodes n1 ON n1.symbol_id = e.source
        JOIN nodes n2 ON n2.symbol_id = e.target
        WHERE n1.path = ? AND e.relation IN {predicate}
        ORDER BY n2.path
        """,
        (target_path,),
    ).fetchall()
    tested_by = sorted({row[0] for row in rows if row[1] == "TESTED_BY"})
    candidates = sorted({row[0] for row in rows if row[1] == "TEST_CANDIDATE"})
    return {
        "target": target_path,
        "tests_evidence_backed": tested_by,
        "tests_candidate_proposed": candidates,
        "coverage": (
            "MAPPED" if tested_by else ("PROPOSED_ONLY" if candidates else "UNMAPPED")
        ),
        "provenance_rule": "TESTED_BY is structural import evidence; TEST_CANDIDATE is PROPOSED and never conflated",
    }


def select_tests(
    *,
    mapped_tests: list[str],
    always_run: list[str],
    flaky: FlakyRegistry,
    now: float | None = None,
) -> dict[str, Any]:
    """Deterministic selection: affected tests minus live quarantines, plus
    every always-run critical test (selection never suppresses criticals)."""
    selected = sorted(set(mapped_tests) | set(always_run))
    skipped_quarantined = []
    runnable = []
    for test in selected:
        if test in always_run:
            runnable.append(test)  # always-run overrides quarantine
        elif flaky.is_quarantined(test, now=now):
            skipped_quarantined.append(test)
        else:
            runnable.append(test)
    return {
        "schema": SCHEMA,
        "selected": sorted(set(runnable)),
        "skipped_quarantined": sorted(set(skipped_quarantined)),
        "always_run_included": sorted(set(always_run)),
        "invariant": "selection never suppresses always-run critical tests",
    }
