import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.agent.state import AgentResult
from mini_claw.sessions.store import SessionManager


class SessionManagerTest(unittest.TestCase):
    def test_session_create_complete_turn_and_build_context(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manager = SessionManager(root)

            session = manager.create(name="repo-debug")
            turn = manager.begin_turn(session.session_id, "inspect repository state")
            completed = manager.complete_turn(
                session.session_id,
                turn.turn_id,
                result=AgentResult(
                    success=True,
                    final_answer="Repository inspected and ready for the next patch.",
                    steps=[],
                    modified_files=["README.md"],
                ),
                trace_lines=[
                    '{"event":"task_started","payload":{"task":"inspect repository state"}}\n',
                    '{"event":"task_finished","payload":{"success":true}}\n',
                ],
            )

            self.assertTrue(Path(completed.trace_path).exists())
            listed = manager.list_sessions(limit=10)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].turn_count, 1)
            context = manager.build_context(session.session_id, max_turns=3, max_chars=1000)
            self.assertIn("repo-debug", context)
            self.assertIn("modified_paths: README.md", context)
            self.assertIn("inspect repository state", context)

    def test_recent_modified_paths_prefers_latest_turn_and_merge_back_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manager = SessionManager(root)
            session = manager.create(name="recent-paths")

            turn1 = manager.begin_turn(session.session_id, "create first artifact")
            manager.complete_turn(
                session.session_id,
                turn1.turn_id,
                result=AgentResult(
                    success=True,
                    final_answer="Created first file.",
                    steps=[],
                    modified_files=["first.py"],
                ),
                trace_lines=[],
            )

            turn2 = manager.begin_turn(session.session_id, "create folder")
            manager.complete_turn(
                session.session_id,
                turn2.turn_id,
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

            recent = manager.recent_modified_paths(session.session_id, max_turns=3, limit=5)

            self.assertEqual(recent[0], "cheshi")
            self.assertIn("first.py", recent)


if __name__ == "__main__":
    unittest.main()
