"""Opt-in, read-only external API conformance checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from typing import Any, Callable, Mapping
from urllib import request

from src.external_contracts.models import ExternalContract


@dataclass(frozen=True, slots=True)
class ConformanceResult:
    contract_id: str
    state: str
    verified: bool
    status_code: int | None
    assertions: tuple[str, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Transport = Callable[[str, Mapping[str, str]], tuple[int, bytes]]


def redact_text(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _http_get(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
    req = request.Request(url, headers=dict(headers), method="GET")
    with request.urlopen(req, timeout=10) as response:  # nosec B310 - model enforces HTTPS
        return int(response.status), response.read()


def _json_path_present(payload: Any, path: str) -> bool:
    current = payload
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return False
    return True


def run_read_only_conformance(
    contract: ExternalContract,
    *,
    enable_online: bool = False,
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> ConformanceResult:
    probe = contract.conformance_probe
    if not enable_online:
        return ConformanceResult(
            contract.id,
            "skipped-not-enabled",
            False,
            None,
            (),
        )
    if probe is None:
        return ConformanceResult(
            contract.id,
            "skipped-no-probe",
            False,
            None,
            (),
        )
    active_env = os.environ if environ is None else environ
    credential = None
    headers = {"accept": "application/json", "user-agent": "flashloan-contracts/pr027"}
    if probe.credential_env:
        credential = active_env.get(probe.credential_env)
        if not credential:
            return ConformanceResult(
                contract.id,
                "skipped-missing-env",
                False,
                None,
                (),
                f"missing credential environment variable {probe.credential_env}",
            )
        headers["authorization"] = f"Bearer {credential}"
    secrets = tuple(item for item in (credential,) if item)
    try:
        status, body = (transport or _http_get)(probe.url, headers)
        assertions = [
            f"status-code:{'ok' if status == probe.expected_status else 'failed'}"
        ]
        payload = json.loads(body.decode("utf-8"))
        for path in probe.required_json_paths:
            assertions.append(
                f"json-path:{path}:{'ok' if _json_path_present(payload, path) else 'failed'}"
            )
        verified = all(item.endswith(":ok") for item in assertions)
        return ConformanceResult(
            contract.id,
            "verified" if verified else "failed-assertion",
            verified,
            status,
            tuple(assertions),
        )
    except Exception as exc:
        return ConformanceResult(
            contract.id,
            "failed-request",
            False,
            None,
            (),
            redact_text(str(exc), secrets),
        )
