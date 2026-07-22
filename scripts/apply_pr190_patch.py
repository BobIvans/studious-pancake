"""One-shot repository patcher for PR-190.

This script is executed by the temporary PR-190 bootstrap workflow and deletes
itself plus that workflow after applying the exact active-path integration.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"expected exactly one match in {path}, found {count}: {old[:80]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_runtime() -> None:
    replace_once("src/config/runtime.py", "import hashlib\n", "")
    replace_once("src/config/runtime.py", "import json\n", "")
    replace_once("src/config/runtime.py", "import yaml\n", "")
    replace_once(
        "src/config/runtime.py",
        "from src.config.secret_resolver import SecretHandle, resolve_secret_reference\n",
        "from src.config.canonical import canonical_digest\n"
        "from src.config.secret_resolver import SecretHandle, resolve_secret_reference\n"
        "from src.config.strict_yaml import StrictYamlError, loads_strict_yaml\n",
    )
    replace_once(
        "src/config/runtime.py",
        '''    def fingerprint(self) -> str:\n        payload = json.dumps(\n            self._fingerprint_dict(), sort_keys=True, separators=(",", ":")\n        ).encode("utf-8")\n        return hashlib.sha256(payload).hexdigest()\n''',
        '''    def safe_display(self) -> dict[str, Any]:\n        return self.redacted_dict()\n\n    def identity_payload(self) -> dict[str, Any]:\n        return self._fingerprint_dict()\n\n    def runtime_materialization(self) -> dict[str, Any]:\n        return self._fingerprint_dict()\n\n    def fingerprint(self) -> str:\n        return canonical_digest(\n            self.identity_payload(),\n            domain="flashloan.runtime-config",\n            schema_version=self.schema_version,\n            environment=self.cluster.name,\n        )\n''',
    )
    replace_once(
        "src/config/runtime.py",
        '''def _read_yaml(path: Path) -> dict[str, Any]:\n    try:\n        payload = yaml.safe_load(path.read_text(encoding="utf-8"))\n    except (OSError, yaml.YAMLError) as exc:\n        raise ConfigurationLoadError(\n            f"cannot read configuration file {path}: {exc}"\n        ) from exc\n    if payload is None:\n        return {}\n    if not isinstance(payload, dict):\n        raise ConfigurationLoadError("configuration root must be a mapping")\n    return payload\n\n\ndef _default_payload() -> dict[str, Any]:\n    resource = resources.files("src.resources").joinpath("runtime.default.yaml")\n    payload = yaml.safe_load(resource.read_text(encoding="utf-8"))\n    if not isinstance(payload, dict):\n        raise ConfigurationLoadError("packaged runtime defaults are invalid")\n    return payload\n''',
        '''def _read_yaml(path: Path) -> dict[str, Any]:\n    try:\n        return loads_strict_yaml(path.read_text(encoding="utf-8"))\n    except (OSError, StrictYamlError) as exc:\n        raise ConfigurationLoadError(\n            f"cannot read configuration file {path}: {exc}"\n        ) from exc\n\n\ndef _default_payload() -> dict[str, Any]:\n    resource = resources.files("src.resources").joinpath("runtime.default.yaml")\n    try:\n        return loads_strict_yaml(resource.read_text(encoding="utf-8"))\n    except StrictYamlError as exc:\n        raise ConfigurationLoadError("packaged runtime defaults are invalid") from exc\n''',
    )


def patch_live_control() -> None:
    replace_once("src/execution/live_control.py", "import yaml\n\n", "")
    replace_once(
        "src/execution/live_control.py",
        "from src.execution.journal import SQLiteAttemptJournal\n",
        "from src.execution.journal import SQLiteAttemptJournal\n"
        "from src.execution.live_policy import (\n"
        "    LiveRiskPolicy,\n"
        "    canonical_policy_hash,\n"
        "    load_live_policy,\n"
        ")\n",
    )
    replace_once(
        "src/execution/live_control.py",
        '''def load_policy(path: str | Path) -> dict[str, Any]:\n    with open(path, "r", encoding="utf-8") as f:\n        data = yaml.safe_load(f) or {}\n    if not isinstance(data, dict):\n        raise ValueError("live risk config must be a mapping")\n    return data\n\n\ndef canonical_policy_hash(policy: dict[str, Any]) -> str:\n    sanitized = _redact(policy)\n    blob = json.dumps(\n        sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=True\n    )\n    return hashlib.sha256(blob.encode()).hexdigest()\n''',
        '''def load_policy(path: str | Path) -> LiveRiskPolicy:\n    return load_live_policy(path)\n''',
    )
    replace_once(
        "src/execution/live_control.py",
        "        policy: dict[str, Any],\n        store: LiveControlStore,\n",
        "        policy: LiveRiskPolicy | dict[str, Any],\n        store: LiveControlStore,\n",
    )
    replace_once(
        "src/execution/live_control.py",
        "        policy: dict[str, Any],\n        store: LiveControlStore,\n",
        "        policy: LiveRiskPolicy | dict[str, Any],\n        store: LiveControlStore,\n",
    )
    replace_once(
        "src/execution/live_control.py",
        ") -> tuple[dict[str, Any], LiveControlStore, SQLiteAttemptJournal, str]:\n",
        ") -> tuple[LiveRiskPolicy, LiveControlStore, SQLiteAttemptJournal, str]:\n",
    )


def cleanup_bootstrap() -> None:
    for relative in (
        "scripts/apply_pr190_patch.py",
        ".github/workflows/pr190-bootstrap.yml",
    ):
        path = ROOT / relative
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    patch_runtime()
    patch_live_control()
    cleanup_bootstrap()
