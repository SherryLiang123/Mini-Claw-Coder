from __future__ import annotations

import json
from typing import Any

from mini_claw.agent.compaction import refresh_compact_summary
from mini_claw.agent.evidence import build_evidence_selection, summarize_evidence
from mini_claw.agent.guardrails import SkillGuardrail
from mini_claw.agent.prompts import SYSTEM_PROMPT, TOOL_CALLING_SYSTEM_PROMPT
from mini_claw.agent.state import AgentResult, AgentStep, TaskState, ToolCall
from mini_claw.agent.tool_output_policy import ToolOutputLookupPolicy
from mini_claw.config import AppConfig
from mini_claw.context.manager import ContextManager
from mini_claw.llm.base import ModelClient, NativeToolCallingClient
from mini_claw.memory.candidates import (
    build_evidence_strategy_candidate,
    build_success_memory_candidate,
)
from mini_claw.memory.store import MemoryStore
from mini_claw.reliability.failure import FailureReport, attribute_failure
from mini_claw.routing.router import ModelRouter
from mini_claw.skills.evolution import build_skill_patch_candidate
from mini_claw.skills.loader import Skill
from mini_claw.skills.loader import select_relevant_skills
from mini_claw.tools.base import Tool
from mini_claw.tools.specs import build_tool_specs
from mini_claw.tracing.events import RuntimeEvent


