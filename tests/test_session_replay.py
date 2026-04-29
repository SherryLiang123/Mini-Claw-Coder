import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.agent.state import AgentResult
from mini_claw.sessions.replay import replay_session, replay_session_turn
from mini_claw.sessions.store import SessionManager


class SessionReplayTest(unittest.TestCase):
    def test_replay_session_aggregates_completed_turns(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manager = SessionManager(root)
            session = manager.create(name="aggregate-demo")

            turn1 = manager.begin_turn(session.session_id, "inspect repository")
            manager.complete_turn(
                session.session_id,
                turn1.turn_id,
                result=AgentResult(
                    success=True,
                    final_answer="inspection complete",
                    steps=[],
                    modified_files=["README.md"],
                ),
                trace_lines=[
                    '{"event":"task_started","payload":{"task":"inspect repository"}}\n',
                    '{"event":"context_build","payload":{"route_reason":"initial_planning"}}\n',
                    '{"event":"tool_call","payload":{"tool":"shell","ok":true,"metadata":{}}}\n',
                    '{"event":"task_finished","payload":{"success":true}}\n',
                ],
            )

            turn2 = manager.begin_turn(session.session_id, "fix import error")
            manager.complete_turn(
                session.session_id,
                turn2.turn_id,
                result=AgentResult(
                    success=False,
                    final_answer="stopped before patch",
                    steps=[],
                    modified_files=["app.py"],
                    failure_report={"root_cause": "PATCH_CONFLICT"},
                ),
                trace_lines=[
                    '{"event":"task_started","payload":{"task":"fix import error"}}\n',
                    '{"event":"context_build","payload":{"route_reason":"failure_recovery"}}\n',
                    '{"event":"tool_call","payload":{"tool":"apply_patch","ok":false,"metadata":{}}}\n',
                    '{"event":"lookup_policy_blocked","payload":{"attempted_tool":"shell"}}\n',
                    '{"event":"task_finished","payload":{"success":false,"failure_report":{"root_cause":"PATCH_CONFLICT","suggested_action":"re-read file"}}}\n',
                ],
            )

            report = replay_session(manager, session.session_id, turn_limit=10)

            self.assertEqual(report.total_turns, 2)
            self.assertEqual(report.completed_turns, 2)
            self.assertEqual(report.successful_turns, 1)
            self.assertEqual(report.failed_turns, 1)
            self.assertEqual(report.total_events, 9)
            self.assertEqual(report.tool_calls, 2)
            self.assertEqual(report.failed_tool_calls, 1)
            self.assertEqual(report.lookup_policy_blocks, 1)
            self.assertEqual(report.route_reason_counts, {"failure_recovery": 1, "initial_planning": 1})
            self.assertEqual(report.failure_root_causes, {"PATCH_CONFLICT": 1})
            self.assertEqual(report.distinct_modified_files, ["README.md", "app.py"])

            turn_report = replay_session_turn(manager, session.session_id, "1")
            self.assertEqual(turn_report.turn_index, 2)
            self.assertFalse(turn_report.success)
            self.assertEqual(turn_report.failure_root_cause, "PATCH_CONFLICT")
            self.assertIsNotNone(turn_report.replay)
            self.assertEqual(turn_report.replay.lookup_policy_blocks, 1)


if __name__ == "__main__":
    unittest.main()
