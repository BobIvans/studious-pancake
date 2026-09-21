from __future__ import annotations

import pytest

from src.config.runtime import ConfigurationLoadError, load_runtime_config
from src.runtime.runtime_entrypoint import (
    CORE_JUPITER_LEND_PROFILE_ID,
    CORE_V1_PROFILE_ENV,
    _select_core_v1_profile,
)
from src.runtime.core_v1_materializer import CORE_V1_PROFILE_ID


def _config():
    return load_runtime_config(cli_overrides={"runtime.mode": "paper"})


def test_installed_profile_selector_preserves_legacy_marginfi_default() -> None:
    profile = _select_core_v1_profile(_config(), {})
    assert profile.profile_id == CORE_V1_PROFILE_ID
    assert profile.lender == "marginfi"
    assert profile.profile_generation == 1
    assert profile.live_enabled is False


def test_installed_profile_selector_reaches_jupiter_lend_default_off() -> None:
    profile = _select_core_v1_profile(
        _config(),
        {CORE_V1_PROFILE_ENV: CORE_JUPITER_LEND_PROFILE_ID},
    )
    assert profile.profile_id == CORE_JUPITER_LEND_PROFILE_ID
    assert profile.lender == "jupiter-lend"
    assert profile.profile_generation == 1
    assert profile.live_enabled is False


def test_installed_profile_selector_rejects_unknown_profile() -> None:
    with pytest.raises(ConfigurationLoadError, match="unsupported profile"):
        _select_core_v1_profile(
            _config(),
            {CORE_V1_PROFILE_ENV: "unknown-profile"},
        )
