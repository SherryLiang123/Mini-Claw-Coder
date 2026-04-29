from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from mini_claw.memory.candidates import MemoryCandidate
from mini_claw.memory.lookup_plan import build_lookup_plan, summarize_lookup_queries
from mini_claw.safety.snapshot import FileSnapshot
from mini_claw.skills.patches import (
    parse_skill_patch_candidate_content,
    render_skill_patch_artifact,
)
from mini_claw.tools.base import ToolOutputHandle, ToolResult
from mini_claw.tracing.events import RuntimeEvent


class MemoryStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.project_memory_path = self.root / "project_memory.md"
        self.memory_candidates_path = self.root / "memory_candidates.jsonl"
        self.memory_candidate_decisions_path = self.root / "memory_candidate_decisions.jsonl"
        self.skill_patch_artifacts_path = self.root / "skill_patch_artifacts.jsonl"
        self.skill_patch_eval_results_path = self.root / "skill_patch_eval_results.jsonl"
        self.read_snapshots_path = self.root / "read_snapshots.jsonl"
        self.trace_path = self.root / "task_trace.jsonl"
        self.tool_output_dir = self.root / "tool_outputs"
        self.skill_patch_artifact_dir = self.root.parent / "skill_patches"

    def read_project_memory(
        self,
        query: str = "",
        max_chars: int = 6_000,
    ) -> str:
        if not self.project_memory_path.exists():
            return "(none)"
        content = self.project_memory_path.read_text(encoding="utf-8")
        if len(content) <= max_chars:
            return content
        return self._select_relevant_memory(content=content, query=query, max_chars=max_chars)

    def update_project_memory(self, content: str) -> None:
        self.project_memory_path.write_text(content, encoding="utf-8")

    def append_trace(self, event: dict[str, Any]) -> None:
        payload = {"ts": datetime.now(timezone.utc).isoformat(), **event}
        with self.trace_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def append_event(self, event: RuntimeEvent) -> None:
        with self.trace_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event.to_dict(), ensure_ascii=True) + "\n")

    def append_memory_candidate(self, candidate: MemoryCandidate) -> None:
        with self.memory_candidates_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(candidate.to_dict(), ensure_ascii=True) + "\n")

    def record_read_snapshot(
        self,
        rel_path: str,
        snapshot: FileSnapshot,
        source: str,
    ) -> dict[str, Any]:
        record = {
            "path": rel_path.replace("\\", "/"),
            "exists": snapshot.exists,
            "sha256": snapshot.sha256,
            "chars": len(snapshot.content or ""),
            "source": source,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.read_snapshots_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=True) + "\n")
        self.append_event(
            RuntimeEvent(
                "file_read_snapshot_recorded",
                {
                    "path": record["path"],
                    "exists": record["exists"],
                    "sha256": record["sha256"],
                    "source": source,
                },
            )
        )
        return record

    def latest_read_snapshots(self) -> dict[str, dict[str, Any]]:
        snapshots: dict[str, dict[str, Any]] = {}
        for record in self._read_jsonl(self.read_snapshots_path):
            rel_path = str(record.get("path", "")).replace("\\", "/")
            if rel_path:
                snapshots[rel_path] = record
        return snapshots

    def latest_read_snapshot(self, rel_path: str) -> dict[str, Any] | None:
        return self.latest_read_snapshots().get(rel_path.replace("\\", "/"))

    def store_tool_result(
        self,
        tool: str,
        args: dict[str, Any],
        result: ToolResult,
        task: str = "",
        preview_chars: int = 1_600,
        max_stored_chars: int = 40_000,
    ) -> ToolOutputHandle:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        output_id = f"tool-{stamp}-{uuid4().hex[:8]}"
        raw_output = result.output or ""
        stored_output, store_truncated = self._truncate_with_marker(
            raw_output,
            max_stored_chars,
            marker="...[tool output truncated before persistence]...",
        )
        preview, truncated = self._truncate_with_marker(
            stored_output,
            preview_chars,
            marker="...[tool output preview truncated]...",
        )
        lookup_plan = build_lookup_plan(
            output=stored_output,
            task=task,
            tool=tool,
            args=args,
        )
        handle = ToolOutputHandle(
            output_id=output_id,
            tool=tool,
            ok=result.ok,
            preview=preview,
            lookup_hint=f"python -m mini_claw tool-output show {output_id}",
            lookup_queries=summarize_lookup_queries(lookup_plan),
            output_chars=len(raw_output),
            stored_output_chars=len(stored_output),
            truncated=truncated,
            store_truncated=store_truncated,
            modified_files=list(result.modified_files),
            metadata=dict(result.metadata),
        )
        payload = {
            "output_id": output_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "ok": result.ok,
            "args": args,
            "output": stored_output,
            "preview": preview,
            "lookup_hint": handle.lookup_hint,
            "output_chars": len(raw_output),
            "stored_output_chars": len(stored_output),
            "preview_chars": len(preview),
            "truncated": truncated,
            "store_truncated": store_truncated,
            "lookup_plan": lookup_plan,
            "modified_files": list(result.modified_files),
            "metadata": dict(result.metadata),
        }
        self.tool_output_dir.mkdir(parents=True, exist_ok=True)
        path = self.tool_output_dir / f"{output_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        return handle

    def list_tool_outputs(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.tool_output_dir.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(self.tool_output_dir.glob("*.json"), reverse=True):
            records.append(json.loads(path.read_text(encoding="utf-8")))
            if len(records) >= limit:
                break
        return records

    def read_tool_output(self, ref: str) -> dict[str, Any]:
        if ref == "latest":
            records = self.list_tool_outputs(limit=1)
            if not records:
                raise ValueError("No stored tool outputs.")
            return records[0]
        if ref == "latest_truncated":
            for record in self.list_tool_outputs(limit=100):
                if record.get("truncated") or record.get("store_truncated"):
                    return record
            raise ValueError("No truncated tool outputs found.")
        if ref.isdigit():
            index = int(ref)
            records = self.list_tool_outputs(limit=max(index, 20))
            if index < 1 or index > len(records):
                raise ValueError(f"Tool output index out of range: {ref}")
            return records[index - 1]
        path = self.tool_output_dir / f"{ref}.json"
        if not path.exists():
            raise ValueError(f"Unknown tool output: {ref}")
        return json.loads(path.read_text(encoding="utf-8"))

    def read_memory_candidates(
        self,
        kind_filter: str = "",
        status_filter: str = "",
        query: str = "",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        decisions = self._latest_candidate_decisions()
        artifacts = self._latest_skill_patch_artifacts_by_candidate()
        candidates: list[dict[str, Any]] = []
        for index, candidate in enumerate(self._read_jsonl(self.memory_candidates_path), start=1):
            candidate_id = str(candidate.get("candidate_id") or f"legacy-{index}")
            decision = decisions.get(candidate_id, {})
            artifact = artifacts.get(candidate_id, {})
            enriched = {
                **candidate,
                "candidate_id": candidate_id,
                "status": decision.get("action", "pending"),
                "decision_reason": decision.get("reason", ""),
                "decision_at": decision.get("created_at", ""),
                "artifact_id": artifact.get("artifact_id", ""),
                "artifact_path": artifact.get("artifact_path", ""),
                "artifact_created_at": artifact.get("created_at", ""),
                "target_skill": artifact.get("target_skill", ""),
                "skill_path": artifact.get("skill_path", ""),
            }
            candidates.append(enriched)
        if kind_filter:
            candidates = [
                candidate
                for candidate in candidates
                if str(candidate.get("kind", "")) == kind_filter
            ]
        if status_filter:
            candidates = [
                candidate
                for candidate in candidates
                if str(candidate.get("status", "")) == status_filter
            ]
        if query.strip():
            scored: list[tuple[int, int, dict[str, Any]]] = []
            for index, candidate in enumerate(candidates):
                score = self._score_candidate_relevance(candidate, query)
                if score > 0:
                    scored.append((score, index, candidate))
            candidates = [
                candidate for _, _, candidate in sorted(scored, reverse=True)
            ]
        if limit is not None:
            candidates = candidates[:limit]
        return candidates

    def read_skill_patch_artifacts(
        self,
        query: str = "",
        limit: int | None = 20,
    ) -> list[dict[str, Any]]:
        artifacts = self._read_jsonl(self.skill_patch_artifacts_path)
        latest_eval = self._latest_skill_patch_eval_results_by_artifact()
        artifacts = [
            {
                **artifact,
                "eval_status": latest_eval.get(str(artifact.get("artifact_id", "")), {}).get("status", ""),
                "eval_command": latest_eval.get(str(artifact.get("artifact_id", "")), {}).get("command", ""),
                "eval_exit_code": latest_eval.get(str(artifact.get("artifact_id", "")), {}).get("exit_code", ""),
                "eval_created_at": latest_eval.get(str(artifact.get("artifact_id", "")), {}).get("created_at", ""),
            }
            for artifact in artifacts
        ]
        if query.strip():
            scored: list[tuple[int, int, dict[str, Any]]] = []
            for index, artifact in enumerate(artifacts):
                score = self._score_skill_patch_artifact_relevance(artifact, query)
                if score > 0:
                    scored.append((score, index, artifact))
            artifacts = [artifact for _, _, artifact in sorted(scored, reverse=True)]
        else:
            artifacts = list(reversed(artifacts))
        if limit is not None:
            artifacts = artifacts[:limit]
        return artifacts

    def read_skill_patch_artifact(self, ref: str) -> dict[str, Any]:
        records = self.read_skill_patch_artifacts(limit=None)
        if not records:
            raise ValueError("No skill patch artifacts.")
        if ref.isdigit():
            index = int(ref)
            if index < 1 or index > len(records):
                raise ValueError(f"Skill patch artifact index out of range: {ref}")
            return self._hydrate_skill_patch_artifact_content(records[index - 1])
        for record in records:
            if record.get("artifact_id") == ref or record.get("candidate_id") == ref:
                return self._hydrate_skill_patch_artifact_content(record)
        raise ValueError(f"Unknown skill patch artifact: {ref}")

    def record_skill_patch_eval_result(
        self,
        ref: str,
        command: str,
        ok: bool,
        exit_code: int,
        output: str,
    ) -> dict[str, Any]:
        artifact = self.read_skill_patch_artifact(ref)
        created_at = datetime.now(timezone.utc).isoformat()
        eval_id = f"skill-patch-eval-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
        stored_output, output_truncated = self._truncate_with_marker(
            output,
            20_000,
            marker="...[skill patch eval output truncated]...",
        )
        record = {
            "eval_id": eval_id,
            "artifact_id": artifact.get("artifact_id", ""),
            "candidate_id": artifact.get("candidate_id", ""),
            "created_at": created_at,
            "command": command,
            "status": "passed" if ok else "failed",
            "ok": ok,
            "exit_code": exit_code,
            "output": stored_output,
            "output_truncated": output_truncated,
        }
        with self.skill_patch_eval_results_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=True) + "\n")
        self._append_skill_patch_eval_to_artifact(artifact, record)
        self.append_event(
            RuntimeEvent(
                "skill_patch_eval_recorded",
                {
                    "eval_id": eval_id,
                    "artifact_id": artifact.get("artifact_id", ""),
                    "candidate_id": artifact.get("candidate_id", ""),
                    "status": record["status"],
                    "exit_code": exit_code,
                    "command": command,
                },
            )
        )
        return record

    def read_evidence_strategies(
        self,
        query: str = "",
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        candidates = self.read_memory_candidates(
            kind_filter="evidence_lookup_strategy",
            status_filter="promoted",
            query=query,
        )
        if not query.strip():
            candidates = list(reversed(candidates))
        return candidates[:limit]

    def promote_memory_candidate(self, ref: str, reason: str = "manual promote") -> dict[str, Any]:
        candidate = self._resolve_memory_candidate(ref)
        if candidate["status"] != "pending":
            raise ValueError(
                f"Candidate {candidate['candidate_id']} is already {candidate['status']}."
            )
        if candidate.get("kind") == "skill_patch_candidate":
            self._materialize_skill_patch_artifact(candidate, reason)
        self._append_project_memory_from_candidate(candidate, reason)
        self._append_candidate_decision(candidate, action="promoted", reason=reason)
        return self._resolve_memory_candidate(str(candidate["candidate_id"]))

    def reject_memory_candidate(self, ref: str, reason: str = "manual reject") -> dict[str, Any]:
        candidate = self._resolve_memory_candidate(ref)
        if candidate["status"] != "pending":
            raise ValueError(
                f"Candidate {candidate['candidate_id']} is already {candidate['status']}."
            )
        self._append_candidate_decision(candidate, action="rejected", reason=reason)
        return self._resolve_memory_candidate(str(candidate["candidate_id"]))

    def _resolve_memory_candidate(self, ref: str) -> dict[str, Any]:
        candidates = self.read_memory_candidates()
        if ref.isdigit():
            index = int(ref)
            if index < 1 or index > len(candidates):
                raise ValueError(f"Candidate index out of range: {ref}")
            return candidates[index - 1]
        for candidate in candidates:
            if candidate.get("candidate_id") == ref:
                return candidate
        raise ValueError(f"Unknown memory candidate: {ref}")

    def _append_candidate_decision(
        self,
        candidate: dict[str, Any],
        action: str,
        reason: str,
    ) -> None:
        payload = {
            "candidate_id": candidate["candidate_id"],
            "action": action,
            "reason": reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "memory_cli",
        }
        with self.memory_candidate_decisions_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=True) + "\n")
        self.append_event(
            RuntimeEvent(
                "memory_candidate_decision",
                {
                    "candidate_id": candidate["candidate_id"],
                    "action": action,
                    "reason": reason,
                },
            )
        )

    def _latest_candidate_decisions(self) -> dict[str, dict[str, Any]]:
        decisions: dict[str, dict[str, Any]] = {}
        for decision in self._read_jsonl(self.memory_candidate_decisions_path):
            candidate_id = str(decision.get("candidate_id", ""))
            if candidate_id:
                decisions[candidate_id] = decision
        return decisions

    def _latest_skill_patch_artifacts_by_candidate(self) -> dict[str, dict[str, Any]]:
        artifacts: dict[str, dict[str, Any]] = {}
        for artifact in self._read_jsonl(self.skill_patch_artifacts_path):
            candidate_id = str(artifact.get("candidate_id", "")).strip()
            if candidate_id:
                artifacts[candidate_id] = artifact
        return artifacts

    def _latest_skill_patch_eval_results_by_artifact(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for result in self._read_jsonl(self.skill_patch_eval_results_path):
            artifact_id = str(result.get("artifact_id", "")).strip()
            if artifact_id:
                results[artifact_id] = result
        return results

    def _append_project_memory_from_candidate(
        self,
        candidate: dict[str, Any],
        reason: str,
    ) -> None:
        if candidate.get("kind") in {"evidence_lookup_strategy", "skill_patch_candidate"}:
            return
        existing = ""
        if self.project_memory_path.exists():
            existing = self.project_memory_path.read_text(encoding="utf-8").rstrip()
        section = "\n".join(
            [
                "## Promoted Memory",
                f"- candidate_id: {candidate['candidate_id']}",
                f"- kind: {candidate.get('kind', '')}",
                f"- source: {candidate.get('source', '')}",
                f"- confidence: {candidate.get('confidence', '')}",
                f"- promote_reason: {reason}",
                f"- evidence: {candidate.get('evidence', '')}",
                "",
                str(candidate.get("content", "")).strip(),
            ]
        )
        content = section if not existing else existing + "\n\n" + section
        self.project_memory_path.write_text(content + "\n", encoding="utf-8")

    def _materialize_skill_patch_artifact(
        self,
        candidate: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc).isoformat()
        artifact_id = f"skill-patch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
        artifact_path = self.skill_patch_artifact_dir / f"{artifact_id}.md"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_content = render_skill_patch_artifact(
            artifact_id=artifact_id,
            candidate=candidate,
            promote_reason=reason,
            created_at=created_at,
            artifact_path=artifact_path,
        )
        artifact_path.write_text(artifact_content, encoding="utf-8")

        proposal = parse_skill_patch_candidate_content(str(candidate.get("content", "")))
        record = {
            "artifact_id": artifact_id,
            "candidate_id": candidate.get("candidate_id", ""),
            "created_at": created_at,
            "promote_reason": reason,
            "artifact_path": str(artifact_path),
            "target_skill": proposal.target_skill,
            "skill_path": proposal.skill_path,
            "source": candidate.get("source", ""),
            "confidence": candidate.get("confidence", ""),
            "content": artifact_content,
        }
        with self.skill_patch_artifacts_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=True) + "\n")

        self.append_event(
            RuntimeEvent(
                "skill_patch_artifact_created",
                {
                    "artifact_id": artifact_id,
                    "candidate_id": candidate.get("candidate_id", ""),
                    "target_skill": proposal.target_skill,
                    "skill_path": proposal.skill_path,
                    "artifact_path": str(artifact_path),
                },
            )
        )
        return record

    def _hydrate_skill_patch_artifact_content(self, artifact: dict[str, Any]) -> dict[str, Any]:
        artifact_path = Path(str(artifact.get("artifact_path", "")))
        if artifact_path.exists():
            return {**artifact, "content": artifact_path.read_text(encoding="utf-8")}
        return artifact

    def _append_skill_patch_eval_to_artifact(
        self,
        artifact: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        artifact_path = Path(str(artifact.get("artifact_path", "")))
        if not artifact_path.exists():
            return
        section = "\n".join(
            [
                "",
                "## Eval Gate Result",
                f"- eval_id: {result.get('eval_id', '')}",
                f"- created_at: {result.get('created_at', '')}",
                f"- status: {result.get('status', '')}",
                f"- command: {result.get('command', '')}",
                f"- exit_code: {result.get('exit_code', '')}",
                f"- output_truncated: {result.get('output_truncated', False)}",
                "",
                "```text",
                str(result.get("output", "")).rstrip(),
                "```",
                "",
            ]
        )
        with artifact_path.open("a", encoding="utf-8") as file:
            file.write(section)

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _select_relevant_memory(self, content: str, query: str, max_chars: int) -> str:
        sections = self._split_markdown_sections(content)
        if len(sections) <= 1:
            return self._head_tail(content, max_chars)

        query_terms = {
            token.lower()
            for token in query.replace("_", " ").replace("-", " ").split()
            if len(token) >= 3
        }
        scored: list[tuple[int, int, str]] = []
        for index, section in enumerate(sections):
            lower = section.lower()
            score = sum(1 for term in query_terms if term in lower)
            if index == 0:
                score += 2
            scored.append((score, -index, section))

        selected: list[str] = []
        used = 0
        for _, _, section in sorted(scored, reverse=True):
            if used + len(section) + 2 > max_chars:
                continue
            selected.append(section)
            used += len(section) + 2
        if not selected:
            return self._head_tail(content, max_chars)

        header = (
            "Memory retrieval: selected relevant project-memory sections "
            f"under {max_chars} chars.\n\n"
        )
        return header + "\n\n".join(selected)

    def _split_markdown_sections(self, content: str) -> list[str]:
        sections: list[str] = []
        current: list[str] = []
        for line in content.splitlines():
            if line.startswith("## ") and current:
                sections.append("\n".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current).strip())
        return [section for section in sections if section]

    def _head_tail(
        self,
        content: str,
        max_chars: int,
        marker: str = "...[project memory truncated by budget]...",
    ) -> str:
        if len(content) <= max_chars:
            return content
        half = max(1, max_chars // 2)
        return content[:half] + "\n\n" + marker + "\n\n" + content[-half:]

    def _truncate_with_marker(
        self,
        content: str,
        max_chars: int,
        marker: str,
    ) -> tuple[str, bool]:
        if len(content) <= max_chars:
            return content, False
        return self._head_tail(content, max_chars, marker=marker), True

    def _score_candidate_relevance(self, candidate: dict[str, Any], query: str) -> int:
        haystacks = [
            str(candidate.get("kind", "")),
            str(candidate.get("source", "")),
            str(candidate.get("content", "")),
            str(candidate.get("evidence", "")),
            " ".join(str(tag) for tag in candidate.get("tags", [])),
        ]
        return self._score_text_relevance(query=query, haystacks=haystacks)

    def _score_skill_patch_artifact_relevance(self, artifact: dict[str, Any], query: str) -> int:
        haystacks = [
            str(artifact.get("candidate_id", "")),
            str(artifact.get("target_skill", "")),
            str(artifact.get("skill_path", "")),
            str(artifact.get("content", "")),
        ]
        return self._score_text_relevance(query=query, haystacks=haystacks)

    def _score_text_relevance(self, query: str, haystacks: list[str]) -> int:
        query_terms = {
            token.lower()
            for token in query.replace("_", " ").replace("-", " ").split()
            if len(token) >= 3
        }
        if not query_terms:
            return 0
        merged = "\n".join(haystacks).lower()
        return sum(1 for term in query_terms if term in merged)
