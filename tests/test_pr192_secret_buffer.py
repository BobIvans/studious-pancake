from __future__ import annotations

import hashlib

import pytest

from src.config.credential_lifecycle import SecretHandle, SecretLifecycleError


def test_secret_handle_supports_scoped_readonly_bytes() -> None:
    handle = SecretHandle("secret-value", source_scheme="test", clock_ns=lambda: 1)

    with handle.borrow_bytes() as view:
        assert view.readonly is True
        assert view.tobytes() == b"secret-value"

    assert handle.lease.use_count == 1
    assert "secret-value" not in repr(handle)


def test_scoped_consumer_can_close_and_zeroize_after_use() -> None:
    handle = SecretHandle("secret-value", source_scheme="test", clock_ns=lambda: 1)

    digest = handle.use_bytes(
        lambda view: hashlib.sha256(view).hexdigest(), close_after=True
    )

    assert digest == hashlib.sha256(b"secret-value").hexdigest()
    assert handle.closed is True
    assert handle.lease.revoked is True
    with pytest.raises(SecretLifecycleError, match="expired, revoked, or exhausted"):
        handle.reveal()


def test_context_manager_revokes_on_exception() -> None:
    handle = SecretHandle("secret-value", source_scheme="test", clock_ns=lambda: 1)

    with pytest.raises(RuntimeError):
        with handle:
            raise RuntimeError("boom")

    assert handle.closed is True
