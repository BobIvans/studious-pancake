from __future__ import annotations

from pathlib import Path

import pytest

from src.config.activation import (
    ConfigActivationError,
    ConfigActivationStore,
    ConfigSourceEntry,
    ConfigSourceManifest,
    effective_config_diff,
)
from src.config.runtime import ConfigurationLoadError, load_runtime_config
from src.execution.live_control import canonical_policy_hash, load_policy
from src.execution.live_policy import LivePolicyError, LiveRiskPolicy


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_runtime_duplicate_merge_alias_and_non_string_keys_fail_closed(
    tmp_path: Path,
) -> None:
    samples = (
        "runtime:\n  mode: disabled\nruntime:\n  mode: paper\n",
        "base: &base\n  runtime: {mode: disabled}\ncopy: *base\n",
        "runtime:\n  <<: {mode: paper}\n",
        "1: value\n",
    )
    for index, text in enumerate(samples):
        with pytest.raises(ConfigurationLoadError):
            load_runtime_config(
                _write(tmp_path / f"unsafe-{index}.yaml", text),
                environ={},
            )


def test_live_policy_is_typed_and_rejects_unknown_fields(tmp_path: Path) -> None:
    policy = load_policy("config/live_risk.yaml")
    assert isinstance(policy, LiveRiskPolicy)

    unknown = (
        Path("config/live_risk.yaml").read_text(encoding="utf-8")
        + "unknown: true\n"
    )
    with pytest.raises(LivePolicyError, match="unknown"):
        load_policy(_write(tmp_path / "unknown.yaml", unknown))


def test_secret_locator_identity_is_preserved_without_exposing_value(
    tmp_path: Path,
) -> None:
    original = Path("config/live_risk.yaml").read_text(encoding="utf-8")
    policy_a = load_policy(
        _write(
            tmp_path / "a.yaml",
            original.replace(
                "env:SOLANA_SIGNER_REF",
                "file:/run/secrets/key-A",
            ),
        )
    )
    policy_b = load_policy(
        _write(
            tmp_path / "b.yaml",
            original.replace(
                "env:SOLANA_SIGNER_REF",
                "file:/run/secrets/key-B",
            ),
        )
    )

    assert canonical_policy_hash(policy_a) != canonical_policy_hash(policy_b)
    assert "key-A" not in str(policy_a.safe_display())
    assert policy_a.identity_payload()["wallet"]["signer_reference"][
        "locator"
    ].endswith("key-A")


def test_runtime_identity_is_domain_separated_and_display_is_redacted(
    tmp_path: Path,
) -> None:
    config_path = _write(
        tmp_path / "runtime.yaml",
        "wallet:\n  signer_reference: file:/run/secrets/signer-A\n",
    )
    config = load_runtime_config(config_path, environ={})
    assert "signer-A" not in str(config.safe_display())
    assert (
        config.identity_payload()["wallet"]["signer_reference"]
        == "file:/run/secrets/signer-A"
    )
    assert len(config.fingerprint()) == 64


def test_signed_activation_is_atomic_and_compare_and_swap_bound(
    tmp_path: Path,
) -> None:
    manifest = ConfigSourceManifest(
        sources=(
            ConfigSourceEntry(
                source_type="config-file",
                identity="/run/secrets/live-risk.yaml",
                value_path="$",
                content_hash="a" * 64,
                secret=False,
            ),
        )
    )
    store = ConfigActivationStore(
        tmp_path,
        signing_key=b"k" * 32,
        environment="mainnet-beta",
    )
    first = store.activate(
        reviewed_previous_generation=None,
        policy_hash="b" * 64,
        release_hash="c" * 64,
        source_manifest=manifest,
        approvals=("reviewer-1",),
        now=100,
        expires_at=200,
    )
    assert store.load_current(now=101) == first
    assert first.generation == 1

    with pytest.raises(ConfigActivationError, match="stale config approval"):
        store.activate(
            reviewed_previous_generation=None,
            policy_hash="d" * 64,
            release_hash="c" * 64,
            source_manifest=manifest,
            approvals=("reviewer-2",),
            now=102,
            expires_at=200,
        )


def test_effective_diff_marks_identity_and_financial_revalidation() -> None:
    diff = effective_config_diff(
        {"wallet": {"signer_reference": "file:/a"}, "reserve_lamports": 1},
        {"wallet": {"signer_reference": "file:/b"}, "reserve_lamports": 2},
        previous_identity="a" * 64,
        proposed_identity="b" * 64,
    )
    assert {change.impact for change in diff.changes} >= {
        "identity",
        "financial",
    }
    assert diff.restart_required is True
    assert diff.revalidation_required is True
