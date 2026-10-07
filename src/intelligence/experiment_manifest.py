"""Sealed identity using the existing research experiment owner."""

from dataclasses import asdict
import re
from src.research.evidence import ResearchExperimentManifest
from src.research.common import require_sha256
from .common import seal, verify_seal


def seal_experiment(
    manifest: ResearchExperimentManifest,
    *,
    repo_sha: str,
    config_sha: str,
    policy_sha: str,
) -> dict:
    if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", repo_sha):
        raise ValueError("exact repo SHA required")
    require_sha256(config_sha, "config_sha")
    require_sha256(policy_sha, "policy_sha")
    return seal(
        {
            "schema": "studious.experiment-identity.v2",
            "experiment": asdict(manifest),
            "experiment_sha256": manifest.manifest_sha256,
            "repo_sha": repo_sha,
            "config_sha": config_sha,
            "policy_sha": policy_sha,
        }
    )


def verify_experiment_identity(receipt: dict) -> ResearchExperimentManifest:
    verify_seal(receipt)
    manifest = ResearchExperimentManifest(
        **{
            **receipt["experiment"],
            "source_ids": tuple(receipt["experiment"]["source_ids"]),
        }
    )
    if (
        seal_experiment(
            manifest,
            repo_sha=receipt["repo_sha"],
            config_sha=receipt["config_sha"],
            policy_sha=receipt["policy_sha"],
        )
        != receipt
    ):
        raise ValueError("experiment identity mismatch")
    return manifest


def compare_experiment_identity(before: dict, after: dict) -> dict:
    verify_experiment_identity(before)
    verify_experiment_identity(after)
    return {
        "same": before == after,
        "changed": [key for key in sorted(before) if before[key] != after[key]],
    }
