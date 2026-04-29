import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mini_claw.llm.openai_compatible import OpenAICompatibleClient


class OpenAICompatibleClientTest(unittest.TestCase):
    def test_client_loads_local_workspace_config_when_env_missing(self) -> None:
        with TemporaryDirectory() as directory:
            workspace = Path(directory)
            config_dir = workspace / ".mini_claw"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "openai_compatible.local.json").write_text(
                (
                    "{\n"
                    '  "api_key": "local-test-key",\n'
                    '  "base_url": "https://example.test/v1"\n'
                    "}\n"
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                client = OpenAICompatibleClient(workspace=workspace)

            self.assertEqual(client.api_key, "local-test-key")
            self.assertEqual(client.base_url, "https://example.test/v1")


if __name__ == "__main__":
    unittest.main()
