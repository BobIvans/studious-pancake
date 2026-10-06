import copy
import json
from pathlib import Path
import shutil

import pytest

from src.runtime_authority import (
    load_canonical_authority,
    evaluate_runtime_authority_map,
    RuntimeAuthorityError,
)
from src.qualification_campaign.identity import CampaignManifest, digest
from src.runtime.dispatch import parsed_command, requested_run_mode
from scripts.qualify_release import collect_release_artifacts

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_release_campaign_share_exact_authority():
    authority = load_canonical_authority(ROOT)
    report = evaluate_runtime_authority_map()
    _, artifacts = collect_release_artifacts(ROOT)
    sha = report.observed["runtime_authority_sha256"]
    campaign = CampaignManifest(
        "a" * 40, "b" * 40, sha, (("policy", "c" * 64),), (("rpc", "d" * 64),)
    )
    assert (
        sha
        == digest(authority)
        == artifacts["runtime_authority_map_digest"]["semantic_sha256"]
        == campaign.runtime_authority_sha256
    )


def test_generations_cannot_mix():
    a = CampaignManifest(
        "a" * 40, "b" * 40, "c" * 64, (("config", "d" * 64),), (("rpc", "e" * 64),)
    )
    raw = copy.deepcopy(a.to_dict())
    raw.pop("safety")
    raw["repository_sha"] = "f" * 40
    b = CampaignManifest(**raw)
    with pytest.raises(ValueError, match="GENERATION_MISMATCH"):
        a.require_same_generation(b)


@pytest.mark.parametrize("mutate", ["mirror", "generation"])
def test_mutation_fails_in_runtime_and_release(tmp_path, mutate):
    shutil.copytree(ROOT / "src/resources", tmp_path / "src/resources")
    (tmp_path / "config").mkdir()
    shutil.copy(
        ROOT / "config/runtime_authority.json",
        tmp_path / "config/runtime_authority.json",
    )
    target = tmp_path / (
        "config/runtime_authority.json"
        if mutate == "mirror"
        else "src/resources/capabilities.json"
    )
    target.write_text(
        target.read_text() + " "
        if mutate == "mirror"
        else target.read_text().replace('"flashloan-bot"', '"other"')
    )
    with pytest.raises(RuntimeAuthorityError):
        load_canonical_authority(tmp_path)
    _, artifacts = collect_release_artifacts(tmp_path)
    assert artifacts["runtime_authority_map_digest"]["status"] == "invalid"


@pytest.mark.parametrize(
    "argv, command",
    [
        (["--config-file", "run", "status"], "status"),
        (["status", "--value", "run"], "status"),
        (["config", "doctor", "--value", "run"], "config"),
        (["run", "--db-path", "run", "--mode=disabled"], "run"),
        (["--config-file=run", "run", "--mode", "paper"], "run"),
    ],
)
def test_parser_owns_subcommand(argv, command):
    assert parsed_command(argv) == command
    if command != "run":
        assert requested_run_mode(argv) is None


def test_development_queue_does_not_affect_canonical_digest():
    authority = load_canonical_authority()
    assert "open_pr_queue" not in authority
    assert "runtime_authority_map.json" not in authority["generation_bindings"]
