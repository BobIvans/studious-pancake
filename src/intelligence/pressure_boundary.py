"""Owner-supplied pressure port for the existing sequential batch supervisor."""

from collections.abc import Callable
from pathlib import Path

from .common import digest, save_json, seal
from .pressure_manager import run_pressure_cycle

ADMISSION_BLOCKED = "AGG02_STORAGE_PRESSURE_ADMISSION_BLOCKED"


class StoragePressureBoundary:
    """Inventory comes from the collection owner, never a model or guessed store.

    Expose this callable as ``storage_pressure_boundary`` on a managed source.
    The installed supervisor invokes it synchronously between durable cycles.
    """

    def __init__(
        self,
        *,
        state_root: str | Path,
        journal_path: str | Path,
        output_dir: str | Path,
        inventory: Callable[[], dict],
    ) -> None:
        self.state_root = Path(state_root)
        self.journal_path = Path(journal_path)
        self.output_dir = Path(output_dir)
        self.inventory = inventory

    def __call__(self, *, batch_id: str, trigger: str) -> dict:
        if trigger not in {"BATCH_BOUNDARY", ADMISSION_BLOCKED}:
            raise ValueError("unknown storage pressure trigger")
        try:
            inventory = self.inventory()
            cycle = run_pressure_cycle(
                state_root=self.state_root,
                journal_path=self.journal_path,
                output_dir=self.output_dir,
                records=inventory.get("records", []),
                references=inventory.get("references", []),
                reference_inventory_complete=inventory.get("inventory_complete")
                is True,
                execute=True,
                batch_id=f"{batch_id}:{trigger}",
            )
            pause = (
                cycle.get("admission_pause_required") is True
                or trigger == ADMISSION_BLOCKED
            )
            receipt = seal(
                {
                    "schema": "studious.storage-pressure-boundary.v1",
                    "batch_id": batch_id,
                    "trigger": trigger,
                    "cycle": cycle,
                    "admission_pause_required": pause,
                    "status": "ADMISSION_PAUSE_REQUIRED" if pause else "CONTINUE",
                    "live_authorized": False,
                }
            )
        except Exception as exc:
            # Record only the exception type; provider messages can carry URLs.
            receipt = seal(
                {
                    "schema": "studious.storage-pressure-boundary.v1",
                    "batch_id": batch_id,
                    "trigger": trigger,
                    "admission_pause_required": True,
                    "status": "ADMISSION_PAUSE_REQUIRED",
                    "reason": "PRESSURE_CYCLE_FAILED",
                    "error_type": type(exc).__name__,
                    "live_authorized": False,
                }
            )
        if receipt["admission_pause_required"]:
            save_json(
                self.output_dir
                / f"blocker-{digest({'batch': batch_id, 'trigger': trigger})}.json",
                receipt,
            )
        return receipt
