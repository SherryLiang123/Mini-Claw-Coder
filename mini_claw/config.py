from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelConfig:
    provider: str = "mock"
    default_model: str = "mock-coder"
    planner_model: str = "mock-planner"
    coder_model: str = "mock-coder"
    reviewer_model: str = "mock-reviewer"
    summarizer_model: str = "mock-summarizer"
    max_retries: int = 2


@dataclass(frozen=True)
class RuntimeConfig:
    workspace: Path
    max_steps: int = 8
    command_timeout_seconds: int = 30
    max_context_chars: int = 24_000
    dry_run: bool = False


@dataclass(frozen=True)
class AppConfig:
    runtime: RuntimeConfig
    models: ModelConfig = ModelConfig()

