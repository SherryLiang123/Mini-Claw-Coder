import io
import sys
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.cli import cmd_background, cmd_todo
from mini_claw.task_graph.graph import TaskGraph, TaskNode


def _python_command(source: str) -> str:
    return f'"{sys.executable}" -c "{source}"'


class BackgroundCliTest(unittest.TestCase):
    def test_background_start_wait_and_task_show(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="run background verification"))
            graph.save(graph_path)

            start_args = Namespace(
                workspace=str(root),
                background_command="start",
                command=_python_command("import time; print('ASYNC_OK'); time.sleep(0.2)"),
                label="verify",
                task_id="task-1",
            )
            start_buffer = io.StringIO()
            with redirect_stdout(start_buffer):
                start_exit = cmd_background(start_args)

            self.assertEqual(start_exit, 0)
            start_output = start_buffer.getvalue()
            self.assertIn("started bg-", start_output)

            wait_args = Namespace(
                workspace=str(root),
                background_command="wait",
                ref="1",
                timeout=10.0,
                poll_interval=0.1,
                tail_chars=400,
            )
            wait_buffer = io.StringIO()
            with redirect_stdout(wait_buffer):
                wait_exit = cmd_background(wait_args)

            self.assertEqual(wait_exit, 0)
            wait_output = wait_buffer.getvalue()
            self.assertIn("status: succeeded", wait_output)
            self.assertIn("ASYNC_OK", wait_output)

            show_args = Namespace(
                workspace=str(root),
                todo_command="show",
                task_id="task-1",
            )
            show_buffer = io.StringIO()
            with redirect_stdout(show_buffer):
                show_exit = cmd_todo(show_args)

            self.assertEqual(show_exit, 0)
            task_output = show_buffer.getvalue()
            self.assertIn("background_runs: bg-", task_output)
            self.assertIn("background run started", task_output)

    def test_todo_note_appends_timestamped_note(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="annotate task"))
            graph.save(graph_path)

            note_args = Namespace(
                workspace=str(root),
                todo_command="note",
                task_id="task-1",
                note="remember to re-run tests",
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_todo(note_args)

            self.assertEqual(exit_code, 0)
            loaded = TaskGraph.load(graph_path)
            self.assertIn("remember to re-run tests", loaded.nodes["task-1"].notes)


if __name__ == "__main__":
    unittest.main()
