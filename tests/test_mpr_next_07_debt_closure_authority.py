from __future__ import annotations

import zipfile
from pathlib import Path

from src.readiness.debt_closure_map import (
    GATE_DEBT_MAP,
    SCHEMA_VERSION,
    closure_map_digest,
    compare_archives,
    evaluate_debt_closure_evidence,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def valid_payload(gate_id: str = "PR-225") -> dict[str, object]:
    mapping = GATE_DEBT_MAP[gate_id]
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "gate_id": gate_id,
        "evidence_kind": mapping.evidence_kind,
        "debt_ids": list(mapping.debt_ids),
        "gate_ok": True,
        "runtime_bound": True,
        "installed_artifact_bound": True,
        "evidence_fresh": True,
        "replayable": True,
        "ci_authoritative": True,
        "source_only": False,
        "synthetic": False,
        "artifact_sha256": HASH_A,
        "runtime_command_surface_sha256": HASH_B,
        "evidence_sha256": HASH_C,
        "freshness_proof_sha256": HASH_D,
    }
    if gate_id == "MPR-31":
        payload["upstream_mprs"] = [
            "MPR-25",
            "MPR-26",
            "MPR-27",
            "MPR-28",
            "MPR-29",
            "MPR-30",
        ]
    return payload


def test_pr225_can_resolve_only_its_stable_debt_ids() -> None:
    decision = evaluate_debt_closure_evidence(valid_payload("PR-225"))

    assert decision.ok
    assert decision.resolved_debt_ids == tuple(sorted(GATE_DEBT_MAP["PR-225"].debt_ids))
    assert decision.blocked_debt_ids == ()
    assert decision.to_dict()["production_ready"] is False
    assert len(decision.closure_digest) == 64


def test_isolated_gate_output_without_runtime_binding_cannot_close_debt() -> None:
    payload = valid_payload("PR-225")
    payload["runtime_bound"] = False

    decision = evaluate_debt_closure_evidence(payload)

    assert not decision.ok
    assert decision.resolved_debt_ids == ()
    assert set(decision.blocked_debt_ids) == set(GATE_DEBT_MAP["PR-225"].debt_ids)
    assert "DEBT_CLOSURE_RUNTIME_BINDING_REQUIRED" in {
        item.code for item in decision.violations
    }


def test_source_only_or_synthetic_evidence_is_never_closure_authority() -> None:
    payload = valid_payload("PR-226")
    payload["source_only"] = True
    payload["synthetic"] = True

    decision = evaluate_debt_closure_evidence(payload)

    assert not decision.ok
    codes = {item.code for item in decision.violations}
    assert "DEBT_CLOSURE_SOURCE_ONLY" in codes
    assert "DEBT_CLOSURE_SYNTHETIC_EVIDENCE" in codes
    assert decision.resolved_debt_ids == ()


def test_gate_cannot_claim_unmapped_debt_id() -> None:
    payload = valid_payload("PR-228")
    payload["debt_ids"] = [*GATE_DEBT_MAP["PR-228"].debt_ids, "runtime.product-state"]

    decision = evaluate_debt_closure_evidence(payload)

    assert not decision.ok
    assert "DEBT_CLOSURE_UNMAPPED_DEBT_ID" in {
        item.code for item in decision.violations
    }
    assert decision.resolved_debt_ids == ()


def test_mpr31_cannot_close_final_debt_without_mpr29_and_mpr30() -> None:
    payload = valid_payload("MPR-31")
    payload["upstream_mprs"] = ["MPR-25", "MPR-26", "MPR-27", "MPR-28"]

    decision = evaluate_debt_closure_evidence(payload)

    assert not decision.ok
    message = "\n".join(item.detail for item in decision.violations)
    assert "MPR-29" in message
    assert "MPR-30" in message
    assert "DEBT_CLOSURE_MPR31_UPSTREAMS_MISSING" in {
        item.code for item in decision.violations
    }


def test_closure_map_digest_is_stable_and_non_empty() -> None:
    assert len(closure_map_digest()) == 64
    assert {"PR-225", "PR-226", "PR-228", "MPR-31"} <= set(GATE_DEBT_MAP)


def _write_zip(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for filename, data in files.items():
            archive.writestr(filename, data)


def test_identical_archive_uploads_are_not_progress(tmp_path: Path) -> None:
    first = tmp_path / "repo22-3.zip"
    second = tmp_path / "repo22-4.zip"
    files = {"src/app.py": b"print('same')\n", "README.md": b"same\n"}
    _write_zip(first, files)
    _write_zip(second, files)

    report = compare_archives(first, second)

    assert report.identical is True
    assert report.has_changes is False
    assert report.added == ()
    assert report.removed == ()
    assert report.changed == ()


def test_archive_diff_reports_real_source_changes(tmp_path: Path) -> None:
    first = tmp_path / "before.zip"
    second = tmp_path / "after.zip"
    _write_zip(first, {"src/app.py": b"old\n", "README.md": b"same\n"})
    _write_zip(second, {"src/app.py": b"new\n", "docs/new.md": b"added\n"})

    report = compare_archives(first, second)

    assert report.identical is False
    assert report.has_changes is True
    assert report.added == ("docs/new.md",)
    assert report.removed == ("README.md",)
    assert report.changed == ("src/app.py",)
