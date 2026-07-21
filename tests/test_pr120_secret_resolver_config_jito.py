from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.config.doctor import run_config_doctor
from src.config.runtime import (
    ConfigurationLoadError,
    JitoAuthMode,
    SecretReference,
    load_runtime_config,
)
from src.config.secret_resolver import SecretResolutionError


def _write(path: Path, text: str, *, mode: int | None = None) -> Path:
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        os.chmod(path, mode)
    return path


def test_secret_resolver_handles_env_and_restrictive_file_without_repr_leak(
    tmp_path: Path,
) -> None:
    secret_file = _write(tmp_path / "jupiter.secret", "file-secret-value\n", mode=0o600)
    config_path = _write(
        tmp_path / "runtime.yaml",
        f"""
wallet:
  signer_reference: env:FLASHLOAN_SIGNER_SECRET
providers:
  jupiter:
    api_key_reference: file:{secret_file}
""",
    )
    config = load_runtime_config(config_path, environ={})

    signer = config.wallet.signer_reference
    jupiter = config.providers.jupiter.api_key_reference
    assert signer is not None
    assert jupiter is not None

    env_handle = signer.resolve(environ={"FLASHLOAN_SIGNER_SECRET": "env-secret-value"})
    file_handle = jupiter.resolve(environ={})

    assert env_handle.reveal() == "env-secret-value"
    assert file_handle.reveal() == "file-secret-value"
    assert "env-secret-value" not in repr(env_handle)
    assert "file-secret-value" not in repr(file_handle)
    assert str(env_handle) == "<redacted secret>"


def test_file_secret_reference_rejects_symlink_multiline_and_loose_permissions(
    tmp_path: Path,
) -> None:
    loose = _write(tmp_path / "loose.secret", "secret\n", mode=0o644)
    with pytest.raises(SecretResolutionError, match="group/other"):
        reference = SecretReference.parse(f"file:{loose}")
        assert reference is not None
        reference.resolve(environ={})

    multiline = _write(tmp_path / "multiline.secret", "secret\nextra\n", mode=0o600)
    with pytest.raises(SecretResolutionError, match="exactly one line"):
        reference = SecretReference.parse(f"file:{multiline}")
        assert reference is not None
        reference.resolve(environ={})

    target = _write(tmp_path / "target.secret", "secret\n", mode=0o600)
    symlink = tmp_path / "linked.secret"
    symlink.symlink_to(target)
    with pytest.raises(SecretResolutionError, match="symlink"):
        reference = SecretReference.parse(f"file:{symlink}")
        assert reference is not None
        reference.resolve(environ={})


def test_keychain_reference_fails_explicitly_until_supported_adapter_exists() -> None:
    reference = SecretReference.parse("keychain:jupiter/api")
    assert reference is not None
    with pytest.raises(SecretResolutionError, match="not supported"):
        reference.resolve(environ={})


def test_config_fingerprint_distinguishes_secret_locator_without_displaying_it(
    tmp_path: Path,
) -> None:
    a = _write(
        tmp_path / "a.yaml",
        "wallet:\n  signer_reference: env:KEY_A\n",
    )
    b = _write(
        tmp_path / "b.yaml",
        "wallet:\n  signer_reference: env:KEY_B\n",
    )
    config_a = load_runtime_config(a, environ={})
    config_b = load_runtime_config(b, environ={})

    assert config_a.redacted_dict() == config_b.redacted_dict()
    assert config_a.fingerprint() != config_b.fingerprint()
    assert "KEY_A" not in str(config_a.redacted_dict())
    assert "KEY_B" not in str(config_b.redacted_dict())


def test_jito_enabled_defaults_to_auth_mode_none_without_uuid(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "jito-none.yaml",
        "providers:\n  jito:\n    enabled: true\n    auth_mode: none\n",
    )
    config = load_runtime_config(path, environ={})

    assert config.providers.jito.enabled is True
    assert config.providers.jito.auth_mode is JitoAuthMode.NONE
    assert config.providers.jito.auth_reference is None

    report = run_config_doctor(config, check_secrets=True, environ={})
    assert report.ok is True
    assert any(item.code == "JITO_AUTH_MODE_NONE" for item in report.diagnostics)


def test_jito_uuid_mode_requires_reference_and_uuid_shape(tmp_path: Path) -> None:
    missing_ref = _write(
        tmp_path / "missing-ref.yaml",
        "providers:\n  jito:\n    enabled: true\n    auth_mode: uuid\n",
    )
    with pytest.raises(ConfigurationLoadError, match="auth_mode=uuid"):
        load_runtime_config(missing_ref, environ={})

    wrong_mode = _write(
        tmp_path / "wrong-mode.yaml",
        (
            "providers:\n  jito:\n    enabled: true\n"
            "    auth_reference: env:JITO_AUTH_UUID\n"
        ),
    )
    with pytest.raises(
        ConfigurationLoadError,
        match="auth_reference requires auth_mode=uuid",
    ):
        load_runtime_config(wrong_mode, environ={})

    uuid_ref = _write(
        tmp_path / "uuid-ref.yaml",
        (
            "providers:\n  jito:\n    enabled: true\n    auth_mode: uuid\n"
            "    auth_reference: env:JITO_AUTH_UUID\n"
        ),
    )
    config = load_runtime_config(uuid_ref, environ={})

    bad = run_config_doctor(
        config,
        check_secrets=True,
        environ={"JITO_AUTH_UUID": "not-a-uuid"},
    )
    assert bad.ok is False
    assert any(item.code == "JITO_AUTH_NOT_UUID" for item in bad.diagnostics)
