import json
from pathlib import Path


def test_archive_scope_is_preserved_and_partial_execution_is_explicit():
    root = Path(__file__).resolve().parents[1]
    archive = root / "docs/web3-market-scale/design-input"
    assert len(tuple(path for path in archive.rglob("*") if path.is_file())) == 170
    matrix = json.loads(
        (root / "docs/web3-market-scale/execution_matrix.json").read_text()
    )
    assert matrix["archive_acceptance_count"] == 189
    assert len(matrix["archive_acceptance_cases"]) == 189
    assert matrix["complete_zip_implemented"] is False
    assert matrix["complete_zip_acceptance_passed"] is False
    assert {f"PM-{i:02}" for i in range(1, 17)} <= {
        row["id"] for row in matrix["packages"]
    }
    assert {f"WG-{i:02}" for i in range(1, 29)} <= {
        row["id"] for row in matrix["packages"]
    }
    for row in matrix["archive_acceptance_cases"]:
        for mapping in row["test_mapping"] or ():
            file, function = mapping.split("::")
            assert f"def {function}(" in (root / file).read_text()
