from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.observability.health import (
    DependencyState,
    build_health_payload,
    build_metrics_text,
    build_readiness_payload,
    build_status_payload,
    check_http_health,
)

pytestmark = pytest.mark.unit


def _state(*, heartbeat_offset_ns: int = 0) -> dict[str, Any]:
    now = 1_700_000_000_000_000_000
    return {
        "schema_version": "pr042.container-runtime.v1",
        "pid": os.getpid(),
        "started_at_unix_ns": now - 1_000_000_000,
        "heartbeat_unix_ns": now + heartbeat_offset_ns,
        "mode": "disabled",
        "diagnostic": "SAFE_IDLE_NO_EXECUTION",
        "product_state": "not-production-ready",
        "capability_sha256": "abc123",
        "dependencies": [
            {
                "name": "runtime_contract",
                "kind": "runtime",
                "state": "ok",
                "critical": True,
                "reason": "capability contract valid",
                "updated_at_unix_ns": now,
                "labels": {},
            },
            {
                "name": "rpc",
                "kind": "provider",
                "state": "unavailable",
                "critical": True,
                "reason": "RPC stale or not configured",
                "updated_at_unix_ns": now,
                "labels": {"api_key": "should-not-leak"},
            },
        ],
    }


def test_health_is_liveness_while_readiness_blocks_critical_dependency() -> None:
    state = _state()
    health = build_health_payload(state, now_ns=state["heartbeat_unix_ns"])
    ready = build_readiness_payload(state, now_ns=state["heartbeat_unix_ns"])

    assert health["schema_version"] == "pr042.health.v1"
    assert health["ok"] is True
    assert ready["schema_version"] == "pr042.readiness.v1"
    assert ready["ok"] is False
    assert any("rpc:unavailable" in reason for reason in ready["reasons"])


def test_redacted_status_never_exposes_secret_dependency_labels() -> None:
    status = build_status_payload(_state(), now_ns=1_700_000_000_000_000_000)
    encoded = json.dumps(status, sort_keys=True)

    assert "should-not-leak" not in encoded
    assert "[REDACTED]" in encoded
    assert status["safety"] == {
        "live_enabled": False,
        "submitted": False,
        "signing_enabled": False,
        "material_redaction": "enabled",
    }


def test_metrics_surface_reports_health_readiness_and_dependency_state() -> None:
    metrics = build_metrics_text(_state(), now_ns=1_700_000_000_000_000_000)

    assert "flashloan_health_status 1" in metrics
    assert "flashloan_readiness_status 0" in metrics
    assert 'dependency="rpc"' in metrics
    assert 'state="unavailable"' in metrics


def test_health_rejects_stale_heartbeat() -> None:
    stale = _state(heartbeat_offset_ns=-30_000_000_000)
    health = build_health_payload(
        stale,
        now_ns=1_700_000_000_000_000_000,
        max_heartbeat_age_seconds=20.0,
    )

    assert health["ok"] is False
    assert health["dependencies"][0]["state"] == DependencyState.UNAVAILABLE.value


def test_http_probe_uses_endpoint_contract_without_real_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true, "status": "healthy"}'

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        assert url == "http://127.0.0.1:8080/health"
        assert timeout == 2.0
        return FakeResponse()

    monkeypatch.setattr("src.observability.health.request.urlopen", fake_urlopen)

    healthy, detail = check_http_health("http://127.0.0.1:8080/health")
    assert healthy is True
    assert "/health endpoint returned ok" in detail


def test_docker_healthcheck_points_to_real_health_endpoint() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "FLASHLOAN_HEALTH_URL=http://127.0.0.1:8080/health" in dockerfile
    assert (
        'CMD ["flashloan-bot-healthcheck", "--url", '
        '"http://127.0.0.1:8080/health"]'
    ) in dockerfile
