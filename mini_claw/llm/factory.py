from __future__ import annotations

from pathlib import Path

from mini_claw.llm.base import ModelClient
from mini_claw.llm.mock import MockModelClient
from mini_claw.llm.openai_compatible import OpenAICompatibleClient


def create_model_client(provider: str, workspace: Path | None = None) -> ModelClient:
    if provider == "mock":
        return MockModelClient()
    if provider == "openai-compatible":
        return OpenAICompatibleClient(workspace=workspace)
    raise ValueError(f"Unknown model provider: {provider}")
