import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.background.jobs import BackgroundRunManager
from mini_claw.memory.store import MemoryStore


def _python_command(source: str) -> str:
    return f'"{sys.executable}" -c "{source}"'


class BackgroundRunManagerTest(unittest.TestCase):
    def test_background_run_persists_logs_and_trace(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            manager = BackgroundRunManager(root, memory=memory)

            command = _python_command(
                "import sys,time; print('BG_OK'); sys.stderr.write('BG_ERR\\n'); time.sleep(0.2)"
            )
            run = manager.start(command, label="smoke", task_id="task-1")
            finished = manager.wait(run.run_id, timeout_seconds=10.0, poll_interval=0.1)
            tails = manager.output_tail(run.run_id, max_chars=400)

            self.assertEqual(finished.status, "succeeded")
            self.assertEqual(finished.task_id, "task-1")
            self.assertIn("BG_OK", tails["stdout"])
            self.assertIn("BG_ERR", tails["stderr"])
            trace = memory.trace_path.read_text(encoding="utf-8")
            self.assertIn("background_run_requested", trace)
            self.assertIn("background_run_started", trace)
            self.assertIn("background_run_finished", trace)

    def test_background_run_records_failure_exit_code(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manager = BackgroundRunManager(root)

            command = _python_command("raise SystemExit(3)")
            run = manager.start(command, label="fails")
            finished = manager.wait(run.run_id, timeout_seconds=10.0, poll_interval=0.1)

            self.assertEqual(finished.status, "failed")
            self.assertEqual(finished.exit_code, 3)


if __name__ == "__main__":
    unittest.main()