class AgentLoop:
    def __init__(
        self,
        config: AppConfig,
        client: ModelClient,
        router: ModelRouter,
        tools: dict[str, Tool],
        memory: MemoryStore,
        skills: list[Skill],
    ) -> None:
        self.config = config
        self.client = client
        self.router = router
        self.tools = tools
        self.memory = memory
        self.skills = skills
        self.guardrail = SkillGuardrail(skills)
        self.lookup_policy = ToolOutputLookupPolicy()
        self.tool_specs = build_tool_specs(list(tools))
        self.context = ContextManager(
            workspace=config.runtime.workspace,
            memory=memory,
            skills=skills,
            max_chars=config.runtime.max_context_chars,
        )

    def run(
        self,
        task: str,
        *,
        session_context: str = "",
        run_metadata: dict[str, Any] | None = None,
    ) -> AgentResult:
        metadata = dict(run_metadata or {})
        state = TaskState(task=task, session_context=session_context)
        self.memory.append_event(
            RuntimeEvent(
                "task_started",
                {
                    "task": task,
                    **metadata,
                },
            )
        )

        final = ""
        success = False
        failure_report: FailureReport | None = None
        evidence_summary: dict[str, Any] | None = None
        context_step = 0
        while len(state.steps) < self.config.runtime.max_steps:
            index = context_step
            context_step += 1
            route = self.router.select(state)
            role = route.role
            model = route.model
            packet = self.context.build_packet(
                self._system_prompt_for_route(route.role, route.guidance),
                state,
            )
            state.last_context_compressed = packet.budget_report.compressed
            state.last_context_used_chars = packet.budget_report.used_chars
            state.last_context_max_chars = packet.budget_report.max_chars
            prompt = packet.render()
            self.memory.append_event(
                RuntimeEvent(
                    "context_build",
                    {
                        "step": index,
                        "role": role,
                        "model": model,
                        "route_reason": route.reason,
                        "route_signals": route.signals,
                        "budget": packet.budget_report.to_dict(),
                    },
                )
            )
            native_result = self._run_native_cycle(
                state=state,
                context_step=index,
                role=role,
                model=model,
                prompt=prompt,
            )
            if native_result.get("used_native"):
                if native_result.get("final") is not None:
                    final = str(native_result["final"])
                    success = bool(native_result.get("success", False))
                    break
                if len(state.steps) >= self.config.runtime.max_steps:
                    break
                if native_result.get("progressed"):
                    continue

            text_result = self._run_text_step(
                state=state,
                context_step=index,
                role=role,
                model=model,
                prompt=prompt,
            )
            if text_result.get("final") is not None:
                final = str(text_result["final"])
                success = bool(text_result.get("success", False))
                break

        evidence_summary = summarize_evidence(state.evidence_history)
        if not success:
            failure_report = attribute_failure(state)
            finalization = self._attempt_forced_finalization(
                state=state,
                evidence_summary=evidence_summary,
                failure_report=failure_report,
            )
            if finalization is not None:
                final = finalization["final"]
                success = finalization["completed"]
                if success:
                    failure_report = None
            if not final:
                final = self._fallback_final(state, failure_report)
        elif self.config.models.provider != "mock":
            candidates = [
                build_success_memory_candidate(
                    task=state.task,
                    final_answer=final,
                    modified_files=sorted(state.modified_files),
                    evidence_summary=evidence_summary,
                )
            ]
            evidence_candidate = build_evidence_strategy_candidate(
                task=state.task,
                evidence_summary=evidence_summary,
            )
            if evidence_candidate is not None:
                candidates.append(evidence_candidate)
            relevant_skills = select_relevant_skills(self.skills, query=state.task, limit=1)
            if relevant_skills:
                skill_patch_candidate = build_skill_patch_candidate(
                    task=state.task,
                    evidence_summary=evidence_summary,
                    skill=relevant_skills[0],
                )
                if skill_patch_candidate is not None:
                    candidates.append(skill_patch_candidate)
                    self.memory.append_event(
                        RuntimeEvent(
                            "skill_patch_candidate_suggested",
                            {
                                "target_skill": relevant_skills[0].name,
                                "skill_path": str(relevant_skills[0].path),
                                "lookups": evidence_summary.get("lookups", 0),
                                "refinements": evidence_summary.get("refinements", 0),
                                "queries": evidence_summary.get("queries", []),
                            },
                        )
                    )
            for candidate in candidates:
                self.memory.append_memory_candidate(candidate)
                self.memory.append_event(
                    RuntimeEvent(
                        "memory_candidate_created",
                        {
                            "kind": candidate.kind,
                            "source": candidate.source,
                            "confidence": candidate.confidence,
                            "tags": candidate.tags,
                        },
                    )
                )

        self.memory.append_event(
            RuntimeEvent(
                "task_finished",
                {
                    "success": success,
                    "modified_files": sorted(state.modified_files),
                    "steps": len(state.steps),
                    "evidence_summary": evidence_summary if evidence_summary["lookups"] > 0 else None,
                    "failure_report": failure_report.to_dict() if failure_report else None,
                    **metadata,
                },
            )
        )
        return AgentResult(
            success=success,
            final_answer=final,
            steps=state.steps,
            modified_files=sorted(state.modified_files),
            failure_report=failure_report.to_dict() if failure_report else None,
        )

    def _parse_decision(self, raw: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    parsed = None
            else:
                parsed = None
        return self._normalize_decision(parsed)

    def _fallback_final(self, state: TaskState, failure_report: FailureReport) -> str:
        return (
            "Mini Claw-Coder stopped before reaching a final answer. "
            f"Steps: {len(state.steps)}. Last observation: {state.last_observation()[:500]}\n"
            f"{failure_report.to_markdown()}"
        )

    def _request_decision(
        self,
        *,
        state: TaskState,
        step: int,
        role: str,
        model: str,
        prompt: str,
    ) -> dict[str, Any]:
        raw = self.client.complete(model=model, messages=[{"role": "user", "content": prompt}])
        decision = self._parse_decision(raw)
        if self._decision_is_actionable(decision):
            return decision

        self.memory.append_event(
            RuntimeEvent(
                "decision_repair_attempted",
                {
                    "step": step,
                    "role": role,
                    "model": model,
                    "raw_excerpt": self._compact_text(raw, 400),
                },
            )
        )
        repaired_raw = self.client.complete(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": self._build_decision_repair_prompt(
                        state=state,
                        role=role,
                        raw_output=raw,
                    ),
                }
            ],
        )
        repaired = self._parse_decision(repaired_raw)
        if self._decision_is_actionable(repaired):
            self.memory.append_event(
                RuntimeEvent(
                    "decision_repaired",
                    {
                        "step": step,
                        "role": role,
                        "model": model,
                    },
                )
            )
            return repaired

        self.memory.append_event(
            RuntimeEvent(
                "decision_repair_failed",
                {
                    "step": step,
                    "role": role,
                    "model": model,
                    "raw_excerpt": self._compact_text(repaired_raw, 400),
                },
            )
        )
        return decision

    def _request_native_decision(
        self,
        *,
        step: int,
        role: str,
        model: str,
        messages: list[dict[str, Any]],
        native_round: int,
    ) -> dict[str, Any]:
        if not self._supports_native_tool_calling():
            return {"thought": "", "action": None, "final": None}

        self.memory.append_event(
            RuntimeEvent(
                "native_tool_calling_attempted",
                {
                    "step": step,
                    "role": role,
                    "model": model,
                    "tool_count": len(self.tool_specs),
                    "native_round": native_round,
                },
            )
        )
        client = self.client
        assert isinstance(client, NativeToolCallingClient)
        decision = self._normalize_decision(
            client.complete_with_tools(
                model=model,
                messages=messages,
                tools=self.tool_specs,
            )
        )
        self.memory.append_event(
            RuntimeEvent(
                "native_tool_calling_result",
                {
                    "step": step,
                    "role": role,
                    "model": model,
                    "native_round": native_round,
                    "tool": (
                        str(decision.get("action", {}).get("tool", "")).strip()
                        if isinstance(decision.get("action"), dict)
                        else ""
                    ),
                    "has_final": bool(
                        isinstance(decision.get("final"), str)
                        and str(decision.get("final", "")).strip()
                    ),
                },
            )
        )
        return decision

    def _run_text_step(
        self,
        *,
        state: TaskState,
        context_step: int,
        role: str,
        model: str,
        prompt: str,
    ) -> dict[str, Any]:
        decision = self._request_decision(
            state=state,
            step=context_step,
            role=role,
            model=model,
            prompt=prompt,
        )
        step = AgentStep(
            index=len(state.steps),
            role=role,
            model=model,
            thought=str(decision.get("thought", "")),
        )
        if decision.get("final"):
            final = str(decision["final"])
            self._record_step(state, step)
            return {
                "handled": True,
                "final": final,
                "success": self._decision_marks_completion(decision),
            }
        action = decision.get("action")
        if not self._is_valid_action(action):
            self._record_missing_action_step(
                state=state,
                context_step=context_step,
                role=role,
                model=model,
                step=step,
            )
            return {"handled": True, "final": None, "success": False}
        self._execute_action_step(
            state=state,
            context_step=context_step,
            role=role,
            model=model,
            step=step,
            action_payload=action,
        )
        return {"handled": True, "final": None, "success": False}

    def _run_native_cycle(
        self,
        *,
        state: TaskState,
        context_step: int,
        role: str,
        model: str,
        prompt: str,
    ) -> dict[str, Any]:
        if not self._supports_native_tool_calling():
            return {"used_native": False, "progressed": False, "final": None, "success": False}

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        native_round = 0
        progressed = False
        while len(state.steps) < self.config.runtime.max_steps:
            native_round += 1
            decision = self._request_native_decision(
                step=context_step,
                role=role,
                model=model,
                messages=messages,
                native_round=native_round,
            )
            if not self._decision_is_actionable(decision):
                if progressed:
                    self.memory.append_event(
                        RuntimeEvent(
                            "native_tool_calling_stalled",
                            {
                                "step": context_step,
                                "role": role,
                                "model": model,
                                "native_round": native_round,
                            },
                        )
                    )
                return {
                    "used_native": progressed,
                    "progressed": progressed,
                    "final": None,
                    "success": False,
                }

            thought = str(decision.get("thought", ""))
            if decision.get("final"):
                final_step = AgentStep(
                    index=len(state.steps),
                    role=role,
                    model=model,
                    thought=thought,
                )
                final = str(decision["final"])
                self._record_step(state, final_step)
                return {
                    "used_native": True,
                    "progressed": True,
                    "final": final,
                    "success": self._decision_marks_completion(decision),
                }

            tool_calls = self._decision_tool_calls(decision)
            if not tool_calls:
                return {
                    "used_native": progressed,
                    "progressed": progressed,
                    "final": None,
                    "success": False,
                }

            progressed = True
            messages.append(self._build_native_assistant_tool_message(thought, tool_calls))
            for call_index, tool_call in enumerate(tool_calls):
                step = AgentStep(
                    index=len(state.steps),
                    role=role,
                    model=model,
                    thought=thought if call_index == 0 else "Continue tool execution from the same native response.",
                )
                self._execute_action_step(
                    state=state,
                    context_step=context_step,
                    role=role,
                    model=model,
                    step=step,
                    action_payload=tool_call,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tool_call.get("id", "")).strip() or f"native-call-{len(state.steps)}",
                        "content": step.observation or "",
                    }
                )
                if len(state.steps) >= self.config.runtime.max_steps:
                    break

        return {
            "used_native": progressed,
            "progressed": progressed,
            "final": None,
            "success": False,
        }

    def _record_missing_action_step(
        self,
        *,
        state: TaskState,
        context_step: int,
        role: str,
        model: str,
        step: AgentStep,
    ) -> None:
        step.observation = "Model returned no action and no final answer."
        state.failure_count += 1
        self._record_step(state, step)
        self.memory.append_event(
            RuntimeEvent(
                "agent_step_failed",
                {
                    "step": context_step,
                    "reason": "missing_action",
                    "role": role,
                    "model": model,
                },
            )
        )

    def _execute_action_step(
        self,
        *,
        state: TaskState,
        context_step: int,
        role: str,
        model: str,
        step: AgentStep,
        action_payload: dict[str, Any],
    ) -> AgentStep:
        call = ToolCall(tool=str(action_payload.get("tool", "")), args=dict(action_payload.get("args", {})))
        step.action = call
        guardrail = self.guardrail.validate(state.task, call)
        if not guardrail.ok:
            step.observation = f"Skill guardrail blocked tool call: {guardrail.reason}"
            state.failure_count += 1
            self._record_step(state, step)
            self.memory.append_event(
                RuntimeEvent(
                    "agent_step_failed",
                    {
                        "step": context_step,
                        "reason": "skill_guardrail",
                        "tool": call.tool,
                        "role": role,
                        "model": model,
                        "active_skills": guardrail.active_skills,
                        "details": guardrail.reason,
                    },
                )
            )
            return step

        tool = self.tools.get(call.tool)
        if tool is None:
            step.observation = f"Unknown tool: {call.tool}"
            state.failure_count += 1
            self._record_step(state, step)
            self.memory.append_event(
                RuntimeEvent(
                    "agent_step_failed",
                    {
                        "step": context_step,
                        "reason": "unknown_tool",
                        "tool": call.tool,
                        "role": role,
                        "model": model,
                    },
                )
            )
            return step

        lookup_policy = self.lookup_policy.validate(state, call)
        if not lookup_policy.ok:
            step.observation = lookup_policy.reason
            state.failure_count += 1
            self._record_step(state, step)
            self.memory.append_event(
                RuntimeEvent(
                    "lookup_policy_blocked",
                    {
                        "step": context_step,
                        "role": role,
                        "model": model,
                        "attempted_tool": call.tool,
                        "pending_output_id": lookup_policy.pending_output_id,
                        "source_tool": lookup_policy.source_tool,
                    },
                )
            )
            self.memory.append_event(
                RuntimeEvent(
                    "agent_step_failed",
                    {
                        "step": context_step,
                        "reason": "tool_output_lookup_required",
                        "tool": call.tool,
                        "role": role,
                        "model": model,
                        "details": lookup_policy.reason,
                        "pending_output_id": lookup_policy.pending_output_id,
                    },
                )
            )
            return step

        result = tool.run(call.args)
        output_handle = self.memory.store_tool_result(
            call.tool,
            call.args,
            result,
            task=state.task,
        )
        step.observation = output_handle.render_for_model()
        step.tool_output_handle = output_handle.to_trace()
        self.lookup_policy.observe_result(state, call, result, output_handle)
        evidence = None
        if call.tool == "tool_output_lookup" and result.ok:
            evidence = build_evidence_selection(result.metadata)
        if evidence is not None:
            state.evidence_history.append(evidence)
            self.memory.append_event(
                RuntimeEvent(
                    "evidence_selected",
                    {
                        "step": context_step,
                        "role": role,
                        "model": model,
                        **evidence.to_dict(),
                    },
                )
            )
        if not result.ok:
            state.failure_count += 1
        state.modified_files.update(result.modified_files)
        self._record_step(state, step)
        self.memory.append_event(
            RuntimeEvent(
                "tool_call",
                {
                    "step": context_step,
                    "role": role,
                    "model": model,
                    "tool": call.tool,
                    "ok": result.ok,
                    "modified_files": result.modified_files,
                    "metadata": result.metadata,
                    "output_handle": output_handle.to_trace(),
                },
            )
        )
        return step

    def _decision_tool_calls(self, decision: dict[str, Any]) -> list[dict[str, Any]]:
        raw_calls = decision.get("tool_calls")
        if isinstance(raw_calls, list):
            calls = [call for call in raw_calls if self._is_valid_action(call)]
            if calls:
                return calls
        action = decision.get("action")
        if self._is_valid_action(action):
            call = dict(action)
            if not str(call.get("id", "")).strip():
                call["id"] = "native-call-1"
            return [call]
        return []

    def _build_native_assistant_tool_message(
        self,
        thought: str,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rendered_calls: list[dict[str, Any]] = []
        for index, call in enumerate(tool_calls, start=1):
            call_id = str(call.get("id", "")).strip() or f"native-call-{index}"
            rendered_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": str(call.get("tool", "")).strip(),
                        "arguments": json.dumps(call.get("args", {}), ensure_ascii=False),
                    },
                }
            )
            call["id"] = call_id
        return {
            "role": "assistant",
            "content": thought or "",
            "tool_calls": rendered_calls,
        }

    def _attempt_forced_finalization(
        self,
        *,
        state: TaskState,
        evidence_summary: dict[str, Any],
        failure_report: FailureReport,
    ) -> dict[str, Any] | None:
        if not state.steps:
            return None

        model = self.router.select_model("summarizer", state)
        self.memory.append_event(
            RuntimeEvent(
                "forced_finalization_attempted",
                {
                    "model": model,
                    "step_count": len(state.steps),
                    "modified_files": sorted(state.modified_files),
                },
            )
        )
        raw = self.client.complete(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": self._build_forced_final_prompt(
                        state=state,
                        evidence_summary=evidence_summary,
                        failure_report=failure_report,
                    ),
                }
            ],
        )
        decision = self._parse_decision(raw)
        final_value = decision.get("final")
        final = str(final_value).strip() if final_value is not None else ""
        if not final:
            self.memory.append_event(
                RuntimeEvent(
                    "forced_finalization_failed",
                    {
                        "model": model,
                        "raw_excerpt": self._compact_text(raw, 400),
                    },
                )
            )
            return None

        completed = self._decision_marks_completion(decision)
        self.memory.append_event(
            RuntimeEvent(
                "forced_finalization_succeeded",
                {
                    "model": model,
                    "completed": completed,
                    "final_excerpt": self._compact_text(final, 240),
                },
            )
        )
        return {"final": final, "completed": completed}

    def _normalize_decision(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"thought": "Invalid model output.", "action": None, "final": None}

        thought = str(payload.get("thought", "")).strip()
        final_value = payload.get("final")
        final = str(final_value).strip() if final_value is not None else None
        tool_calls = self._normalize_tool_calls(payload)
        action = tool_calls[0] if tool_calls else None
        if action is None:
            action_payload = payload.get("action")
            if isinstance(action_payload, dict):
                tool = str(action_payload.get("tool", "")).strip()
                args = action_payload.get("args", {})
                if not isinstance(args, dict):
                    args = {}
                if tool:
                    action = {"tool": tool, "args": args}
        normalized = {"thought": thought, "action": action, "final": final}
        if tool_calls:
            normalized["tool_calls"] = tool_calls
        status = str(payload.get("status", "")).strip().lower()
        if status in {"completed", "incomplete"}:
            normalized["status"] = status
        return normalized

    def _normalize_tool_calls(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        raw_calls = payload.get("tool_calls")
        if not isinstance(raw_calls, list):
            return normalized
        for item in raw_calls:
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool", "")).strip()
            if not tool:
                function = item.get("function", {})
                if isinstance(function, dict):
                    tool = str(function.get("name", "")).strip()
            args = item.get("args", {})
            if not isinstance(args, dict):
                function = item.get("function", {})
                raw_arguments = function.get("arguments", {}) if isinstance(function, dict) else {}
                if isinstance(raw_arguments, str):
                    try:
                        args = json.loads(raw_arguments)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = raw_arguments if isinstance(raw_arguments, dict) else {}
            if not tool or not isinstance(args, dict):
                continue
            tool_call: dict[str, Any] = {"tool": tool, "args": args}
            tool_call_id = str(item.get("id", "")).strip()
            if tool_call_id:
                tool_call["id"] = tool_call_id
            normalized.append(tool_call)
        return normalized

    def _decision_is_actionable(self, decision: dict[str, Any]) -> bool:
        final = decision.get("final")
        if isinstance(final, str) and final.strip():
            return True
        if isinstance(decision.get("tool_calls"), list) and decision["tool_calls"]:
            return True
        return self._is_valid_action(decision.get("action"))

    def _decision_marks_completion(self, decision: dict[str, Any]) -> bool:
        return str(decision.get("status", "completed")).strip().lower() != "incomplete"

    def _is_valid_action(self, action: Any) -> bool:
        return (
            isinstance(action, dict)
            and bool(str(action.get("tool", "")).strip())
            and isinstance(action.get("args", {}), dict)
        )

    def _build_decision_repair_prompt(
        self,
        *,
        state: TaskState,
        role: str,
        raw_output: str,
    ) -> str:
        tool_names = " | ".join(sorted(self.tools))
        return "\n".join(
            [
                "Your previous response did not match the runtime JSON contract.",
                "Re-emit exactly one JSON object and nothing else.",
                "If the previous response was a final answer, wrap it into `final` with `action` set to null.",
                "If the previous response was selecting a tool, express it under `action` with a valid tool name and JSON object args.",
                "",
                "Allowed JSON shapes:",
                "{",
                '  "thought": "short reasoning",',
                '  "action": {"tool": "' + tool_names + '", "args": {}},',
                '  "final": null',
                "}",
                "or",
                "{",
                '  "thought": "why the task is complete",',
                '  "action": null,',
                '  "final": "concise user-facing summary"',
                "}",
                "",
                f"Task: {state.task}",
                f"Current role: {role}",
                "Previous response:",
                self._compact_text(raw_output, 4_000),
            ]
        )

    def _build_forced_final_prompt(
        self,
        *,
        state: TaskState,
        evidence_summary: dict[str, Any],
        failure_report: FailureReport,
    ) -> str:
        modified_files = ", ".join(sorted(state.modified_files)) or "(none)"
        evidence_line = ", ".join(str(item) for item in evidence_summary.get("queries", [])) or "(none)"
        return "\n".join(
            [
                "The coding-agent run ended without a valid final answer.",
                "Close the run now.",
                "Return exactly one JSON object and nothing else.",
                "",
                "Schema:",
                "{",
                '  "thought": "brief closing rationale",',
                '  "action": null,',
                '  "final": "user-facing wrap-up of what happened",',
                '  "status": "completed | incomplete"',
                "}",
                "",
                "Use `status=completed` only when the task has enough evidence for a completed answer.",
                "Use `status=incomplete` when the work is partial, blocked, or unverified.",
                "",
                f"Task: {state.task}",
                f"Modified files: {modified_files}",
                f"Failure count: {state.failure_count}",
                f"Evidence queries: {evidence_line}",
                "Failure summary:",
                failure_report.to_markdown(),
                "",
                "Recent execution trace:",
                self._format_recent_trace(state),
            ]
        )

    def _format_recent_trace(self, state: TaskState, limit: int = 6) -> str:
        if not state.steps:
            return "(no steps)"
        rows: list[str] = []
        for step in state.steps[-limit:]:
            rows.append(
                "\n".join(
                    [
                        f"Step {step.index} [{step.role}/{step.model}]",
                        f"Thought: {self._compact_text(step.thought, 240)}",
                        f"Action: {step.action.tool if step.action else '(none)'}",
                        f"Observation: {self._compact_text(step.observation or '(none)', 600)}",
                    ]
                )
            )
        return "\n\n".join(rows)

    def _compact_text(self, text: str, limit: int) -> str:
        stripped = str(text or "").strip()
        if len(stripped) <= limit:
            return stripped
        return stripped[: max(0, limit - 3)] + "..."

    def _record_step(self, state: TaskState, step: AgentStep) -> None:
        state.steps.append(step)
        if step.role == "summarizer":
            state.last_summarized_compacted_steps = state.compacted_steps
        update = refresh_compact_summary(state)
        if update is None:
            return
        self.memory.append_event(
            RuntimeEvent(
                "context_compacted",
                {
                    "step": step.index,
                    "compacted_steps": update.compacted_steps,
                    "kept_steps": update.kept_steps,
                    "summary_chars": update.summary_chars,
                    "tool_counts": update.tool_counts,
                },
            )
        )

    def _system_prompt_for_route(self, role: str, guidance: str) -> str:
        base_prompt = TOOL_CALLING_SYSTEM_PROMPT if self._supports_native_tool_calling() else SYSTEM_PROMPT
        return "\n".join(
            [
                base_prompt,
                "",
                f"Current role: {role}",
                f"Role guidance: {guidance}",
            ]
        )

    def _supports_native_tool_calling(self) -> bool:
        return isinstance(self.client, NativeToolCallingClient)
