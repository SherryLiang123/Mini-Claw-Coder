import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.task_graph.graph import TaskGraph, TaskNode


class TaskGraphTest(unittest.TestCase):
    def test_ready_nodes_respect_dependencies(self) -> None:
        graph = TaskGraph()
        graph.add(TaskNode(task_id="a", objective="first"))
        graph.add(TaskNode(task_id="b", objective="second", dependencies=["a"]))

        self.assertEqual([node.task_id for node in graph.ready()], ["a"])

        graph.set_status("a", "done")

        self.assertEqual([node.task_id for node in graph.ready()], ["b"])

    def test_graph_save_and_load(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "task_graph.json"
            graph = TaskGraph()
            graph.add(
                TaskNode(
                    task_id="a",
                    objective="first",
                    verification_command="python -m test",
                    workspace_path=".mini_claw/task_workspaces/a",
                    background_run_ids=["bg-1"],
                    notes="[2026-01-01T00:00:00+00:00] remembered detail",
                )
            )
            graph.save(path)

            loaded = TaskGraph.load(path)

            self.assertEqual(loaded.nodes["a"].objective, "first")
            self.assertEqual(loaded.nodes["a"].verification_command, "python -m test")
            self.assertEqual(loaded.nodes["a"].workspace_path, ".mini_claw/task_workspaces/a")
            self.assertEqual(loaded.nodes["a"].background_run_ids, ["bg-1"])
            self.assertIn("remembered detail", loaded.nodes["a"].notes)

    def test_attach_workspace_updates_node(self) -> None:
        graph = TaskGraph()
        graph.add(TaskNode(task_id="a", objective="first"))

        graph.attach_workspace("a", ".mini_claw/task_workspaces/a")

        self.assertEqual(graph.nodes["a"].workspace_path, ".mini_claw/task_workspaces/a")

    def test_attach_background_run_and_append_note(self) -> None:
        graph = TaskGraph()
        graph.add(TaskNode(task_id="a", objective="first"))

        graph.attach_background_run("a", "bg-1")
        graph.attach_background_run("a", "bg-1")
        graph.append_note("a", "watch pytest output", created_at="2026-01-01T00:00:00+00:00")

        self.assertEqual(graph.nodes["a"].background_run_ids, ["bg-1"])
        self.assertIn("watch pytest output", graph.nodes["a"].notes)


if __name__ == "__main__":
    unittest.main()
