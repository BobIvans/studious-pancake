"""Opt-in, read-only external API conformance checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
from datetime import UTC, datetime
import hashlib
import hmac
import inspect
import json
import os
from typing import Any, Callable, Mapping, cast
from urllib import request
from urllib.parse import urlparse

from src.external_contracts.models import (
    ConformanceProbe,
    CredentialMode,
    ExternalContract,
    JsonPathAssertion,
    JsonValueType,
)


@dataclass(frozen=True, slots=True)
class ConformanceHttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class ConformanceResult:
    contract_id: str
    state: str
    verified: bool
    status_code: int | None
    assertions: tuple[str, ...]
    request_method: str | None = None
    request_url: str | None = None
    response_sha256: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


StructuredTransport = Callable[[ConformanceHttpRequest], tuple[int, bytes]]
LegacyTransport = Callable[[str, Mapping[str, str]], tuple[int, bytes]]
Transport = StructuredTransport | LegacyTransport
_MISSING = object()


def redact_text(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _http_request(probe_request: ConformanceHttpRequest) -> tuple[int, bytes]:
    req = request.Request(
        probe_request.url,
        data=probe_request.body,
        headers=dict(probe_request.headers),
        method=probe_request.method,
    )
    with request.urlopen(  # nosec B310 - model enforces HTTPS
        req, timeout=probe_request.timeout_seconds
    ) as response:
        return int(response.status), response.read()


def _invoke_transport(
    transport: Transport | None, probe_request: ConformanceHttpRequest
) -> tuple[int, bytes, bool]:
    if transport is None:
        status, body = _http_request(probe_request)
        return status, body, False
    try:
        parameters = inspect.signature(transport).parameters
    except (TypeError, ValueError):
        parameters = {}
    if len(parameters) >= 2:
        legacy = cast(LegacyTransport, transport)
        status, body = legacy(probe_request.url, probe_request.headers)
        return status, body, True
    structured = cast(StructuredTransport, transport)
    status, body = structured(probe_request)
    return status, body, False


def _json_path_value(payload: Any, path: str) -> Any:
    current = payload
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def _json_path_present(payload: Any, path: str) -> bool:
    return _json_path_value(payload, path) is not _MISSING


def _json_type_matches(value: Any, expected_type: JsonValueType) -> bool:
    if expected_type is JsonValueType.OBJECT:
        return isinstance(value, dict)
    if expected_type is JsonValueType.ARRAY:
        return isinstance(value, list)
    if expected_type is JsonValueType.STRING:
        return isinstance(value, str)
    if expected_type is JsonValueType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type is JsonValueType.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type is JsonValueType.BOOLEAN:
        return isinstance(value, bool)
    if expected_type is JsonValueType.NULL:
        return value is None
    return False


def _declared_required_env(probe: ConformanceProbe) -> tuple[str, ...]:
    if probe.required_env:
        return probe.required_env
    if probe.credential_env:
        return (probe.credential_env,)
    return ()


def _okx_signature(
    url: str, secret: str, timestamp: str, method: str, body: str
) -> str:
    parsed = urlparse(url)
    path = parsed.path
    if parsed.query:
        path = f"{path}?{parsed.query}"
    message = f"{timestamp}{method.upper()}{path}{body}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _utc_iso_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _headers_for_probe(
    probe: ConformanceProbe, active_env: Mapping[str, str], body_text: str
) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    headers = {
        "accept": "application/json",
        "user-agent": "flashloan-contracts/pr070",
    }
    if probe.json_body is not None:
        headers["content-type"] = "application/json"
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
        method = probe.method.value
        timestamp = _utc_iso_timestamp()
        headers.update(
            {
                "OK-ACCESS-KEY": active_env["OKX_API_KEY"],
                "OK-ACCESS-PASSPHRASE": active_env["OKX_API_PASSPHRASE"],
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-SIGN": _okx_signature(
                    probe.url,
                    active_env["OKX_SECRET_KEY"],
                    timestamp,
                    method,
                    body_text,
                ),
            }
        )
        project_id = active_env.get("OKX_PROJECT_ID")
        if project_id:
            headers["OK-ACCESS-PROJECT"] = project_id

    return headers, secrets, ()


def _probe_body(probe: ConformanceProbe) -> tuple[bytes | None, str]:
    if probe.json_body is None:
        return None, ""
    body_text = json.dumps(probe.json_body, separators=(",", ":"))
    return body_text.encode("utf-8"), body_text


def _request_for_probe(
    probe: ConformanceProbe, active_env: Mapping[str, str]
) -> tuple[ConformanceHttpRequest | None, tuple[str, ...], tuple[str, ...]]:
    body, body_text = _probe_body(probe)
    headers, secrets, missing_env = _headers_for_probe(probe, active_env, body_text)
    if missing_env:
        return None, secrets, missing_env
    probe_request = ConformanceHttpRequest(
        method=probe.method.value,
        url=probe.url,
        headers=headers,
        body=body,
        timeout_seconds=probe.timeout_seconds,
    )
    return probe_request, secrets, ()


def _append_business_code_assertion(
    payload: Any, probe: ConformanceProbe, assertions: list[str]
) -> None:
    if probe.business_code_path is None:
        return
    observed = _json_path_value(payload, probe.business_code_path)
    ok = observed == probe.business_code_equals
    assertions.append(
        f"business-code:{probe.business_code_path}="
        f"{probe.business_code_equals}:{'ok' if ok else 'failed'}"
    )


def _append_json_assertion(
    payload: Any, assertion: JsonPathAssertion, assertions: list[str]
) -> None:
    value = _json_path_value(payload, assertion.path)
    present = value is not _MISSING
    assertions.append(f"json-path:{assertion.path}:{'ok' if present else 'failed'}")
    if not present:
        return
    if assertion.value_type is not None:
        type_ok = _json_type_matches(value, assertion.value_type)
        assertions.append(
            f"json-type:{assertion.path}:{assertion.value_type.value}:"
            f"{'ok' if type_ok else 'failed'}"
        )
    if assertion.min_size is not None:
        sized_ok = hasattr(value, "__len__") and len(value) >= assertion.min_size
        assertions.append(
            f"json-min-size:{assertion.path}:{assertion.min_size}:"
            f"{'ok' if sized_ok else 'failed'}"
        )
    if assertion.expected_value is not None:
        equals_ok = value == assertion.expected_value
        assertions.append(
            f"json-equals:{assertion.path}:{'ok' if equals_ok else 'failed'}"
        )


def _assertions_verified(assertions: list[str]) -> bool:
    return all(
        item.startswith("credential-mode:")
        or item.startswith("request-method:")
        or item.endswith(":ok")
        for item in assertions
    )


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
    probe_request, secrets, missing_env = _request_for_probe(probe, active_env)
    if missing_env:
        return ConformanceResult(
            contract.id,
            "skipped-missing-env",
            False,
            None,
            (),
            request_method=probe.method.value,
            request_url=probe.url,
            error=(
                "missing credential environment variable(s): " + ", ".join(missing_env)
            ),
        )
    assert probe_request is not None

    try:
        status, body, used_legacy_transport = _invoke_transport(
            transport, probe_request
        )
        strict_assertions = not used_legacy_transport
        assertions = [
            f"credential-mode:{probe.credential_mode.value}",
            f"request-method:{probe_request.method}",
            f"status-code:{'ok' if status == probe.expected_status else 'failed'}",
        ]
        payload: Any | None = None
        needs_json = bool(
            probe.required_json_paths
            or (
                strict_assertions
                and (probe.json_assertions or probe.business_code_path is not None)
            )
        )
        if needs_json:
            payload = json.loads(body.decode("utf-8"))
        if probe.required_json_paths:
            assert payload is not None
            for path in probe.required_json_paths:
                present = _json_path_present(payload, path)
                assertions.append(f"json-path:{path}:{'ok' if present else 'failed'}")
        if probe.business_code_path is not None and strict_assertions:
            assert payload is not None
            _append_business_code_assertion(payload, probe, assertions)
        if probe.json_assertions and strict_assertions:
            assert payload is not None
            for assertion in probe.json_assertions:
                _append_json_assertion(payload, assertion, assertions)
        verified = _assertions_verified(assertions)
        return ConformanceResult(
            contract.id,
            "verified" if verified else "failed-assertion",
            verified,
            status,
            tuple(assertions),
            request_method=probe_request.method,
            request_url=probe_request.url,
            response_sha256=hashlib.sha256(body).hexdigest(),
        )
    except Exception as exc:
        return ConformanceResult(
            contract.id,
            "failed-request",
            False,
            None,
            (),
            request_method=probe_request.method,
            request_url=probe_request.url,
            error=redact_text(str(exc), secrets),
        )
