from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from src.providers.jupiter.router import (
    JUPITER_MAX_DECODED_INSTRUCTION_BYTES,
    JUPITER_MAX_INSTRUCTIONS_BY_BUCKET,
    JupiterBuildRequest,
    JupiterRejectionReason,
    JupiterRouterError,
    parse_build_response,
    strict_json_loads,
)

pytestmark = pytest.mark.unit

REQ = JupiterBuildRequest(
    input_mint="So11111111111111111111111111111111111111112",
    output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    amount=1_000_000,
    taker="Takr111111111111111111111111111111111111111",
    slippage_bps=100,
    wrap_and_unwrap_sol=False,
)


def load_success() -> dict[str, object]:
    path = Path("tests/fixtures/providers/jupiter/router_build_success_2026-07-19.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_error(data: dict[str, object]) -> JupiterRouterError:
    with pytest.raises(JupiterRouterError) as excinfo:
        parse_build_response(data, REQ)
    assert excinfo.value.reason is JupiterRejectionReason.SCHEMA_FAILURE
    return excinfo.value


def test_pr179_rejects_duplicate_json_keys() -> None:
    with pytest.raises(JupiterRouterError) as excinfo:
        strict_json_loads('{"routePlan": [], "routePlan": []}')

    assert excinfo.value.reason is JupiterRejectionReason.SCHEMA_FAILURE
    assert "duplicate" in str(excinfo.value)


def test_pr179_rejects_non_finite_json_constants() -> None:
    with pytest.raises(JupiterRouterError) as excinfo:
        strict_json_loads('{"slippageBps": NaN}')

    assert excinfo.value.reason is JupiterRejectionReason.SCHEMA_FAILURE
    assert "non-finite" in str(excinfo.value)


def test_pr179_malformed_instruction_list_element_rejects_entire_response() -> None:
    data = load_success()
    setup = data["setupInstructions"]
    assert isinstance(setup, list)
    setup.append("malformed-string")

    error = _schema_error(data)

    assert "setupInstructions" in str(error)
    assert "malformed" in str(error)


def test_pr179_malformed_alt_entry_rejects_entire_response() -> None:
    data = load_success()
    alt = data["addressesByLookupTableAddress"]
    assert isinstance(alt, dict)
    alt["ALT1111111111111111111111111111111111111111"].append(123)  # type: ignore[index]

    error = _schema_error(data)

    assert "ALT" in str(error)
    assert "malformed" in str(error)


def test_pr179_route_plan_malformed_item_rejects_response() -> None:
    data = load_success()
    route = data["routePlan"]
    assert isinstance(route, list)
    route.append(["not", "a", "mapping"])

    error = _schema_error(data)

    assert "routePlan" in str(error)
    assert "malformed" in str(error)


def test_pr179_instruction_byte_budget_fails_before_execution_build() -> None:
    data = load_success()
    swap = data["swapInstruction"]
    assert isinstance(swap, dict)
    payload = b"x" * (JUPITER_MAX_DECODED_INSTRUCTION_BYTES + 1)
    swap["data"] = base64.b64encode(payload).decode("ascii")

    error = _schema_error(data)

    assert "instruction data exceeds structural budget" in str(error)


def test_pr179_instruction_bucket_budget_is_enforced() -> None:
    data = load_success()
    setup = data["setupInstructions"]
    assert isinstance(setup, list)
    first = setup[0]
    setup[:] = [first] * (JUPITER_MAX_INSTRUCTIONS_BY_BUCKET["setupInstructions"] + 1)

    error = _schema_error(data)

    assert "setupInstructions exceeds structural budget" in str(error)


def test_pr179_blockhash_shape_is_exact() -> None:
    data = load_success()
    blockhash = data["blockhashWithMetadata"]
    assert isinstance(blockhash, dict)
    blockhash["blockhash"] = [1, 2, 3]

    error = _schema_error(data)

    assert "blockhashWithMetadata.blockhash invalid" in str(error)
