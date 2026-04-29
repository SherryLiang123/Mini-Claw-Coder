from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from mini_claw.llm.base import ToolSpec


class OpenAICompatibleClient:
    """Tiny OpenAI-compatible chat completions client using the standard library."""

    def __init__(self, workspace: Path | None = None) -> None:
        local_config = self._load_local_config(workspace)
        self.api_key = (
            os.environ.get("MINI_CLAW_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or str(local_config.get("api_key", "")).strip()
        )
        self.base_url = (
            os.environ.get("MINI_CLAW_BASE_URL")
            or str(local_config.get("base_url", "")).strip()
            or "https://api.openai.com/v1"
        )
        if not self.api_key:
            raise RuntimeError("Set MINI_CLAW_API_KEY or OPENAI_API_KEY to use openai-compatible.")

    def complete(self, model: str, messages: list[dict[str, Any]]) -> str:
        payload = json.dumps({"model": model, "messages": messages, "temperature": 0.2}).encode()
        data = self._post(payload)
        return str(data["choices"][0]["message"]["content"])

    def complete_with_tools(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
    ) -> dict[str, Any]:
        payload = json.dumps(
            {
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                        },
                    }
                    for tool in tools
                ],
                "tool_choice": "auto",
            }
        ).encode()
        data = self._post(payload)
        message = data["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        content = self._stringify_message_content(message.get("content"))
        if tool_calls:
            parsed_calls: list[dict[str, Any]] = []
            for raw_call in tool_calls:
                function = raw_call.get("function", {})
                raw_arguments = function.get("arguments", "{}")
                try:
                    arguments = json.loads(raw_arguments) if raw_arguments else {}
                except json.JSONDecodeError:
                    arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}
                parsed_calls.append(
                    {
                        "id": str(raw_call.get("id", "")).strip(),
                        "tool": str(function.get("name", "")).strip(),
                        "args": arguments,
                    }
                )
            first_call = parsed_calls[0]
            return {
                "thought": content,
                "action": {
                    "tool": first_call["tool"],
                    "args": first_call["args"],
                },
                "tool_calls": parsed_calls,
                "final": None,
            }
        return {
            "thought": "",
            "action": None,
            "final": content,
        }

    def _post(self, payload: bytes) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenAI-compatible request failed: status={exc.code} body={body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI-compatible request failed: {exc}") from exc
        return data

    def _stringify_message_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
            return "\n".join(parts).strip()
        return str(content)

    def _load_local_config(self, workspace: Path | None) -> dict[str, Any]:
        candidates: list[Path] = []
        if workspace is not None:
            candidates.append((workspace / ".mini_claw" / "openai_compatible.local.json").resolve())
        candidates.append((Path.cwd() / ".mini_claw" / "openai_compatible.local.json").resolve())
        seen: set[Path] = set()
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Failed to read local OpenAI-compatible config: {path}: {exc}") from exc
            if isinstance(data, dict):
                return data
        return {}
