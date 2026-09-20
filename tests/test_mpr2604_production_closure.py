from __future__ import annotations

import pytest

from scripts.production_debt_audit import _apply_qualification_overlay
from src.runtime import runtime_entrypoint


def _blocked_payload() -> dict:
    return {
        "production_ready": False,
        "paper_ready": False,
        "live_ready": False,
        "consistency_errors": [],
        "observed": {
            "product_state": "not-production-ready",
            "live_mode_available": False,
        },
        "batches": [],
        "blockers": [
            {
                "id": "runtime.product-state",
                "blocks_paper": True,
                "blocks_live": True,
            },
            {
                "id": "deployment.image-provenance",
                "blocks_paper": True,
                "blocks_live": True,
            },
        ],
    }


def test_untrusted_qualification_cannot_remove_blockers_or_promote_readiness() -> None:
    qualification = {
        "schema_version": "mpr-close-06.release-qualification.v1",
        "release_id": "attacker-controlled-release",
        "qualified": True,
        "promotion_state": "production-ready",
        "product_state": "production-ready",
        "live_mode_available": True,
        "missing_artifacts": [],
        "debt_resolution": {
            "runtime.product-state": {"resolved": True},
            "deployment.image-provenance": {"resolved": True},
        },
    }

    result = _apply_qualification_overlay(_blocked_payload(), qualification)

    assert [item["id"] for item in result["blockers"]] == [
        "runtime.product-state",
        "deployment.image-provenance",
    ]
    assert result["production_ready"] is False
    assert result["paper_ready"] is False
    assert result["live_ready"] is False
    assert result["resolved_by_release_qualification"] == []
    assert result["claimed_resolved_by_release_qualification"] == [
        "deployment.image-provenance",
        "runtime.product-state",
    ]
    assert result["qualification"]["authoritative"] is False
    assert result["observed"]["qualification_authoritative"] is False


def test_json_and_db_path_do_not_imply_one_cycle() -> None:
    parsed = runtime_entrypoint._parser().parse_args(
        [
            "run",
            "--mode",
            "paper",
            "--json",
            "--db-path",
            "/tmp/paper.sqlite3",
        ]
    )

    assert parsed.as_json is True
    assert parsed.db_path == "/tmp/paper.sqlite3"
    assert parsed.once is False
    assert parsed.max_cycles is None


def test_paper_lifecycle_has_explicit_once_and_max_cycles_controls() -> None:
    once = runtime_entrypoint._parser().parse_args(
        ["run", "--mode", "paper", "--once"]
    )
    bounded = runtime_entrypoint._parser().parse_args(
        ["run", "--mode", "paper", "--max-cycles", "7"]
    )

    assert once.once is True
    assert once.max_cycles is None
    assert bounded.once is False
    assert bounded.max_cycles == 7


def test_once_and_max_cycles_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        runtime_entrypoint._parser().parse_args(
            ["run", "--mode", "paper", "--once", "--max-cycles", "2"]
        )


def test_negative_max_cycles_fails_closed() -> None:
    with pytest.raises(Exception, match="--max-cycles must be non-negative"):
        runtime_entrypoint._resolve_max_cycles({}, once=False, max_cycles=-1)


def test_zero_max_cycles_preserves_continuous_mode() -> None:
    assert runtime_entrypoint._resolve_max_cycles({}, once=False, max_cycles=0) == 0
    assert runtime_entrypoint._resolve_max_cycles({}, once=True, max_cycles=None) == 1
