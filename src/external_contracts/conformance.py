"""Opt-in, read-only external API conformance checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import hashlib
import hmac
import json
import os
from time import time
from typing import Any, Callable, Mapping
from urllib import request
from urllib.parse import urlparse

from src.external_contracts.models import (
    ConformanceProbe,
    CredentialMode,
    ExternalContract,
)


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
    with request.urlopen(  # nosec B310 - model enforces HTTPS
        req, timeout=10
    ) as response:
        return int(response.status), response.read()


def _json_path_present(payload: Any, path: str) -> bool:
    current = payload
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return False
    return True


def _declared_required_env(probe: ConformanceProbe) -> tuple[str, ...]:
    if probe.required_env:
        return probe.required_env
    if probe.credential_env:
        return (probe.credential_env,)
    return ()


def _okx_signature(url: str, secret: str, timestamp: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    if parsed.query:
        path = f"{path}?{parsed.query}"
    message = f"{timestamp}GET{path}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _headers_for_probe(
    probe: ConformanceProbe, active_env: Mapping[str, str]
) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    headers = {"accept": "application/json", "user-agent": "flashloan-contracts/pr054"}
    required_env = _declared_required_env(probe)
    missing_env = tuple(name for name in required_env if not active_env.get(name))
    if missing_env:
        return headers, (), missing_env

    secrets = tuple(
        active_env[name]
        for name in set(required_env + probe.optional_env)
        if active_env.get(name)
    )

    if probe.credential_mode in {
        CredentialMode.HEADER_API_KEY,
        CredentialMode.WHITELIST_API_KEY,
    }:
        env_name = probe.credential_header_env or (
            required_env[0] if required_env else ""
        )
        header_name = probe.credential_header_name or "x-api-key"
        if env_name:
            headers[header_name] = active_env[env_name]

    elif probe.credential_mode is CredentialMode.BEARER_TOKEN:
        env_name = probe.credential_header_env or (
            required_env[0] if required_env else ""
        )
        if env_name:
            headers[probe.credential_header_name or "authorization"] = (
                f"Bearer {active_env[env_name]}"
            )

    elif probe.credential_mode is CredentialMode.OPTIONAL_UUID:
        uuid_value = next(
            (active_env[name] for name in probe.optional_env if active_env.get(name)),
            None,
        )
        if uuid_value:
            headers["x-jito-auth"] = uuid_value

    elif probe.credential_mode is CredentialMode.OKX_SIGNED:
        timestamp = str(time())
        headers.update(
            {
                "OK-ACCESS-KEY": active_env["OKX_API_KEY"],
                "OK-ACCESS-PASSPHRASE": active_env["OKX_API_PASSPHRASE"],
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-SIGN": _okx_signature(
                    probe.url, active_env["OKX_SECRET_KEY"], timestamp
                ),
            }
        )
        project_id = active_env.get("OKX_PROJECT_ID")
        if project_id:
            headers["OK-ACCESS-PROJECT"] = project_id

    return headers, secrets, ()


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
    headers, secrets, missing_env = _headers_for_probe(probe, active_env)
    if missing_env:
        return ConformanceResult(
            contract.id,
            "skipped-missing-env",
            False,
            None,
            (),
            "missing credential environment variable(s): " + ", ".join(missing_env),
        )

    try:
        status, body = (transport or _http_get)(probe.url, headers)
        assertions = [
            f"credential-mode:{probe.credential_mode.value}",
            f"status-code:{'ok' if status == probe.expected_status else 'failed'}",
        ]
        if probe.required_json_paths:
            payload = json.loads(body.decode("utf-8"))
            for path in probe.required_json_paths:
                present = _json_path_present(payload, path)
                assertions.append(f"json-path:{path}:{'ok' if present else 'failed'}")
        verified = all(
            item.startswith("credential-mode:") or item.endswith(":ok")
            for item in assertions
        )
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
