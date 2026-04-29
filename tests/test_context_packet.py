import unittest

from mini_claw.context.packet import ContextCompiler, ContextSection


class ContextPacketTest(unittest.TestCase):
    def test_context_compiler_truncates_low_priority_sections(self) -> None:
        compiler = ContextCompiler(max_chars=1200)
        packet = compiler.compile(
            objective="fix bug",
            sections=[
                ContextSection("System", "rules", priority=100),
                ContextSection("Task", "fix bug", priority=100),
                ContextSection("Large Low Priority", "x" * 5000, priority=10),
            ],
        )

        self.assertTrue(packet.budget_report.compressed)
        self.assertIn("Large Low Priority", packet.budget_report.truncated_sections)
        self.assertLessEqual(len(packet.render()), 1300)


if __name__ == "__main__":
    unittest.main()
