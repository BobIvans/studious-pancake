"""PR-163 / GRAPH-02: typed financial primitives and rights."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega802Error, Primitive, require_text, stable_hash


def define_financial_primitive_type(
    *,
    kind: str,
    asset_id: str,
    unit: str,
    rights: Sequence[str],
    underlying: Sequence[str] = (),
    maturity: int | None = None,
) -> Primitive:
    return Primitive(
        primitive_id=stable_hash(
            {
                "kind": kind,
                "asset_id": asset_id,
                "unit": unit,
                "rights": sorted(rights),
                "underlying": list(underlying),
                "maturity": maturity,
            }
        ),
        kind=kind,
        asset_id=asset_id,
        unit=unit,
        rights=tuple(rights),
        underlying=tuple(underlying),
        maturity=maturity,
    )


def validate_asset_units_and_rights(
    primitive: Primitive, *, expected_unit: str, required_rights: Sequence[str]
) -> bool:
    require_text(expected_unit, "expected_unit")
    if primitive.unit != expected_unit:
        raise Mega802Error("UNIT_MISMATCH")
    missing = set(required_rights) - set(primitive.rights)
    if missing:
        raise Mega802Error(f"MISSING_RIGHTS:{','.join(sorted(missing))}")
    return True


def resolve_wrapper_underlying_chain(
    registry: Mapping[str, Primitive], asset_id: str
) -> tuple[str, ...]:
    require_text(asset_id, "asset_id")
    chain: list[str] = []
    seen: set[str] = set()
    current = asset_id
    while True:
        if current in seen:
            raise Mega802Error("WRAPPER_CYCLE")
        seen.add(current)
        chain.append(current)
        primitive = registry.get(current)
        if primitive is None:
            raise Mega802Error("UNKNOWN_PRIMITIVE")
        if not primitive.underlying:
            return tuple(chain)
        if len(primitive.underlying) != 1:
            raise Mega802Error("AMBIGUOUS_UNDERLYING")
        current = primitive.underlying[0]


def reject_invalid_primitive_composition(
    inputs: Sequence[Primitive],
    outputs: Sequence[Primitive],
    *,
    required_rights: Sequence[str],
) -> tuple[str, ...]:
    if not inputs or not outputs:
        raise Mega802Error("EMPTY_COMPOSITION")
    rights = set().union(*(set(item.rights) for item in inputs))
    missing = set(required_rights) - rights
    if missing:
        raise Mega802Error(f"ILLEGAL_COMPOSITION:{','.join(sorted(missing))}")
    input_units = {item.unit for item in inputs}
    output_units = {item.unit for item in outputs}
    if len(input_units | output_units) > 1:
        raise Mega802Error("INCOMPATIBLE_UNITS")
    return tuple(sorted(item.primitive_id for item in (*inputs, *outputs)))
