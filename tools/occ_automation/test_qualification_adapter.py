from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from src import fast_q_automation as fastq

SHA = "a" * 40
TOOL = Path(__file__).resolve().parent


def request(
    action: str = "qualify_and_report",
    *,
    text: str | None = None,
    proposal: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": fastq.REQUEST_SCHEMA,
        "request_id": "req-1",
        "idempotency_key": "req-1",
        "action": action,
        "text": text,
        "inputs": {},
        "proposal": proposal,
    }


class OccFastQBoundaryTests(unittest.TestCase):
    def test_laya_proposal_cannot_change_explicit_action(self):
        raw = request(
            proposal={
                "source": "laya",
                "action": "transcribe_local_audio",
            }
        )
        normalized = fastq.validate_request(raw)
        self.assertEqual(normalized["action"], "qualify_and_report")

    def test_laya_confidence_field_cannot_grant_permission(self):
        raw = request(
            proposal={
                "source": "laya",
                "action": "qualify_and_report",
                "confidence": "1.0",
            }
        )
        with self.assertRaisesRegex(ValueError, "PROPOSAL_INVALID"):
            fastq.validate_request(raw)

    def test_design_only_paper_plan_is_not_action_request(self):
        plan = json.loads(
            (TOOL / "config" / "paper_campaign.plan.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            plan["schema_version"],
            "occ-paper-campaign-proposal.v1",
        )
        self.assertFalse(plan["native_adapter_compatible"])
        with self.assertRaisesRegex(
            ValueError,
            "REQUEST_SCHEMA_OR_FIELDS_INVALID",
        ):
            fastq.validate_request(plan)

    def test_transaction_like_text_is_rejected_not_executed(self):
        raw = request(
            action="qualify_and_report",
            text="send transaction now",
        )
        with self.assertRaisesRegex(ValueError, "LIVE_OR_UNSAFE"):
            fastq.validate_request(raw)

    def test_external_asr_action_is_contract_only(self):
        raw = request(action="transcribe_local_audio")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(
                fastq,
                "_check_source",
                return_value={"git_sha": SHA},
            ):
                receipt = fastq.execute_request(
                    raw,
                    repo_root=root / "repo",
                    output_root=root / "out",
                    expected_sha=SHA,
                )
        contract = receipt["result"]["adapter_contract"]
        self.assertEqual(
            receipt["status"],
            "EXTERNAL_ADAPTER_REQUIRED",
        )
        self.assertFalse(contract["core_execution_performed"])
        self.assertFalse(contract["model_supplied_paths_allowed"])
        self.assertFalse(contract["paid_api_fallback"])

    def test_registered_actions_do_not_include_shell_or_send(self):
        forbidden = {
            "shell",
            "exec",
            "execute_shell",
            "send_transaction",
            "send_bundle",
            "sign",
            "trade_live",
        }
        self.assertFalse(forbidden.intersection(fastq.ACTION_IDS))

    def test_private_request_text_is_not_persisted_in_receipt(self):
        phrase = "Проверь готовность бота"
        raw = {
            "schema_version": fastq.LEGACY_REQUEST_SCHEMA,
            "request_id": "private-1",
            "text": phrase,
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with (
                mock.patch.object(
                    fastq,
                    "_check_source",
                    return_value={"git_sha": SHA},
                ),
                mock.patch.object(
                    fastq,
                    "_execute_qualification",
                    return_value={
                        "status": "INSPECTED",
                        "blockers": ["blocked"],
                        "first_blocker": "blocked",
                        "next_action": "inspect_current_blocker",
                        "limitations": [],
                    },
                ),
            ):
                fastq.execute_request(
                    raw,
                    repo_root=root / "repo",
                    output_root=root / "out",
                    expected_sha=SHA,
                )
            saved = (
                root
                / "out"
                / "actions"
                / "private-1"
                / "receipt.json"
            ).read_text(encoding="utf-8")
        self.assertNotIn(phrase, saved)

    def test_secret_bearing_inputs_fail_closed(self):
        raw = request(action="inspect_current_blocker")
        raw["inputs"] = {
            "qualification_request_id": "q1",
            "api_key": "secret",
        }
        with self.assertRaisesRegex(ValueError, "SECRET_BEARING"):
            fastq.validate_request(raw)

    def test_current_wallet_blocker_never_allows_patch(self):
        owner = fastq._owner_for(
            "paper-shadow:blocked_missing_wallet_public_key"
        )
        self.assertIsNotNone(owner)
        self.assertFalse(owner["patch_allowed"])
        self.assertEqual(
            owner["stop_reason"],
            "EXTERNAL_OPERATOR_INPUT_REQUIRED",
        )

    def test_voice_schema_contains_only_registered_proposals(self):
        tools = json.loads(
            (TOOL / "config" / "voice_tools.responses.json").read_text(
                encoding="utf-8"
            )
        )
        enum = set(
            tools[0]["parameters"]["properties"]["action"]["enum"]
        )
        unsafe = {
            "shell",
            "exec",
            "send_transaction",
            "send_bundle",
            "merge",
            "trade_live",
        }
        self.assertFalse(enum.intersection(unsafe))


if __name__ == "__main__":
    unittest.main()
