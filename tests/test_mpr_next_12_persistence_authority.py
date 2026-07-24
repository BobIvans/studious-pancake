from __future__ import annotations

from pathlib import Path

from src.persistence_authority_mpr_next_12 import (
    POLICY_SCHEMA,
    evaluate_persistence_authority,
    find_direct_connects,
    validate_policy,
)


def _policy() -> dict[str, object]:
    return {
        "schema_version": POLICY_SCHEMA,
        "approved_factories": ["src.persistence:open_runtime_db"],
        "allowed_direct_connects": [
            {
                "glob": "tests/**",
                "classification": "test-fixture",
                "reason": "temporary fixture database",
            }
        ],
        "quarantined_direct_connects": [
            {
                "glob": "src/legacy/**",
                "classification": "quarantined-legacy",
                "reason": "legacy storage is not runtime-admitted",
            }
        ],
        "blocked_direct_connects": [
            {
                "glob": "src/runtime/**",
                "classification": "active-runtime-split",
                "reason": "active runtime must use approved factory",
            }
        ],
    }


def test_mpr_next_12_policy_schema_is_valid() -> None:
    validated = validate_policy(_policy())

    assert validated["schema_version"] == POLICY_SCHEMA
    assert validated["approved_factories"] == ("src.persistence:open_runtime_db",)


def test_mpr_next_12_finds_sqlite_and_aiosqlite_connect_calls(tmp_path: Path) -> None:
    runtime = tmp_path / "src" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "store.py").write_text(
        "import sqlite3\nimport aiosqlite\n"
        "sqlite3.connect('runtime.db')\n"
        "async def open_db():\n    return await aiosqlite.connect('runtime.db')\n",
        encoding="utf-8",
    )

    occurrences = find_direct_connects(tmp_path)

    assert ("src/runtime/store.py", 3, "sqlite3.connect") in occurrences
    assert ("src/runtime/store.py", 5, "aiosqlite.connect") in occurrences


def test_mpr_next_12_blocks_active_runtime_direct_connects() -> None:
    report = evaluate_persistence_authority(
        policy=_policy(),
        occurrences=(("src/runtime/store.py", 10, "sqlite3.connect"),),
    )

    assert report.accepted is False
    assert report.unapproved_occurrences == 1
    assert report.blockers == (
        "UNAPPROVED_DIRECT_CONNECT:src/runtime/store.py:10:active-runtime-split",
    )


def test_mpr_next_12_allows_explicit_test_fixture_direct_connects() -> None:
    report = evaluate_persistence_authority(
        policy=_policy(),
        occurrences=(("tests/test_store.py", 8, "sqlite3.connect"),),
    )

    assert report.accepted is True
    assert report.total_occurrences == 1
    assert report.unapproved_occurrences == 0
    assert report.occurrences[0].classification == "test-fixture"


def test_mpr_next_12_quarantined_legacy_direct_connects_are_not_accepted() -> None:
    report = evaluate_persistence_authority(
        policy=_policy(),
        occurrences=(("src/legacy/arb.py", 4, "sqlite3.connect"),),
    )

    assert report.accepted is False
    assert report.occurrences[0].classification == "quarantined-legacy"
    assert report.blockers == (
        "UNAPPROVED_DIRECT_CONNECT:src/legacy/arb.py:4:quarantined-legacy",
    )
