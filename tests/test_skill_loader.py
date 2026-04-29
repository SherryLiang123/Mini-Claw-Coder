import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.skills.loader import SkillLoader, load_skill, select_relevant_skills


class SkillLoaderTest(unittest.TestCase):
    def test_load_skill_parses_front_matter_contract(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / "repo"
            skill_dir.mkdir()
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text(
                """---
name: repo-onboarding
description: Inspect repositories.
triggers:
  - inspect
  - repository
allowed_tools: [shell]
forbidden_paths:
  - .git
verification:
  - cite evidence
---

# Repo Onboarding

Read files carefully.
""",
                encoding="utf-8",
            )

            skill = load_skill(skill_path)

            self.assertEqual(skill.name, "repo-onboarding")
            self.assertIn("inspect", skill.contract.triggers)
            self.assertEqual(skill.contract.allowed_tools, ["shell"])
            self.assertIn(".git", skill.contract.forbidden_paths)
            self.assertNotIn("---", skill.body)

    def test_loader_selects_relevant_skills(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "repo").mkdir()
            (root / "repo" / "SKILL.md").write_text(
                """---
name: repo-onboarding
description: inspect repository
triggers: [inspect, repository]
---
Repo instructions.
""",
                encoding="utf-8",
            )
            (root / "tests").mkdir()
            (root / "tests" / "SKILL.md").write_text(
                """---
name: test-debugging
description: fix failing tests
triggers: [pytest, unittest, test]
---
Test instructions.
""",
                encoding="utf-8",
            )

            skills = SkillLoader([root]).load()
            selected = select_relevant_skills(skills, query="fix pytest failure", limit=1)

            self.assertEqual(selected[0].name, "test-debugging")


if __name__ == "__main__":
    unittest.main()

