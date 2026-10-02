from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import qualification_adapter as qa

SHA = "a" * 40


def request(action="qualification_audit", goal="Проверь блокеры, ничего не запускай"):
    return qa.validate_action_request({
        "schema_version": qa.ACTION_SCHEMA,
        "request_id": "req-1",
        "action": action,
        "goal": goal,
        "source_refs": ["receipt:fastq"],
        "repeat": "once",
        "duration_hours": None,
    })


class AdapterTests(unittest.TestCase):
    def test_laya_high_confidence_cannot_change_or_grant_action(self):
        routed = qa.route_request(
            request(),
            laya_proposal="pause_jobs",
            laya_confidence=0.999,
        )
        self.assertEqual(routed.selected_action, "qualification_audit")
        self.assertFalse(routed.permissions_granted_by_laya)
        self.assertTrue(routed.executable)

    def test_design_only_paper_plan_cannot_execute(self):
        with self.assertRaisesRegex(qa.AdapterError, "DESIGN_ONLY"):
            qa.assert_paper_plan_not_executable(
                {"schema_version": "occ-paper-campaign-proposal.v1"}
            )

    def test_transcript_shell_and_transaction_text_remains_data(self):
        meta = qa.transcript_metadata(
            "powershell curl X; sendTransaction and sendBundle"
        )
        self.assertTrue(meta["contains_execution_like_text"])
        self.assertFalse(meta["raw_text_persisted"])
        self.assertFalse(meta["execution_authority"])

    def test_strict_request_rejects_extra_fields(self):
        raw = {
            "schema_version": qa.ACTION_SCHEMA,
            "request_id": "req",
            "action": "qualification_audit",
            "goal": "x",
            "source_refs": [],
            "repeat": "once",
            "duration_hours": None,
            "shell": "rm -rf /",
        }
        with self.assertRaisesRegex(qa.AdapterError, "FIELDS_MISMATCH"):
            qa.validate_action_request(raw)

    def test_non_qualification_actions_are_never_executed_here(self):
        for action in (
            "intake_once",
            "search_context",
            "draft_work_item",
            "propose_paper_campaign",
            "pause_jobs",
            "job_status",
        ):
            routed = qa.route_request(request(action=action))
            self.assertFalse(routed.executable)
            self.assertIsNone(routed.selected_action)

    def test_child_receipt_keeps_blocker_and_never_promotes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            out = root / "runs"
            child = {
                "schema_version": "pr189.command-result.v1",
                "command": "qualify-and-report",
                "command_mode": "inspect",
                "details": {
                    "request_id": "req-1-fastq",
                    "profile": qa.PROFILE,
                    "qualified": False,
                    "release_authorized": False,
                    "live_authorized": False,
                    "transactions_sent": 0,
                    "sender_free_pass": False,
                    "blockers": [
                        "paper-shadow:blocked_missing_wallet_public_key"
                    ],
                },
            }
            calls = []

            def runner(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    json.dumps(child).encode(),
                    b"diagnostic",
                )

            receipt = qa.execute_qualification_audit(
                request=request(),
                repo_root=repo,
                output_root=out,
                expected_sha=SHA,
                runner=runner,
            )
            self.assertEqual(receipt["domain_verdict"], "BLOCKED")
            self.assertFalse(receipt["qualified"])
            self.assertFalse(receipt["live_authorized"])
            self.assertEqual(receipt["transactions_sent"], 0)
            self.assertEqual(
                receipt["repair_task"]["status"],
                "NEEDS_OPERATOR_INPUT",
            )
            self.assertNotIn(
                "Проверь блокеры",
                json.dumps(receipt, ensure_ascii=False),
            )
            self.assertFalse(calls[0][1]["shell"])
            self.assertEqual(
                calls[0][0][:3],
                [
                    "flashloan-checks",
                    "qualify-and-report",
                    "inspect",
                ],
            )

    def test_unsafe_child_flags_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            out = root / "runs"
            child = {
                "schema_version": "pr189.command-result.v1",
                "command": "qualify-and-report",
                "command_mode": "inspect",
                "details": {
                    "request_id": "req-1-fastq",
                    "profile": qa.PROFILE,
                    "qualified": True,
                    "release_authorized": False,
                    "live_authorized": False,
                    "transactions_sent": 0,
                    "sender_free_pass": False,
                    "blockers": [],
                },
            }

            def runner(argv, **kwargs):
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    json.dumps(child).encode(),
                    b"",
                )

            with self.assertRaisesRegex(qa.AdapterError, "UNSAFE_FLAG"):
                qa.execute_qualification_audit(
                    request=request(),
                    repo_root=repo,
                    output_root=out,
                    expected_sha=SHA,
                    runner=runner,
                )

    def test_same_request_is_reused_and_changed_input_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            out = root / "runs"
            count = 0
            child = {
                "schema_version": "pr189.command-result.v1",
                "command": "qualify-and-report",
                "command_mode": "inspect",
                "details": {
                    "request_id": "req-1-fastq",
                    "profile": qa.PROFILE,
                    "qualified": False,
                    "release_authorized": False,
                    "live_authorized": False,
                    "transactions_sent": 0,
                    "sender_free_pass": False,
                    "blockers": ["b"],
                },
            }

            def runner(argv, **kwargs):
                nonlocal count
                count += 1
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    json.dumps(child).encode(),
                    b"",
                )

            first = qa.execute_qualification_audit(
                request=request(),
                repo_root=repo,
                output_root=out,
                expected_sha=SHA,
                runner=runner,
            )
            second = qa.execute_qualification_audit(
                request=request(),
                repo_root=repo,
                output_root=out,
                expected_sha=SHA,
                runner=runner,
            )
            self.assertFalse(first["reused"])
            self.assertTrue(second["reused"])
            self.assertEqual(count, 1)
            changed = qa.ActionRequest(
                "req-1",
                "qualification_audit",
                "different",
                ("receipt:fastq",),
                "once",
                None,
            )
            with self.assertRaisesRegex(qa.AdapterError, "INPUT_CONFLICT"):
                qa.execute_qualification_audit(
                    request=changed,
                    repo_root=repo,
                    output_root=out,
                    expected_sha=SHA,
                    runner=runner,
                )

    def test_repo_output_overlap_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            with self.assertRaisesRegex(
                qa.AdapterError,
                "MUST_NOT_OVERLAP",
            ):
                qa.execute_qualification_audit(
                    request=request(),
                    repo_root=repo,
                    output_root=repo / "runs",
                    expected_sha=SHA,
                )

    def test_safe_environment_drops_keys_and_providers(self):
        env = qa._safe_env({
            "PATH": "x",
            "OPENAI_API_KEY": "secret",
            "FLASHLOAN_PRIVATE_KEY": "secret",
            "HTTPS_PROXY": "x",
        })
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("FLASHLOAN_PRIVATE_KEY", env)
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertEqual(env["LIVE_TRADING_ENABLED"], "false")
        self.assertEqual(env["FLASHLOAN_JUPITER_ENABLED"], "false")


if __name__ == "__main__":
    unittest.main()
