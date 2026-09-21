"""PR-327..352 closure views for ULTIMATE-MEGA1.

This module extends the canonical AGG-15 coverage concept to NF-001..NF-1016.
It is an audit/view layer only: it does not sign, submit, promote, allocate
capital, mutate providers or become a second release authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

ULTIMATE_EXPECTED_NF_IDS = tuple(range(1, 1017))
ALLOWED_DISPOSITIONS = frozenset(
    {
        "SATISFIED_BY_EXISTING",
        "IMPLEMENTED_OFFLINE",
        "PARTIAL",
        "TODO",
        "BLOCKED_EXTERNAL",
        "PAUSED",
        "DEFERRED_BY_PROFILE",
        "NOT_APPLICABLE_TO_SELECTED_PROFILE",
        "RESEARCH_CLOSED_WITH_RESULT",
    }
)

# Exact compressed partition copied from the roadmap closure packages.
_CLOSURE_SPECS = {
    327: "1-11,16,353-356",
    328: "17-30,365-368,605-608,641-652,661-664",
    329: "31-34,36-44,62-66,77-80,82-83,737-740",
    330: "45-61,250,337-340,369-388,781-784,789-800",
    331: "76,84-89,91-94,197,357-364,393-396,401-408,457-460,653-660,677-680,701-704,729-732,911-915",
    332: "67-69,71,116-118,123,461-464",
    333: "12-15,96-115,445-448,809-812,906-910",
    334: "124-132,135-136,155-173,333-336,341-352,409-424,433-444,449-456,585-592,597-600,709-712,897-905",
    335: "81,119,133-134,137,140-143,152-154,174,239,241-242,489-492,521-524",
    336: "70,120,138,501-508,705-708,757-760,921-930",
    337: "73-74,121-122,139,147-151,465-488,497-500,821-824,916-920,936-940",
    338: "72,144-146,517-520,829-832,961-965",
    339: "175-189,191-193,397-400,529-532,665-676,1002-1016",
    340: "240,243-247,251-256,306,329-332,593-596,601-604,609-612,717-728,733-736,801-804,873-876,881-888",
    341: "75,194-196,198-215,425-432,525-528,613-616,713-716,741-752,805-808",
    342: "90,95,216-232,238,389-392,533-576,681-684,689-700",
    343: "233-237,323,577-584,633-636,753-756,761-768,996-1001",
    344: "257-264,271-285,617-624,833-848,941-960,991-995",
    345: "265-270,286-287,625-628,853-860",
    346: "293,629-632,861-864,986-990",
    347: "288-292,294-295,299,307,509-516,685-688,813-820,931-935,976-985",
    348: "296-298,825-828,849-852,966-975",
    349: "300-305",
    350: "249,313-317,769-780,785-788",
    351: "35,190,248,308-312,318-322,493-496,865-872,877-880,889-892",
    352: "324-328,637-640,893-896",
}

CLOSURE_NAMES = {
    327: "CLOSE-SCOPE",
    328: "CLOSE-REUSE",
    329: "CLOSE-SOURCES",
    330: "CLOSE-DATA",
    331: "CLOSE-RIGHTS",
    332: "CLOSE-VENUES",
    333: "CLOSE-CAPITAL",
    334: "CLOSE-EXACT",
    335: "CLOSE-SOLANA",
    336: "CLOSE-ORDERFLOW",
    337: "CLOSE-CONVERSIONS",
    338: "CLOSE-LIQUIDATIONS",
    339: "CLOSE-QUALIFICATION",
    340: "CLOSE-OPERATIONS",
    341: "CLOSE-EXECUTION",
    342: "CLOSE-INTELLIGENCE",
    343: "CLOSE-SIMULACRUM",
    344: "CLOSE-EVM",
    345: "CLOSE-MOVE",
    346: "CLOSE-CROSSCHAIN",
    347: "CLOSE-INVENTORY",
    348: "CLOSE-PAYOFFS",
    349: "CLOSE-RWA",
    350: "CLOSE-FRONTIER",
    351: "CLOSE-PRODUCTS",
    352: "CLOSE-FINAL",
}


def _expand(spec: str) -> tuple[int, ...]:
    values: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            start, end = (int(value) for value in part.split("-", 1))
            values.extend(range(start, end + 1))
        else:
            values.append(int(part))
    return tuple(values)


CLOSURE_PACKAGES = {
    pr: _expand(spec) for pr, spec in sorted(_CLOSURE_SPECS.items())
}
NF_TO_CLOSURE = {
    nf: pr for pr, values in CLOSURE_PACKAGES.items() for nf in values
}


class UltimateClosureError(ValueError):
    """Malformed or contradictory closure evidence."""


@dataclass(frozen=True, slots=True)
class ClosureEvidence:
    nf_id: int
    primary_owner: str
    contract_ref: str
    test_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    disposition: str
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.nf_id not in NF_TO_CLOSURE:
            raise UltimateClosureError("NF_OUT_OF_SCOPE")
        if not self.primary_owner or not self.contract_ref:
            raise UltimateClosureError("OWNER_CONTRACT_REQUIRED")
        if self.disposition not in ALLOWED_DISPOSITIONS:
            raise UltimateClosureError("INVALID_DISPOSITION")
        if self.disposition in {"SATISFIED_BY_EXISTING", "IMPLEMENTED_OFFLINE"}:
            if not self.test_refs or not self.evidence_refs:
                raise UltimateClosureError("IMPLEMENTATION_EVIDENCE_REQUIRED")


@dataclass(frozen=True, slots=True)
class ClosureAudit:
    mapped_nf_count: int
    evidence_row_count: int
    missing_evidence_nf_ids: tuple[int, ...]
    duplicate_evidence_nf_ids: tuple[int, ...]
    open_implementation_nf_ids: tuple[int, ...]
    operationally_blocked_nf_ids: tuple[int, ...]

    @property
    def structurally_complete(self) -> bool:
        return (
            self.mapped_nf_count == 1016
            and not self.missing_evidence_nf_ids
            and not self.duplicate_evidence_nf_ids
        )

    @property
    def code_closed(self) -> bool:
        return self.structurally_complete and not self.open_implementation_nf_ids


def audit_closure_evidence(rows: Sequence[ClosureEvidence]) -> ClosureAudit:
    if tuple(sorted(NF_TO_CLOSURE)) != ULTIMATE_EXPECTED_NF_IDS:
        raise UltimateClosureError("CLOSURE_PARTITION_NOT_1016")
    counts: dict[int, int] = {}
    by_nf: dict[int, ClosureEvidence] = {}
    for row in rows:
        counts[row.nf_id] = counts.get(row.nf_id, 0) + 1
        by_nf[row.nf_id] = row
    duplicates = tuple(sorted(nf for nf, count in counts.items() if count > 1))
    missing = tuple(nf for nf in ULTIMATE_EXPECTED_NF_IDS if nf not in by_nf)
    open_implementation = tuple(
        sorted(
            row.nf_id
            for row in rows
            if row.disposition in {"PARTIAL", "TODO"}
        )
    )
    operational = tuple(
        sorted(
            row.nf_id
            for row in rows
            if row.disposition
            in {
                "BLOCKED_EXTERNAL",
                "PAUSED",
                "DEFERRED_BY_PROFILE",
                "NOT_APPLICABLE_TO_SELECTED_PROFILE",
            }
        )
    )
    return ClosureAudit(
        mapped_nf_count=len(NF_TO_CLOSURE),
        evidence_row_count=len(rows),
        missing_evidence_nf_ids=missing,
        duplicate_evidence_nf_ids=duplicates,
        open_implementation_nf_ids=open_implementation,
        operationally_blocked_nf_ids=operational,
    )


def assert_static_closure_partition() -> None:
    values = [nf for package in CLOSURE_PACKAGES.values() for nf in package]
    if len(values) != 1016:
        raise UltimateClosureError("CLOSURE_COUNT_NOT_1016")
    if len(set(values)) != 1016:
        raise UltimateClosureError("CLOSURE_DUPLICATE_NF")
    if tuple(sorted(values)) != ULTIMATE_EXPECTED_NF_IDS:
        raise UltimateClosureError("CLOSURE_GAP")


assert_static_closure_partition()

__all__ = [
    "ALLOWED_DISPOSITIONS",
    "CLOSURE_NAMES",
    "CLOSURE_PACKAGES",
    "ClosureAudit",
    "ClosureEvidence",
    "NF_TO_CLOSURE",
    "ULTIMATE_EXPECTED_NF_IDS",
    "UltimateClosureError",
    "assert_static_closure_partition",
    "audit_closure_evidence",
]
