from __future__ import annotations

from scripts.production_debt_audit import _apply_qualification_overlay


def test_production_debt_audit_overlay_removes_only_evidence_resolved_blockers() -> None:
    payload = {
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
    qualification = {
        "schema_version": "mpr-close-06.release-qualification.v1",
        "release_id": "pytest-release",
        "qualified": False,
        "promotion_state": "blocked_pending_evidence",
        "product_state": "not-production-ready",
        "live_mode_available": False,
        "missing_artifacts": ["runtime_image_digest"],
        "debt_resolution": {
            "deployment.image-provenance": {"resolved": True},
            "runtime.product-state": {"resolved": False},
        },
    }

    overlaid = _apply_qualification_overlay(payload, qualification)

    assert [item["id"] for item in overlaid["blockers"]] == ["runtime.product-state"]
    assert overlaid["resolved_by_release_qualification"] == ["deployment.image-provenance"]
    assert overlaid["production_ready"] is False
    assert overlaid["qualification"]["release_id"] == "pytest-release"
