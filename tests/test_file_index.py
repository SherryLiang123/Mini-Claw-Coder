import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.context.file_index import build_file_index, render_file_index


class FileIndexTest(unittest.TestCase):
    def test_file_index_extracts_symbols_and_preview(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text(
                "class Service:\n    pass\n\ndef greet():\n    return 'hi'\n",
                encoding="utf-8",
            )
            (root / ".mini_claw").mkdir()
            (root / ".mini_claw" / "hidden.py").write_text("def hidden(): pass\n", encoding="utf-8")

            entries = build_file_index(root, query="greet service", limit=10)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].path, "app.py")
            self.assertIn("Service", entries[0].symbols)
            self.assertIn("greet", entries[0].symbols)
            self.assertIn("class Service", entries[0].preview)
            self.assertGreater(entries[0].score, 0)

    def test_render_file_index_is_preview_not_full_content(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Title\n\nshort intro\n\nsecret full detail\n",
                encoding="utf-8",
            )

            rendered = render_file_index(root, query="title", preview_lines=1)

            self.assertIn("Progressive disclosure", rendered)
            self.assertIn("README.md", rendered)
            self.assertIn("Title", rendered)
            self.assertNotIn("secret full detail", rendered)

    def test_file_index_ignores_reference_roots_by_default(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text("def real_entry():\n    return True\n", encoding="utf-8")
            (root / ".external").mkdir()
            (root / ".external" / "reference.py").write_text(
                "def reference_only():\n    return False\n",
                encoding="utf-8",
            )
            (root / "sibling-project").mkdir()
            (root / "sibling-project" / "alt.py").write_text(
                "def sibling_project():\n    return False\n",
                encoding="utf-8",
            )

            entries = build_file_index(root, query="entry reference sibling", limit=10)
            indexed_paths = [entry.path for entry in entries]

            self.assertEqual(indexed_paths, ["main.py"])


if __name__ == "__main__":
    unittest.main()
