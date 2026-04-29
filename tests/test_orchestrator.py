import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.memory.store import MemoryStore
from mini_claw.task_graph.graph import TaskGraph, TaskNode
from mini_claw.task_graph.orchestrator import CoderRunResult, run_task_graph_orchestration
from mini_claw.task_graph.workspace import TaskWorkspaceManager


class TaskGraphOrchestratorTest(unittest.TestCase):
    def test_orchestrator_runs_tester_and_integrator_merge(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
            graph = TaskGraph()
            graph.add(
                TaskNode(
                    task_id="task-1",
                    objective="update app value",
                    verification_command="python -c \"raise SystemExit(0)\"",
                )
            )
            memory = MemoryStore(root / ".mini_claw" / "memory")
            manager = TaskWorkspaceManager(root)
            task_workspace = manager.create("task-1")
            graph.attach_workspace("task-1", task_workspace.path)
            (Path(task_workspace.path) / "app.py").write_text(
                "VALUE = 'new'\n",
                encoding="utf-8",
            )

            report = run_task_graph_orchestration(
                workspace=root,
                graph=graph,
                workspace_manager=manager,
                memory=memory,
            )

            self.assertEqual(report.processed, 1)
            self.assertEqual(report.passed, 1)
            self.assertEqual(graph.nodes["task-1"].status, "done")
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 'new'\n")
            self.assertIn("[integrator] ok", report.to_markdown())

    def test_orchestrator_stops_on_tester_failure(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
            graph = TaskGraph()
            graph.add(
                TaskNode(
                    task_id="task-1",
                    objective="update app value",
                    verification_command="python -c \"raise SystemExit(2)\"",
                )
            )
            memory = MemoryStore(root / ".mini_claw" / "memory")
            manager = TaskWorkspaceManager(root)

            report = run_task_graph_orchestration(
                workspace=root,
                graph=graph,
                workspace_manager=manager,
                memory=memory,
            )

            self.assertEqual(report.failed, 1)
            self.assertEqual(graph.nodes["task-1"].status, "failed")
            self.assertIn("[tester] failed", report.to_markdown())
            self.assertNotIn("[integrator]", report.to_markdown())

    def test_orchestrator_can_run_coder_agent_callback(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
            graph = TaskGraph()
            graph.add(
                TaskNode(
                    task_id="task-1",
                    objective="update app value",
                    verification_command="python -c \"raise SystemExit(0)\"",
                )
            )
            memory = MemoryStore(root / ".mini_claw" / "memory")
            manager = TaskWorkspaceManager(root)

            def coder_runner(node: TaskNode, task_workspace: Path) -> CoderRunResult:
                self.assertEqual(node.task_id, "task-1")
                (task_workspace / "app.py").write_text("VALUE = 'agent'\n", encoding="utf-8")
                return CoderRunResult(
                    ok=True,
                    detail="coder agent patched app.py",
                    modified_files=["app.py"],
                )

            report = run_task_graph_orchestration(
                workspace=root,
                graph=graph,
                workspace_manager=manager,
                memory=memory,
                coder_runner=coder_runner,
            )

            self.assertEqual(report.passed, 1)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 'agent'\n")
            markdown = report.to_markdown()
            self.assertIn("coder agent patched app.py", markdown)
            self.assertIn("modified_files=app.py", markdown)


if __name__ == "__main__":
    unittest.main()
