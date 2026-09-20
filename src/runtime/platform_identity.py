"""Authoritative runtime-platform identity and native known-answer probes.

MPR-RP-01 combines the PR-053 native-runtime qualification boundary with the
PR-057 command dependency admission boundary.  Importing this module is
side-effect free: no network, credential, persistence, signer, or sender access
occurs while identity and policy are inspected.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from importlib import metadata, resources
import json
import os
from pathlib import Path
import platform
import ssl
import sys
import sysconfig
from typing import Any, Iterable, Mapping

PLATFORM_SCHEMA = "mpr-rp-01.platform-identity.v1"
QUALIFICATION_SCHEMA = "mpr-rp-01.platform-qualification.v1"


class PlatformQualificationError(RuntimeError):
    """The current runtime platform is not admitted for the requested mode."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalized_machine(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _normalized_libc(system: str, name: str) -> str:
    value = name.strip().lower()
    if system == "Darwin":
        return "libsystem"
    if system == "Windows":
        return "msvcrt"
    if value in {"glibc", "gnu libc", "libc"}:
        return "glibc"
    if "musl" in value:
        return "musl"
    return value or "unknown"


def _python_abi() -> str:
    soabi = str(sysconfig.get_config_var("SOABI") or "")
    if soabi.startswith("cpython-"):
        digits = soabi.removeprefix("cpython-").split("-", 1)[0]
        if digits.isdigit():
            return f"cp{digits}"
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def _event_loop_policy_name() -> str:
    try:
        import asyncio

        policy = asyncio.get_event_loop_policy()
    except Exception:
        return "unknown"
    module = type(policy).__module__.lower()
    if "uvloop" in module:
        return "uvloop"
    return "asyncio"


@dataclass(frozen=True, slots=True)
class NativeDistributionIdentity:
    name: str
    version: str | None
    record_sha256: str | None
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlatformIdentity:
    schema_version: str
    system: str
    release: str
    kernel: str
    machine: str
    python_version: str
    python_implementation: str
    python_abi: str
    libc_name: str
    libc_version: str
    openssl_version: str
    event_loop_policy: str
    executable_realpath: str
    native_distributions: tuple[NativeDistributionIdentity, ...]
    environment_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["native_distributions"] = [
            item.to_dict() for item in self.native_distributions
        ]
        return payload

    @property
    def fingerprint(self) -> str:
        return _sha256(_canonical_json(self.to_dict()))


@dataclass(frozen=True, slots=True)
class PlatformQualification:
    schema_version: str
    admitted: bool
    requested_mode: str
    matched_platform_id: str | None
    blockers: tuple[str, ...]
    identity: PlatformIdentity
    policy_sha256: str
    known_answer_results: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "admitted": self.admitted,
            "requested_mode": self.requested_mode,
            "matched_platform_id": self.matched_platform_id,
            "blockers": list(self.blockers),
            "identity": self.identity.to_dict(),
            "identity_sha256": self.identity.fingerprint,
            "policy_sha256": self.policy_sha256,
            "known_answer_results": dict(self.known_answer_results),
        }


def _distribution_identity(name: str) -> NativeDistributionIdentity:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return NativeDistributionIdentity(
            name=name,
            version=None,
            record_sha256=None,
            status="missing",
        )
    record = dist.read_text("RECORD")
    digest = _sha256(record.encode("utf-8")) if record is not None else None
    return NativeDistributionIdentity(
        name=name,
        version=dist.version,
        record_sha256=digest,
        status="installed",
    )


def load_platform_policy(path: str | Path | None = None) -> dict[str, Any]:
    if path is not None:
        source = Path(path)
        raw = source.read_text(encoding="utf-8")
    else:
        root = Path(__file__).resolve().parents[2]
        repository_policy = root / "config" / "supported_runtime_platforms.json"
        if repository_policy.is_file():
            raw = repository_policy.read_text(encoding="utf-8")
        else:
            raw = resources.files("src.resources").joinpath(
                "supported_runtime_platforms.json"
            ).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("platforms"), list):
        raise PlatformQualificationError("supported platform policy is malformed")
    return value


