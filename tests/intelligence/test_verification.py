"""OCA-W18 tests: symbol-to-test mapping, always-run override, flaky registry."""

from __future__ import annotations

import sqlite3
import time

from src.intelligence.verification import (
    FlakyRegistry,
    select_tests,
    symbol_to_tests,
)

SCHEMA_SQL = """
CREATE TABLE nodes (symbol_id TEXT PRIMARY KEY, path TEXT, kind TEXT, name TEXT);
CREATE TABLE edges (relation TEXT, source TEXT, target TEXT, resolution TEXT, provenance TEXT);
INSERT INTO nodes VALUES ('s1', 'src/pkg/core.py', 'module', 'src.pkg.core');
INSERT INTO nodes VALUES ('s2', 'tests/test_core.py', 'module', 'tests.test_core');
INSERT INTO nodes VALUES ('s3', 'tests/test_core_extra.py', 'module', 'tests.test_core_extra');
INSERT INTO edges VALUES ('TESTED_BY', 's1', 's2', 'RESOLVED', 'STATIC_EXTRACTED');
INSERT INTO edges VALUES ('TEST_CANDIDATE', 's1', 's3', 'PROPOSED', 'PATTERN_MATCH');
"""


def test_symbol_to_tests_separates_evidence_from_proposed() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(SCHEMA_SQL)
    mapping = symbol_to_tests(connection, "src/pkg/core.py")
    assert mapping["tests_evidence_backed"] == ["tests/test_core.py"]
    assert mapping["tests_candidate_proposed"] == ["tests/test_core_extra.py"]
    assert mapping["coverage"] == "MAPPED"
    # Never conflated: proposed candidates cannot masquerade as evidence.
    assert mapping["provenance_rule"].startswith("TESTED_BY is structural")
    unmapped = symbol_to_tests(connection, "src/pkg/other.py")
    assert unmapped["coverage"] == "UNMAPPED"


def test_selection_with_always_run_override(tmp_path) -> None:
    flaky = FlakyRegistry(tmp_path / "flaky.json")
    future = time.time() + 3600
    flaky.quarantine("tests/test_flaky.py", owner="w18-lane", expires_at=future)
    selection = select_tests(
        mapped_tests=["tests/test_core.py", "tests/test_flaky.py"],
        always_run=["tests/test_flaky.py", "tests/test_critical.py"],
        flaky=flaky,
    )
    # Always-run overrides quarantine; mapped non-quarantined stay in.
    assert "tests/test_flaky.py" in selection["selected"]
    assert selection["skipped_quarantined"] == []
    assert "tests/test_critical.py" in selection["always_run_included"]
    assert "tests/test_core.py" in selection["selected"]
    assert selection["invariant"].startswith("selection never suppresses")


def test_quarantine_requires_future_expiry_and_auto_lifts(tmp_path) -> None:
    flaky = FlakyRegistry(tmp_path / "flaky.json")
    try:
        flaky.quarantine("t", owner="x", expires_at=time.time() - 10)
        raise AssertionError("past expiry must be rejected")
    except ValueError:
        pass
    short = time.time() + 2
    flaky.quarantine("tests/t.py", owner="x", expires_at=short)
    assert flaky.is_quarantined("tests/t.py", now=short - 1)
    assert not flaky.is_quarantined("tests/t.py", now=short + 1)
