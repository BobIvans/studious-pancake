from __future__ import annotations

import pytest

from src.pr198_sender_free_artifact_gate import (
    InstalledArtifactEvidence,
    ImportEdge,
    PR198ArtifactGateState,
    evaluate_sender_free_artifact,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def clean_evidence() -> InstalledArtifactEvidence:
    return InstalledArtifactEvidence(
        wheel_sha256=DIGEST_A,
        image_sha256=DIGEST_B,
        entrypoints={
            "flashloan-bot": "src.cli_pr189:main",
            "flashloan-checks": "src.automation_cli_pr189:main",
        },
        installed_modules=(
            "src.cli_pr189",
            "src.automation_cli_pr189",
            "src.paper_shadow.runtime",
        ),
        reachable_modules=(
            "src.cli_pr189",
            "src.automation_cli_pr189",
            "src.paper_shadow.runtime",
        ),
        import_edges=(
            ImportEdge("src.cli_pr189", "src.paper_shadow.runtime"),
            ImportEdge("src.automation_cli_pr189", "src.cli_pr189"),
        ),
        capabilities={
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "sender_enabled": False,
            "signer_enabled": False,
            "jito_submission_enabled": False,
            "rpc_submission_enabled": False,
            "private_key_materialized": False,
        },
    )


def test_pr198_artifact_gate_accepts_sender_free_installed_surface() -> None:
    report = evaluate_sender_free_artifact(clean_evidence())

    assert report.ready is True
    assert report.state is PR198ArtifactGateState.READY_FOR_SENDER_FREE_RUNTIME
    assert report.violations == ()
    assert report.to_dict()["safety_boundary"] == {
        "live_execution_allowed": False,
        "signer_allowed": False,
        "sender_import_allowed": False,
    }


def test_pr198_artifact_gate_rejects_forbidden_installed_sender_module() -> None:
    evidence = clean_evidence()
    report = evaluate_sender_free_artifact(
        InstalledArtifactEvidence(
            wheel_sha256=evidence.wheel_sha256,
            image_sha256=evidence.image_sha256,
            entrypoints=evidence.entrypoints,
            installed_modules=(
                *evidence.installed_modules,
                "src.execution.senders.jito",
            ),
            reachable_modules=evidence.reachable_modules,
            import_edges=evidence.import_edges,
            capabilities=evidence.capabilities,
        )
    )

    assert report.ready is False
    assert report.violations[0].code == "forbidden_module_installed"
    assert report.violations[0].subject == "src.execution.senders.jito"


def test_pr198_artifact_gate_rejects_reachable_forbidden_import_edge() -> None:
    evidence = clean_evidence()
    report = evaluate_sender_free_artifact(
        InstalledArtifactEvidence(
            wheel_sha256=evidence.wheel_sha256,
            image_sha256=evidence.image_sha256,
            entrypoints=evidence.entrypoints,
            installed_modules=evidence.installed_modules,
            reachable_modules=evidence.reachable_modules,
            import_edges=(
                *evidence.import_edges,
                ImportEdge("src.paper_shadow.runtime", "src.signer.ipc"),
            ),
            capabilities=evidence.capabilities,
        )
    )

    assert report.ready is False
    assert report.violations[0].code == "forbidden_import_edge"
    assert report.violations[0].subject == "src.paper_shadow.runtime->src.signer.ipc"


def test_pr198_artifact_gate_rejects_live_or_signer_capabilities() -> None:
    evidence = clean_evidence()
    capabilities = dict(evidence.capabilities)
    capabilities["live_trading_enabled"] = True
    capabilities["private_key_materialized"] = True

    report = evaluate_sender_free_artifact(
        InstalledArtifactEvidence(
            wheel_sha256=evidence.wheel_sha256,
            image_sha256=evidence.image_sha256,
            entrypoints=evidence.entrypoints,
            installed_modules=evidence.installed_modules,
            reachable_modules=evidence.reachable_modules,
            import_edges=evidence.import_edges,
            capabilities=capabilities,
        )
    )

    assert report.ready is False
    assert [violation.code for violation in report.violations] == [
        "forbidden_capability_enabled",
        "forbidden_capability_enabled",
    ]
    assert {violation.subject for violation in report.violations} == {
        "live_trading_enabled",
        "private_key_materialized",
    }


def test_pr198_artifact_gate_requires_installed_not_source_tree_only() -> None:
    evidence = clean_evidence()

    with pytest.raises(ValueError, match="installed output"):
        InstalledArtifactEvidence(
            wheel_sha256=evidence.wheel_sha256,
            image_sha256=evidence.image_sha256,
            entrypoints=evidence.entrypoints,
            installed_modules=evidence.installed_modules,
            reachable_modules=evidence.reachable_modules,
            import_edges=evidence.import_edges,
            capabilities=evidence.capabilities,
            source_tree_only=True,
        )


def test_pr198_artifact_gate_requires_mandatory_entrypoints() -> None:
    evidence = clean_evidence()
    report = evaluate_sender_free_artifact(
        InstalledArtifactEvidence(
            wheel_sha256=evidence.wheel_sha256,
            image_sha256=evidence.image_sha256,
            entrypoints={"flashloan-bot": "src.cli_pr189:main"},
            installed_modules=evidence.installed_modules,
            reachable_modules=evidence.reachable_modules,
            import_edges=evidence.import_edges,
            capabilities=evidence.capabilities,
        )
    )

    assert report.ready is False
    assert report.violations[0].code == "missing_required_entrypoint"
    assert report.violations[0].subject == "flashloan-checks"


def test_pr198_artifact_gate_hash_is_deterministic_for_reordered_evidence() -> None:
    left = evaluate_sender_free_artifact(clean_evidence())
    right = evaluate_sender_free_artifact(
        InstalledArtifactEvidence(
            wheel_sha256=DIGEST_A,
            image_sha256=DIGEST_B,
            entrypoints={
                "flashloan-checks": "src.automation_cli_pr189:main",
                "flashloan-bot": "src.cli_pr189:main",
            },
            installed_modules=(
                "src.paper_shadow.runtime",
                "src.cli_pr189",
                "src.automation_cli_pr189",
            ),
            reachable_modules=(
                "src.paper_shadow.runtime",
                "src.automation_cli_pr189",
                "src.cli_pr189",
            ),
            import_edges=(
                ImportEdge("src.automation_cli_pr189", "src.cli_pr189"),
                ImportEdge("src.cli_pr189", "src.paper_shadow.runtime"),
            ),
            capabilities={
                "signer_enabled": False,
                "sender_enabled": False,
                "paper_trading_only": True,
                "live_trading_enabled": False,
                "jito_submission_enabled": False,
                "rpc_submission_enabled": False,
                "private_key_materialized": False,
            },
        )
    )

    assert left.evidence_hash == right.evidence_hash