def capture_platform_identity(
    *,
    native_distributions: Iterable[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> PlatformIdentity:
    policy = load_platform_policy()
    names = tuple(native_distributions or policy.get("native_distributions", ()))
    libc_name, libc_version = platform.libc_ver()
    system = platform.system()
    env = os.environ if environ is None else environ
    selected = {
        key: env[key]
        for key in sorted(env)
        if key in {"LANG", "LC_ALL", "TZ", "PYTHONHASHSEED", "PYTHONUTF8"}
    }
    return PlatformIdentity(
        schema_version=PLATFORM_SCHEMA,
        system=system,
        release=platform.release(),
        kernel=platform.version(),
        machine=_normalized_machine(platform.machine()),
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        python_abi=_python_abi(),
        libc_name=_normalized_libc(system, libc_name),
        libc_version=libc_version or "unknown",
        openssl_version=ssl.OPENSSL_VERSION,
        event_loop_policy=_event_loop_policy_name(),
        executable_realpath=str(Path(sys.executable).resolve()),
        native_distributions=tuple(_distribution_identity(name) for name in names),
        environment_fingerprint=_sha256(_canonical_json(selected)),
    )


def probe_solders_known_answers() -> Mapping[str, str]:
    """Execute deterministic, dependency-local byte round trips.

    The probe intentionally avoids network calls, random values, signing keys, and
    transaction submission.  A compatible-looking but semantically broken native
    extension therefore blocks transaction capability before active work begins.
    """

    from solders.pubkey import Pubkey

    vector = bytes(range(32))
    pubkey = Pubkey.from_bytes(vector)
    if bytes(pubkey) != vector:
        raise PlatformQualificationError("solders Pubkey byte round-trip mismatch")
    text = str(pubkey)
    restored = Pubkey.from_string(text)
    if bytes(restored) != vector:
        raise PlatformQualificationError("solders Pubkey base58 round-trip mismatch")
    return {
        "pubkey_bytes_sha256": _sha256(bytes(pubkey)),
        "pubkey_base58_sha256": _sha256(text.encode("ascii")),
    }


def _platform_matches(identity: PlatformIdentity, rule: Mapping[str, Any]) -> bool:
    machines = {_normalized_machine(str(item)) for item in rule.get("machines", ())}
    libcs = {str(item).strip().lower() for item in rule.get("libc", ())}
    event_loops = {str(item) for item in rule.get("event_loops", ())}
    return (
        identity.system == str(rule.get("system"))
        and identity.machine in machines
        and identity.libc_name in libcs
        and identity.python_abi == str(rule.get("python_abi"))
        and identity.event_loop_policy in event_loops
    )


def qualify_platform(
    identity: PlatformIdentity,
    *,
    requested_mode: str,
    policy: Mapping[str, Any],
    run_native_known_answers: bool = False,
) -> PlatformQualification:
    blockers: list[str] = []
    matched: Mapping[str, Any] | None = None
    for candidate in policy.get("platforms", ()):
        if isinstance(candidate, Mapping) and _platform_matches(identity, candidate):
            matched = candidate
            break
    if matched is None:
        blockers.append("PLATFORM_NOT_QUALIFIED")
    elif requested_mode not in set(map(str, matched.get("allowed_modes", ()))):
        blockers.append("PLATFORM_MODE_NOT_QUALIFIED")

    known_answers: dict[str, str] = {}
    if run_native_known_answers:
        try:
            known_answers.update(probe_solders_known_answers())
        except ModuleNotFoundError:
            blockers.append("NATIVE_DEPENDENCY_MISSING:solders")
        except Exception as exc:
            blockers.append(f"NATIVE_KNOWN_ANSWER_FAILED:{type(exc).__name__}")

    policy_sha = _sha256(_canonical_json(policy))
    return PlatformQualification(
        schema_version=QUALIFICATION_SCHEMA,
        admitted=not blockers,
        requested_mode=requested_mode,
        matched_platform_id=(str(matched.get("id")) if matched is not None else None),
        blockers=tuple(blockers),
        identity=identity,
        policy_sha256=policy_sha,
        known_answer_results=known_answers,
    )


def qualify_current_platform(
    *,
    requested_mode: str = "disabled",
    run_native_known_answers: bool = False,
    policy_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> PlatformQualification:
    policy = load_platform_policy(policy_path)
    identity = capture_platform_identity(
        native_distributions=policy.get("native_distributions", ()),
        environ=environ,
    )
    return qualify_platform(
        identity,
        requested_mode=requested_mode,
        policy=policy,
        run_native_known_answers=run_native_known_answers,
    )
