import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.evals.bench import compare_bench_routing_policies, run_bench_file


class EvalBenchTest(unittest.TestCase):
    def test_run_bench_file_collects_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            workspace = Path(directory)
            bench_path = workspace / "bench.json"
            bench_path.write_text(
                """
{
  "cases": [
    {
      "name": "patch_case",
      "task": "change value",
      "setup_files": {"app.py": "VALUE = 'old'\\n"},
      "scripted_actions": [
        {
          "thought": "patch",
          "action": {
            "tool": "apply_patch",
            "args": {
              "operations": [
                {
                  "op": "replace",
                  "path": "app.py",
                  "old": "old",
                  "new": "new"
                }
              ],
              "verify": ["python -c \\"import app; raise SystemExit(0 if app.VALUE == 'new' else 1)\\""]
            }
          },
          "final": null
        },
        {"thought": "done", "action": null, "final": "done"}
      ],
      "verification_commands": [
        "python -c \\"import app; raise SystemExit(0 if app.VALUE == 'new' else 1)\\""
      ]
    }
  ]
}
""".strip(),
                encoding="utf-8",
            )

            report = run_bench_file(bench_path, workspace=workspace)

            self.assertEqual(report.total, 1)
            self.assertEqual(report.passed, 1)
            self.assertEqual(report.results[0].tool_calls, 1)
            self.assertEqual(report.results[0].patch_transactions, 1)
            self.assertEqual(report.routing_policy, "signal-aware")

    def test_compare_bench_routing_policies_reports_route_reason_differences(self) -> None:
        with TemporaryDirectory() as directory:
            workspace = Path(directory)
            bench_path = workspace / "bench-routing.json"
            bench_path.write_text(
                """
{
  "cases": [
    {
      "name": "long_trace_case",
      "task": "inspect repository state over several steps",
      "setup_files": {},
      "scripted_actions": [
        {"thought": "step0", "action": {"tool": "shell", "args": {"command": "python -c \\"print('STEP0')\\""}}, "final": null},
        {"thought": "step1", "action": {"tool": "shell", "args": {"command": "python -c \\"print('STEP1')\\""}}, "final": null},
        {"thought": "step2", "action": {"tool": "shell", "args": {"command": "python -c \\"print('STEP2')\\""}}, "final": null},
        {"thought": "step3", "action": {"tool": "shell", "args": {"command": "python -c \\"print('STEP3')\\""}}, "final": null},
        {"thought": "step4", "action": {"tool": "shell", "args": {"command": "python -c \\"print('STEP4')\\""}}, "final": null},
        {"thought": "done", "action": null, "final": "done"}
      ],
      "verification_commands": []
    }
  ]
}
""".strip(),
                encoding="utf-8",
            )

            report = compare_bench_routing_policies(
                bench_path,
                workspace=workspace,
                policies=["basic", "signal-aware"],
            )

            self.assertEqual(report.total_cases, 1)
            self.assertEqual(len(report.summaries), 2)
            basic = next(summary for summary in report.summaries if summary.policy == "basic")
            signal = next(summary for summary in report.summaries if summary.policy == "signal-aware")
            self.assertNotIn("new_context_compaction", basic.route_reason_counts)
            self.assertIn("new_context_compaction", signal.route_reason_counts)


if __name__ == "__main__":
    unittest.main()
