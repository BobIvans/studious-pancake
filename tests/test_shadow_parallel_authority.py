from dataclasses import asdict, replace
import pytest
from tests.test_pr02_unified_lifecycle_authority import FakeTimeAuthority, digest
from src.durability.unified_authority_pr02 import (
    UnifiedLifecycleAuthority,
    UnifiedAuthorityError,
)
from src.strategy.conflict_scheduler import WorkResourceSet
from src.strategy.shadow_portfolio import (
    ShadowPortfolioCandidate,
    allocate_shadow_portfolio,
)
from src.mechanism_discovery.pr356_contracts import PR356ContractError


def authority(path, clock, owner):
    return UnifiedLifecycleAuthority(
        path,
        release_digest=digest("release"),
        policy_bundle_hash=digest("policy"),
        time_authority=clock,
        owner_id=owner,
    )


def test_independent_connections_share_resource_claims_and_fences(tmp_path):
    clock = FakeTimeAuthority()
    first = authority(tmp_path / "one.db", clock, "worker-a")
    second = authority(tmp_path / "one.db", clock, "worker-b")

    def begin(store, work, resources):
        return store.begin_shadow_work(
            work_id=work,
            generation=1,
            state_generation="frame",
            resource_payload=asdict(resources),
        )

    fence = begin(first, "a", WorkResourceSet(writable_accounts=("pool",)))
    with pytest.raises(UnifiedAuthorityError, match="CONFLICT"):
        begin(second, "b", WorkResourceSet(readonly_accounts=("pool",)))
    other = begin(second, "c", WorkResourceSet(readonly_accounts=("oracle",)))
    with pytest.raises(UnifiedAuthorityError, match="MISMATCH"):
        first.commit_shadow_work(
            replace(fence, fencing_token=2), evidence={"result": 1}
        )
    receipt = first.commit_shadow_work(fence, evidence={"result": 1})
    replay = first.commit_shadow_work(fence, evidence={"result": 1})
    assert replay.terminal_id == receipt.terminal_id
    assert replay.replayed
    assert begin(second, "b", WorkResourceSet(readonly_accounts=("pool",)))
    first.close()
    second.close()


def test_dead_worker_claim_is_not_silently_released_on_restart(tmp_path):
    clock = FakeTimeAuthority()
    first = authority(tmp_path / "one.db", clock, "a")
    first.begin_shadow_work(
        work_id="a",
        generation=1,
        state_generation="f",
        resource_payload=asdict(WorkResourceSet(pools=("pool",))),
    )
    first.close()
    clock.reboot()
    second = authority(tmp_path / "one.db", clock, "b")
    with pytest.raises(UnifiedAuthorityError, match="CONFLICT"):
        second.begin_shadow_work(
            work_id="b",
            generation=1,
            state_generation="f",
            resource_payload=asdict(WorkResourceSet(pools=("pool",))),
        )
    second.close()


def test_finite_portfolio_beats_greedy_fixture_and_common_payer_blocks_parallelism():
    spec = [
        ("A", 9, "1", "1"),
        ("B", 8, "1", "2"),
        ("C", 7, "2", "1"),
        ("D", 1, "2", "3"),
        ("E", 5, "3", "4"),
        ("F", 4, "4", "5"),
    ]
    rows = tuple(
        ShadowPortfolioCandidate(
            cid,
            score,
            0,
            (("cpu", 1),),
            WorkResourceSet(
                pools=(pool,),
                economic_resources=(reserve,),
                fee_payer=cid,
                readonly_accounts=("oracle",),
            ),
        )
        for cid, score, pool, reserve in spec
    )
    result = allocate_shadow_portfolio(
        rows, budget={"cpu": 3}, max_selected=3, max_tail_loss_units=0
    )
    assert result.candidate_ids == ("B", "C", "E")
    assert result.expected_utility_units == 20
    greedy = []
    for row in sorted(
        rows, key=lambda item: (-item.expected_utility_units, item.candidate_id)
    ):
        if len(greedy) < 3 and not any(
            row.resources.conflicts_with(previous.resources) for previous in greedy
        ):
            greedy.append(row)
    assert sum(row.expected_utility_units for row in greedy) == 18
    shared = tuple(
        replace(row, resources=replace(row.resources, fee_payer="common"))
        for row in rows
    )
    assert allocate_shadow_portfolio(
        shared, budget={"cpu": 3}, max_selected=3, max_tail_loss_units=0
    ).candidate_ids == ("A",)
    with pytest.raises(PR356ContractError, match="DIMENSION_MISSING"):
        allocate_shadow_portfolio(
            rows, budget={}, max_selected=3, max_tail_loss_units=0
        )


def test_simultaneous_resource_claims_have_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "race.db"
    clock = FakeTimeAuthority()
    initializer = authority(path, clock, "initializer")
    initializer.close()
    barrier = Barrier(2)

    def contender(owner):
        store = authority(path, clock, owner)
        try:
            barrier.wait(timeout=5)
            try:
                store.begin_shadow_work(
                    work_id=owner,
                    generation=1,
                    state_generation="frame",
                    resource_payload=asdict(
                        WorkResourceSet(economic_resources=("shared-lender-cash",))
                    ),
                )
                return "admitted"
            except UnifiedAuthorityError as error:
                assert "CONFLICT" in str(error)
                return "denied"
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, ("a", "b")))
    assert sorted(results) == ["admitted", "denied"]
