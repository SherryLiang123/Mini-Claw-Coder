from __future__ import annotations

from pathlib import Path

from mini_claw.agent.state import TaskState
from mini_claw.context.file_index import render_file_index
from mini_claw.context.packet import ContextCompiler, ContextPacket, ContextSection
from mini_claw.context.workspace import snapshot_tree
from mini_claw.memory.store import MemoryStore
from mini_claw.skills.loader import Skill, select_relevant_skills


class ContextManager:
    def __init__(
        self,
        workspace: Path,
        memory: MemoryStore,
        skills: list[Skill],
        max_chars: int,
    ) -> None:
        self.workspace = workspace
        self.memory = memory
        self.skills = skills
        self.max_chars = max_chars
        self.compiler = ContextCompiler(max_chars=max_chars)

    def build_prompt(self, system_prompt: str, state: TaskState) -> str:
        return self.build_packet(system_prompt, state).render()

    def build_packet(self, system_prompt: str, state: TaskState) -> ContextPacket:
        sections = [
            ContextSection("System Rules", system_prompt, priority=100),
            ContextSection("Task", state.task, priority=100),
            ContextSection("Session Context", state.session_context, priority=88),
            ContextSection("Workspace Tree", snapshot_tree(self.workspace), priority=70),
            ContextSection(
                "File Index Preview",
                render_file_index(
                    workspace=self.workspace,
                    query=state.task,
                    limit=40,
                    preview_lines=2,
                ),
                priority=80,
                disclosure="preview",
            ),
            ContextSection(
                "Project Memory",
                self.memory.read_project_memory(
                    query=state.task,
                    max_chars=max(1_000, self.max_chars // 5),
                ),
                priority=75,
            ),
            ContextSection(
                "Evidence Strategies",
                self._format_evidence_strategies(state.task),
                priority=74,
            ),
            ContextSection(
                "Working Summary",
                self._format_compact_summary(state),
                priority=84,
            ),
            ContextSection("Relevant Skills", self._format_skills(state.task), priority=65),
            ContextSection("Execution Trace", self._format_trace(state), priority=85),
        ]
        filtered = [section for section in sections if section.content.strip() and section.content.strip() != "(none)"]
        return self.compiler.compile(objective=state.task, sections=filtered)

    def _format_evidence_strategies(self, query: str) -> str:
        strategies = self.memory.read_evidence_strategies(
            query=query,
            limit=3,
        )
        if not strategies:
            return "(none)"
        blocks: list[str] = []
        for index, strategy in enumerate(strategies, start=1):
            blocks.append(
                "\n".join(
                    [
                        f"Strategy {index}",
                        f"candidate_id: {strategy.get('candidate_id', '')}",
                        f"confidence: {strategy.get('confidence', '')}",
                        "tags: "
                        + (
                            ", ".join(str(tag) for tag in strategy.get("tags", []))
                            or "(none)"
                        ),
                        str(strategy.get("content", "")).strip() or "(none)",
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _format_skills(self, query: str) -> str:
        if not self.skills:
            return "(none)"
        selected = select_relevant_skills(self.skills, query=query, limit=3)
        return "\n\n".join(skill.to_prompt() for skill in selected)

    def _format_compact_summary(self, state: TaskState) -> str:
        if not state.compact_summary.strip():
            return "(none)"
        return "\n".join(
            [
                f"Older steps compacted: {state.compacted_steps}",
                f"Compaction count: {state.compaction_count}",
                "",
                state.compact_summary.strip(),
            ]
        )

    def _format_trace(self, state: TaskState) -> str:
        if not state.steps:
            return "(no steps yet)"
        rows: list[str] = []
        recent_steps = state.steps[-4:] if state.compact_summary else state.steps[-6:]
        for step in recent_steps:
            rows.append(
                "\n".join(
                    [
                        f"Step {step.index} [{step.role}/{step.model}]",
                        f"Thought: {step.thought}",
                        f"Action: {step.action.tool if step.action else '(none)'}",
                        f"Observation: {(step.observation or '')[:1800]}",
                    ]
                )
            )
        return "\n\n".join(rows)
