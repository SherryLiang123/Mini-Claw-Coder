import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.cli import cmd_run, cmd_session
from mini_claw.sessions.store import SessionManager


class SessionCliTest(unittest.TestCase):
    def test_session_create_run_and_show(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            create_args = Namespace(
                workspace=str(root),
                session_command="create",
                name="demo-session",
                json=False,
            )
            create_buffer = io.StringIO()
            with redirect_stdout(create_buffer):
                create_exit = cmd_session(create_args)

            self.assertEqual(create_exit, 0)
            self.assertIn("created session-", create_buffer.getvalue())

            run_args = Namespace(
                task="inspect this repository",
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session="1",
            )
            run_buffer = io.StringIO()
            with redirect_stdout(run_buffer):
                run_exit = cmd_run(run_args)

            self.assertEqual(run_exit, 0)
            self.assertIn("Mock run completed", run_buffer.getvalue())

            show_args = Namespace(
                workspace=str(root),
                session_command="show",
                ref="1",
                turn_limit=5,
                max_chars=2000,
                json=False,
            )
            show_buffer = io.StringIO()
            with redirect_stdout(show_buffer):
                show_exit = cmd_session(show_args)

            self.assertEqual(show_exit, 0)
            output = show_buffer.getvalue()
            self.assertIn("session_context_preview:", output)
            self.assertIn("turn_count: 1", output)
            self.assertIn("inspect this repository", output)

            replay_args = Namespace(
                workspace=str(root),
                session_command="replay",
                ref="1",
                turn_limit=10,
                json=False,
            )
            replay_buffer = io.StringIO()
            with redirect_stdout(replay_buffer):
                replay_exit = cmd_session(replay_args)

            self.assertEqual(replay_exit, 0)
            replay_output = replay_buffer.getvalue()
            self.assertIn("# Mini Claw Session Replay", replay_output)
            self.assertIn("successful_turns: 1", replay_output)

            turn_show_args = Namespace(
                workspace=str(root),
                session_command="turn-show",
                session_ref="1",
                turn_ref="1",
                json=False,
            )
            turn_show_buffer = io.StringIO()
            with redirect_stdout(turn_show_buffer):
                turn_show_exit = cmd_session(turn_show_args)

            self.assertEqual(turn_show_exit, 0)
            turn_show_output = turn_show_buffer.getvalue()
            self.assertIn("## Turn 1", turn_show_output)
            self.assertIn("tool_calls=", turn_show_output)

            manager = SessionManager(root)
            session = manager.read_session("1")
            turns = manager.list_turns(session.session_id, limit=5)
            self.assertEqual(len(turns), 1)
            self.assertTrue(Path(turns[0].trace_path).exists())
            self.assertGreater(turns[0].trace_event_count, 0)

    def test_session_cli_supports_json_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            create_args = Namespace(
                workspace=str(root),
                session_command="create",
                name="json-session",
                json=True,
            )
            create_buffer = io.StringIO()
            with redirect_stdout(create_buffer):
                create_exit = cmd_session(create_args)

            self.assertEqual(create_exit, 0)
            created = json.loads(create_buffer.getvalue())
            self.assertEqual(created["name"], "json-session")

            run_args = Namespace(
                task="inspect this repository",
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session="1",
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_run(run_args), 0)

            replay_args = Namespace(
                workspace=str(root),
                session_command="replay",
                ref="1",
                turn_limit=10,
                json=True,
            )
            replay_buffer = io.StringIO()
            with redirect_stdout(replay_buffer):
                replay_exit = cmd_session(replay_args)

            self.assertEqual(replay_exit, 0)
            replay_payload = json.loads(replay_buffer.getvalue())
            self.assertEqual(replay_payload["successful_turns"], 1)
            self.assertEqual(replay_payload["total_turns"], 1)


if __name__ == "__main__":
    unittest.main()
