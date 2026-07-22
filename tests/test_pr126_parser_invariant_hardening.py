from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

import pytest

from src.security.parser_invariants import (
    ErrorCategory,
    ParserInvariantError,
    assert_no_parser_invariant_debt,
    parse_json_object_payload,
    require_invariant,
    scan_python_source_for_invariant_debt,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pr126_error_taxonomy_has_required_categories() -> None:
    assert {category.value for category in ErrorCategory} == {
        "provider-business-error",
        "transport-error",
        "schema-drift",
        "protocol-rejection",
        "programmer-invariant-violation",
        "security-violation",
    }


def test_pr126_require_invariant_is_not_optimized_away(tmp_path: Path) -> None:
    script = tmp_path / "optimized_validation.py"
    script.write_text(
        "\n".join(
            [
                "from src.security.parser_invariants import (",
                "    ErrorCategory,",
                "    ParserInvariantError,",
                "    require_invariant,",
                ")",
                "try:",
                "    assert False, 'python -O removes this assert'",
                "    require_invariant(",
                "        False,",
                "        'assertion-free validation still runs',",
                "        category=ErrorCategory.SCHEMA_DRIFT,",
                "        source='optimized-mode',",
                "    )",
                "except ParserInvariantError as exc:",
                "    print(exc.category.value)",
                "    print(str(exc))",
                "else:",
                "    raise SystemExit('validation was optimized away')",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(REPO_ROOT)
        if not existing_pythonpath
        else os.pathsep.join((str(REPO_ROOT), existing_pythonpath))
    )

    completed = subprocess.run(
        [sys.executable, "-O", str(script)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "schema-drift" in completed.stdout
    assert "assertion-free validation still runs" in completed.stdout


def test_pr126_json_object_parser_is_bounded_and_categorized() -> None:
    assert parse_json_object_payload('{"ok": true}', source="unit") == {"ok": True}

    cases: tuple[tuple[str | bytes, ErrorCategory], ...] = (
        ("", ErrorCategory.SCHEMA_DRIFT),
        ("[]", ErrorCategory.SCHEMA_DRIFT),
        ("42", ErrorCategory.SCHEMA_DRIFT),
        ("{", ErrorCategory.SCHEMA_DRIFT),
        (b"\xff", ErrorCategory.SCHEMA_DRIFT),
        ('{"api_key":"' + "A1" * 30, ErrorCategory.SCHEMA_DRIFT),
    )
    for payload, category in cases:
        with pytest.raises(ParserInvariantError) as exc_info:
            parse_json_object_payload(payload, source="fuzz-case", max_bytes=128)
        assert exc_info.value.category is category
        assert "A1" * 10 not in str(exc_info.value)

    with pytest.raises(ParserInvariantError) as exc_info:
        parse_json_object_payload('{"oversized": true}', source="budget", max_bytes=4)
    assert exc_info.value.category is ErrorCategory.SECURITY_VIOLATION


def test_pr126_scanner_catches_assert_and_unjustified_broad_exception() -> None:
    source = "\n".join(
        [
            "def parse(value):",
            "    assert value, 'assertions disappear under -O'",
            "    try:",
            "        return int(value)",
            "    except Exception:",
            "        return 0",
        ]
    )

    findings = scan_python_source_for_invariant_debt(source, path="parser.py")

    assert {finding.code for finding in findings} == {
        "PR126-ASSERT",
        "PR126-BROAD-EXCEPT",
    }
    with pytest.raises(ParserInvariantError) as exc_info:
        assert_no_parser_invariant_debt(findings)
    assert exc_info.value.category is ErrorCategory.PROGRAMMER_INVARIANT_VIOLATION


def test_pr126_scanner_allows_explicit_broad_exception_justification() -> None:
    source = "\n".join(
        [
            "def boundary():",
            "    try:",
            "        return 'safe shutdown boundary'",
            "    # pr126: allow-broad-except - top-level shutdown boundary",
            "    except Exception:",
            "        return 'redacted failure'",
        ]
    )

    assert scan_python_source_for_invariant_debt(source, path="boundary.py") == ()


def test_pr126_parser_invariant_module_has_no_assert_or_broad_except_debt() -> None:
    source = (REPO_ROOT / "src/security/parser_invariants.py").read_text(
        encoding="utf-8"
    )

    assert (
        scan_python_source_for_invariant_debt(
            source,
            path="src/security/parser_invariants.py",
        )
        == ()
    )


def test_pr126_require_invariant_raises_redacted_category() -> None:
    with pytest.raises(ParserInvariantError) as exc_info:
        require_invariant(
            False,
            "provider payload rejected",
            category=ErrorCategory.PROTOCOL_REJECTION,
            source="instruction-decoder",
        )

    assert exc_info.value.category is ErrorCategory.PROTOCOL_REJECTION
    assert str(exc_info.value) == "instruction-decoder: provider payload rejected"
