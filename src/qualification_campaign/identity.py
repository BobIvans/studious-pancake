"""Exact repository/config generation binding shared with runtime and release."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def git_commit(root: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"], text=True
    ).strip()


@dataclass(frozen=True)
class CampaignManifest:
    repository_sha: str
    main_sha: str
    runtime_authority_sha256: str
    configuration_digests: tuple[tuple[str, str], ...]
    source_generations: tuple[tuple[str, str], ...]
    mode: str = "CAPTURE_ONLY"
    schema_version: str = "prequal.campaign-manifest.v1"

    def __post_init__(self) -> None:
        if (
            self.mode != "CAPTURE_ONLY"
            or self.schema_version != "prequal.campaign-manifest.v1"
        ):
            raise ValueError("campaign is read-only capture only")
        for sha in (self.repository_sha, self.main_sha):
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError("exact repository/main SHA required")
        for sha in (
            self.runtime_authority_sha256,
            *(d for _, d in self.configuration_digests),
            *(d for _, d in self.source_generations),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError("exact generation digest required")
        for field in ("configuration_digests", "source_generations"):
            pairs = tuple(sorted(getattr(self, field)))
            if (
                not pairs
                or any(not k for k, _ in pairs)
                or len({k for k, _ in pairs}) != len(pairs)
            ):
                raise ValueError(
                    "nonempty unique configuration/source generations required"
                )
            object.__setattr__(self, field, pairs)

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "safety": {
                "signer_reachable": False,
                "sender_reachable": False,
                "transaction_submission_allowed": False,
                "live_authorization": False,
            },
        }

    @property
    def campaign_id(self) -> str:
        return digest(self.to_dict())

    def require_same_generation(self, other: CampaignManifest) -> None:
        if self.campaign_id != other.campaign_id:
            raise ValueError("CAMPAIGN_GENERATION_MISMATCH")

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        main_sha: str,
        configuration: dict[str, object],
        sources: dict[str, object],
    ) -> CampaignManifest:
        from src.runtime_authority import (
            load_canonical_authority,
            evaluate_runtime_authority_map,
        )

        authority = load_canonical_authority(root)
        report = evaluate_runtime_authority_map(authority)
        if not report.accepted:
            raise ValueError("RUNTIME_AUTHORITY_INVALID:" + ",".join(report.blockers))
        # Dirty files cannot be represented by a commit identity.
        changed = subprocess.check_output(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain",
                "--untracked-files=normal",
            ],
            text=True,
        )
        if changed.strip():
            raise ValueError("CAMPAIGN_REQUIRES_CLEAN_CHECKOUT")
        subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", main_sha, "HEAD"],
            check=True,
        )
        return cls(
            git_commit(root),
            main_sha,
            digest(authority),
            tuple((k, digest(v)) for k, v in configuration.items()),
            tuple((k, digest(v)) for k, v in sources.items()),
        )


def manifest_from_dict(raw):
    """Restore exact identity including mandatory safety fields; never ignore them."""
    values = dict(raw)
    safety = values.pop("safety", None)
    if safety != {
        "signer_reachable": False,
        "sender_reachable": False,
        "transaction_submission_allowed": False,
        "live_authorization": False,
    }:
        raise ValueError("CAMPAIGN_SAFETY_BOUNDARY_INVALID")
    return CampaignManifest(**values)
