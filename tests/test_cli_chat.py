import io
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mini_claw.agent.state import AgentResult
from mini_claw.cli import _resolve_chat_task_from_session, cmd_chat, make_parser
from mini_claw.sessions.store import SessionManager


class ChatCliTest(unittest.TestCase):
    def test_chat_parser_defaults_to_merge_back_and_higher_step_budget(self) -> None:
        parser = make_parser()
        args = parser.parse_args(["chat"])

        self.assertEqual(args.max_steps, 12)
        self.assertTrue(args.merge_back)
        self.assertTrue(args.rollback_on_merge_verification_failure)

    def test_chat_creates_session_and_runs_turns(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            args = Namespace(
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=4,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session="",
                session_name="chat-demo",
                turn_limit=5,
                execution_mode="copy",
                show_execution_diff=False,
                merge_back=False,
                merge_verify=[],
                rollback_on_merge_verification_failure=True,
            )

            output = io.StringIO()
            with patch("builtins.input", side_effect=["inspect this repository", "/session", "/exit"]):
                with redirect_stdout(output):
                    exit_code = cmd_chat(args)

            self.assertEqual(exit_code, 0)
            rendered = output.getvalue()
            self.assertIn("[chat] session=session-", rendered)
            self.assertIn("Mock run completed", rendered)
            self.assertIn("[chat] closed session-", rendered)

            manager = SessionManager(root)
            sessions = manager.list_sessions(limit=5)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].name, "chat-demo")
            turns = manager.list_turns(sessions[0].session_id, limit=5)
            self.assertEqual(len(turns), 1)
            self.assertIn("inspect this repository", turns[0].task)

    def test_chat_resolves_previous_turn_reference_to_recent_path(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cheshi").mkdir()
            manager = SessionManager(root)
            session = manager.create(name="resolver")
            turn = manager.begin_turn(session.session_id, "create cheshi folder")
            manager.complete_turn(
                session.session_id,
                turn.turn_id,
                result=AgentResult(
                    success=True,
                    final_answer="Created cheshi folder.",
                    steps=[],
                    modified_files=["cheshi/"],
                ),
                trace_lines=[],
                merge_back_status="ok",
                merge_back_output="merged",
                merge_back_files=["cheshi"],
            )

            resolved_task, notice = _resolve_chat_task_from_session(
                session_manager=manager,
                session_ref=session.session_id,
                task="就是我刚刚让你新建的那个文件夹",
                workspace=root,
            )

            self.assertIn("cheshi", resolved_task)
            self.assertIn("Resolved previous-turn reference", notice)
            self.assertIn("absolute_path", resolved_task)

    def test_chat_answers_recent_path_lookup_without_invoking_agent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cheshi").mkdir()
            manager = SessionManager(root)
            session = manager.create(name="direct-lookup")
            turn = manager.begin_turn(session.session_id, "create cheshi folder")
            manager.complete_turn(
                session.session_id,
                turn.turn_id,
                result=AgentResult(
                    success=True,
                    final_answer="Created cheshi folder.",
                    steps=[],
                    modified_files=["cheshi/"],
                ),
                trace_lines=[],
                merge_back_status="ok",
                merge_back_output="merged",
                merge_back_files=["cheshi"],
            )

            args = Namespace(
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=4,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session=session.session_id,
                session_name="chat-demo",
                turn_limit=5,
                execution_mode="copy",
                show_execution_diff=False,
                merge_back=False,
                merge_verify=[],
                rollback_on_merge_verification_failure=True,
            )

            output = io.StringIO()
            with patch("mini_claw.cli.cmd_run", side_effect=AssertionError("cmd_run should not be called")):
                with patch("builtins.input", side_effect=["这个文件夹的位置在哪里", "/exit"]):
                    with redirect_stdout(output):
                        exit_code = cmd_chat(args)

            self.assertEqual(exit_code, 0)
            rendered = output.getvalue()
            self.assertIn("`cheshi`", rendered)
            self.assertIn("绝对路径", rendered)


if __name__ == "__main__":
    unittest.main()
