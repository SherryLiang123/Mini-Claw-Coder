from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from mini_claw.agent.loop import AgentLoop
from mini_claw.agent.state import AgentResult
from mini_claw.background.jobs import BackgroundRunManager
from mini_claw.config import AppConfig, ModelConfig, RuntimeConfig
from mini_claw.context.file_index import render_file_index
from mini_claw.dashboard import build_runtime_dashboard, summarize_dashboard_changes
from mini_claw.doctor import (
    run_runtime_doctor,
    summarize_doctor_category_delta,
    summarize_doctor_changes,
)
from mini_claw.home import (
    HOME_TUI_SECTION_IDS,
    build_terminal_home,
    render_terminal_home_markdown,
    render_terminal_home_tui,
    resolve_home_tui_preset,
)
from mini_claw.evals.runner import run_eval_file
from mini_claw.evals.bench import compare_bench_routing_policies, run_bench_file
from mini_claw.llm.factory import create_model_client
from mini_claw.llm.base import NativeToolCallingClient
from mini_claw.memory.store import MemoryStore
from mini_claw.routing.router import ModelRouter
from mini_claw.sessions.replay import replay_session, replay_session_turn
from mini_claw.sessions.store import SessionManager
from mini_claw.skills.patches import build_skill_patch_apply_preview
from mini_claw.skills.loader import SkillLoader, select_relevant_skills
from mini_claw.tools.runtime import build_runtime_tools
from mini_claw.tools.specs import build_tool_specs
from mini_claw.tracing.events import RuntimeEvent
from mini_claw.tracing.replay import replay_trace
from mini_claw.viewer import load_viewer_source, render_viewer_html
from mini_claw.task_graph.graph import TaskGraph, TaskNode
from mini_claw.task_graph.orchestrator import CoderRunResult, run_task_graph_orchestration
from mini_claw.task_graph.workspace import TaskWorkspaceManager


def build_agent(
    args: argparse.Namespace,
    *,
    execution_workspace: Path | None = None,
    memory_workspace: Path | None = None,
    skill_roots: list[Path] | None = None,
) -> AgentLoop:
    workspace = (execution_workspace or Path(args.workspace).resolve()).resolve()
    memory_root = (memory_workspace or workspace).resolve()
    runtime = RuntimeConfig(
        workspace=workspace,
        max_steps=args.max_steps,
        command_timeout_seconds=args.timeout,
        dry_run=args.dry_run,
    )
    models = ModelConfig(
        provider=args.provider,
        default_model=args.model,
        planner_model=args.model,
        coder_model=args.model,
        reviewer_model=args.model,
        summarizer_model=args.model,
    )
    config = AppConfig(runtime=runtime, models=models)

    memory = MemoryStore(memory_root / ".mini_claw" / "memory")
    resolved_skill_roots: list[Path] = []
    for path in skill_roots or [workspace / ".mini_claw" / "skills"]:
        resolved = path.resolve()
        if resolved not in resolved_skill_roots:
            resolved_skill_roots.append(resolved)
    skills = SkillLoader(resolved_skill_roots).load()
    router = ModelRouter(models, policy=args.routing_policy)
    client = create_model_client(models.provider, workspace=workspace)

    tools = build_runtime_tools(
        workspace=workspace,
        memory=memory,
        timeout_seconds=runtime.command_timeout_seconds,
        dry_run=runtime.dry_run,
        require_read_snapshot=args.enforce_read_before_write,
    )
    return AgentLoop(config=config, client=client, router=router, tools=tools, memory=memory, skills=skills)


def cmd_run(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    task = str(getattr(args, "task", "") or "").strip()
    resolved_task = str(getattr(args, "resolved_task", task) or task).strip()
    session_context = ""
    run_metadata: dict[str, object] = {}
    session_manager: SessionManager | None = None
    turn = None
    trace_start = 0
    if args.session:
        session_manager = SessionManager(workspace)
        session = session_manager.read_session(args.session)
        session_context = session_manager.build_context(session.session_id)
        turn = session_manager.begin_turn(session.session_id, task)
        trace_start = session_manager.trace_line_count()
        run_metadata = {
            "session_id": session.session_id,
            "session_name": session.name,
            "session_turn_id": turn.turn_id,
            "session_turn_index": turn.turn_index,
        }
    try:
        execution_mode, execution_task_id, execution_workspace = _prepare_run_execution_workspace(
            args=args,
            workspace=workspace,
            turn_id=turn.turn_id if turn is not None else "",
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    run_metadata.update(
        {
            "workspace_root": str(workspace),
            "execution_mode": execution_mode,
            "execution_task_id": execution_task_id,
            "execution_workspace": str(execution_workspace),
        }
    )
    agent = build_agent(
        args,
        execution_workspace=execution_workspace,
        memory_workspace=workspace,
        skill_roots=[
            execution_workspace / ".mini_claw" / "skills",
            workspace / ".mini_claw" / "skills",
        ],
    )
    agent.memory.append_event(
        RuntimeEvent(
            "execution_workspace_prepared",
            {
                "workspace_root": str(workspace),
                "execution_mode": execution_mode,
                "execution_task_id": execution_task_id,
                "execution_workspace": str(execution_workspace),
            },
        )
    )
    result = agent.run(
        resolved_task,
        session_context=session_context,
        run_metadata=run_metadata,
    )
    merge_back_status = ""
    merge_back_output = ""
    merge_back_files: list[str] = []
    _read_execution_diff_if_needed(
        args=args,
        workspace=workspace,
        execution_mode=execution_mode,
        execution_task_id=execution_task_id,
        memory=agent.memory,
    )
    merge_back_requested = bool(getattr(args, "merge_back", False))
    if merge_back_requested:
        if execution_mode == "main":
            print("merge-back requires an isolated execution mode.", file=sys.stderr)
            merge_back_status = "invalid"
            merge_back_output = "merge-back requires an isolated execution mode"
            if session_manager is not None and turn is not None:
                session_manager.complete_turn(
                    args.session,
                    turn.turn_id,
                    result=result,
                    trace_lines=session_manager.read_trace_slice(trace_start),
                    execution_mode=execution_mode,
                    execution_workspace=str(execution_workspace),
                    execution_task_id=execution_task_id,
                    merge_back_status=merge_back_status,
                    merge_back_output=merge_back_output,
                    merge_back_files=merge_back_files,
                )
            return 1
        if result.success:
            merge_back_status, merge_back_output, merge_back_files = _merge_execution_workspace(
                args=args,
                workspace=workspace,
                execution_task_id=execution_task_id,
                memory=agent.memory,
            )
            print(f"[merge-back] {merge_back_output}")
        else:
            merge_back_status = "skipped"
            merge_back_output = "skipped because agent run failed"
            agent.memory.append_event(
                RuntimeEvent(
                    "execution_workspace_merge",
                    {
                        "task_id": execution_task_id,
                        "status": merge_back_status,
                        "output": merge_back_output,
                    },
                )
            )
            print(f"[merge-back] {merge_back_output}")
    if merge_back_requested and merge_back_status not in {"", "ok", "skipped"}:
        result = AgentResult(
            success=False,
            final_answer=_build_merge_back_failure_summary(
                result=result,
                merge_back_status=merge_back_status,
                merge_back_output=merge_back_output,
                execution_workspace=execution_workspace,
                merge_back_files=merge_back_files,
            ),
            steps=result.steps,
            modified_files=result.modified_files,
            failure_report=result.failure_report,
        )
    if session_manager is not None and turn is not None:
        session_manager.complete_turn(
            args.session,
            turn.turn_id,
            result=result,
            trace_lines=session_manager.read_trace_slice(trace_start),
            execution_mode=execution_mode,
            execution_workspace=str(execution_workspace),
            execution_task_id=execution_task_id,
            merge_back_status=merge_back_status,
            merge_back_output=merge_back_output,
            merge_back_files=merge_back_files,
        )
    if execution_mode != "main":
        print(
            f"[execution] mode={execution_mode} task_id={execution_task_id} "
            f"workspace={execution_workspace}"
        )
        _print_execution_follow_up(
            args=args,
            execution_task_id=execution_task_id,
            merge_back_requested=merge_back_requested,
            merge_back_status=merge_back_status,
            merge_back_files=merge_back_files,
        )
    print(result.final_answer)
    if merge_back_requested and merge_back_status not in {"ok", "skipped"}:
        return 1
    return 0 if result.success else 1


def _build_merge_back_failure_summary(
    *,
    result: AgentResult,
    merge_back_status: str,
    merge_back_output: str,
    execution_workspace: Path,
    merge_back_files: list[str],
) -> str:
    changed_paths = ", ".join(merge_back_files or result.modified_files) or "(none)"
    original = " ".join((result.final_answer or "").split())
    lines = [
        "The agent completed work inside the isolated execution workspace, but merge-back did not succeed.",
        f"merge_back_status: {merge_back_status}",
        f"changed_paths: {changed_paths}",
        f"execution_workspace: {execution_workspace}",
        f"merge_back_output: {merge_back_output}",
    ]
    if original:
        lines.append(f"agent_summary_before_merge: {original}")
    lines.append(
        "Review or retry merge from the isolated workspace before treating the task as completed."
    )
    return "\n".join(lines)


def cmd_chat(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    session_manager = SessionManager(workspace)
    try:
        session = (
            session_manager.read_session(args.session)
            if str(getattr(args, "session", "")).strip()
            else session_manager.create(name=str(getattr(args, "session_name", "")).strip() or "chat")
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    merge_verify = _resolve_default_chat_merge_verify(
        workspace=workspace,
        explicit_commands=list(getattr(args, "merge_verify", [])),
    )
    print(f"[chat] session={session.session_id} name={session.name or '-'} workspace={workspace}")
    print(
        "[chat] enter a coding task. Commands: /help, /session, /replay, /exit"
    )
    if bool(getattr(args, "merge_back", False)):
        verify_text = ", ".join(merge_verify) if merge_verify else "(none)"
        print(f"[chat] merge-back=on verify={verify_text}")
    else:
        print("[chat] merge-back=off")

    while True:
        try:
            raw_task = input("mini-claw> ")
        except EOFError:
            print(f"[chat] closed {session.session_id}")
            return 0

        task = raw_task.strip()
        if not task:
            continue
        lowered = task.lower()
        if lowered in {"/exit", "/quit", "exit", "quit"}:
            print(f"[chat] closed {session.session_id}")
            return 0
        if lowered == "/help":
            print("Commands: /help, /session, /replay, /exit")
            continue
        if lowered == "/session":
            current = session_manager.read_session(session.session_id)
            print(
                f"[chat] session={current.session_id} turns={current.turn_count} "
                f"updated_at={current.updated_at}"
            )
            continue
        if lowered == "/replay":
            report = replay_session(
                session_manager,
                session.session_id,
                turn_limit=int(getattr(args, "turn_limit", 10)),
            )
            print(report.to_markdown())
            continue

        direct_answer = _maybe_answer_recent_reference_query(
            session_manager=session_manager,
            session_ref=session.session_id,
            task=task,
            workspace=workspace,
        )
        if direct_answer is not None:
            _record_chat_controller_turn(
                session_manager=session_manager,
                session_ref=session.session_id,
                task=task,
                final_answer=direct_answer,
            )
            print(direct_answer)
            continue

        resolved_task, resolution_notice = _resolve_chat_task_from_session(
            session_manager=session_manager,
            session_ref=session.session_id,
            task=task,
            workspace=workspace,
        )
        if resolution_notice:
            print(f"[chat] {resolution_notice}")
        run_args = _build_run_args_from_chat(
            args=args,
            task=task,
            resolved_task=resolved_task,
            session_ref=session.session_id,
            merge_verify=merge_verify,
        )
        exit_code = cmd_run(run_args)
        if exit_code != 0:
            print(f"[chat] task exited with code {exit_code}")


def _build_run_args_from_chat(
    *,
    args: argparse.Namespace,
    task: str,
    resolved_task: str,
    session_ref: str,
    merge_verify: list[str],
) -> argparse.Namespace:
    return argparse.Namespace(
        task=task,
        resolved_task=resolved_task,
        workspace=args.workspace,
        provider=args.provider,
        model=args.model,
        routing_policy=args.routing_policy,
        max_steps=args.max_steps,
        timeout=args.timeout,
        dry_run=args.dry_run,
        enforce_read_before_write=args.enforce_read_before_write,
        session=session_ref,
        execution_mode=args.execution_mode,
        execution_id="",
        show_execution_diff=args.show_execution_diff,
        merge_back=args.merge_back,
        merge_verify=list(merge_verify),
        rollback_on_merge_verification_failure=args.rollback_on_merge_verification_failure,
    )


def _resolve_chat_task_from_session(
    *,
    session_manager: SessionManager,
    session_ref: str,
    task: str,
    workspace: Path,
) -> tuple[str, str]:
    normalized_task = task.strip()
    if not normalized_task:
        return normalized_task, ""
    recent_paths = session_manager.recent_modified_paths(session_ref, max_turns=3, limit=5)
    if not recent_paths:
        return normalized_task, ""
    if _task_mentions_recent_path(normalized_task, recent_paths):
        return normalized_task, ""
    if not _task_uses_previous_turn_reference(normalized_task):
        return normalized_task, ""

    resolved_path = recent_paths[0]
    resolved_target = (workspace / resolved_path.rstrip("/")).resolve()
    path_kind = "directory" if resolved_path.endswith("/") or resolved_target.is_dir() else "file"
    note = (
        "Resolved previous-turn reference to "
        f"{path_kind} `{resolved_path}` at `{resolved_target}`."
    )
    augmented_task = "\n".join(
        [
            normalized_task,
            "",
            "Resolved reference from the previous turn:",
            f"- path: {resolved_path}",
            f"- absolute_path: {resolved_target}",
            f"- kind: {path_kind}",
            "- Use this resolved path unless the user explicitly corrects it.",
        ]
    )
    return augmented_task, note


def _maybe_answer_recent_reference_query(
    *,
    session_manager: SessionManager,
    session_ref: str,
    task: str,
    workspace: Path,
) -> str | None:
    normalized_task = task.strip()
    if not normalized_task or not _task_requests_path_lookup(normalized_task):
        return None
    recent_paths = session_manager.recent_modified_paths(session_ref, max_turns=3, limit=5)
    if not recent_paths or _task_mentions_recent_path(normalized_task, recent_paths):
        return None
    if not _task_uses_previous_turn_reference(normalized_task):
        return None

    resolved_path = recent_paths[0]
    target = (workspace / resolved_path.rstrip("/")).resolve()
    is_directory = resolved_path.endswith("/") or target.is_dir()
    kind_label = "目录" if is_directory else "文件"
    rel_display = resolved_path.rstrip("/") or "."
    if target.exists():
        return (
            f"上一个引用的{kind_label}路径是 `{rel_display}`。\n"
            f"绝对路径：`{target}`"
        )
    return (
        f"上一个引用的{kind_label}路径候选是 `{rel_display}`。\n"
        f"预期绝对路径：`{target}`\n"
        "当前主工作区没有找到它，可能只存在于隔离工作区，或者上一次 merge-back 没有成功。"
    )


def _record_chat_controller_turn(
    *,
    session_manager: SessionManager,
    session_ref: str,
    task: str,
    final_answer: str,
) -> None:
    turn = session_manager.begin_turn(session_ref, task)
    session_manager.complete_turn(
        session_ref,
        turn.turn_id,
        result=AgentResult(
            success=True,
            final_answer=final_answer,
            steps=[],
            modified_files=[],
        ),
        trace_lines=[],
    )


def _task_mentions_recent_path(task: str, recent_paths: list[str]) -> bool:
    lowered = task.lower()
    for path in recent_paths:
        normalized = path.replace("\\", "/").strip("/")
        if not normalized:
            continue
        basename = normalized.rsplit("/", 1)[-1].lower()
        full = normalized.lower()
        if basename and basename in lowered:
            return True
        if full and full in lowered:
            return True
    return False


def _task_uses_previous_turn_reference(task: str) -> bool:
    lowered = task.lower()
    chinese_tokens = [
        "刚刚让你新建的那个文件",
        "刚刚让你新建的那个文件夹",
        "刚刚让你新建的那个目录",
        "刚才让你新建的那个文件",
        "刚才让你新建的那个文件夹",
        "上一个文件",
        "上一个文件夹",
        "上一个目录",
        "之前那个文件",
        "之前那个文件夹",
        "前面那个文件",
        "前面那个文件夹",
        "这个文件",
        "这个文件夹",
        "这个目录",
        "那个文件",
        "那个文件夹",
        "那个目录",
        "它的位置",
        "它在哪",
        "它在哪里",
    ]
    english_tokens = [
        "previous",
        "earlier",
        "that file",
        "that folder",
        "that directory",
        "this file",
        "this folder",
        "this directory",
        "it",
        "just created",
        "just made",
    ]
    if any(token in task for token in chinese_tokens):
        return True
    return any(token in lowered for token in english_tokens)


def _task_requests_path_lookup(task: str) -> bool:
    lowered = task.lower()
    chinese_tokens = ["位置", "路径", "在哪", "在哪里", "地址"]
    english_tokens = ["where", "path", "location", "located"]
    if any(token in task for token in chinese_tokens):
        return True
    return any(token in lowered for token in english_tokens)


def _resolve_default_chat_merge_verify(
    *,
    workspace: Path,
    explicit_commands: list[str],
) -> list[str]:
    commands = [command for command in explicit_commands if str(command).strip()]
    if commands:
        return commands
    tests_dir = workspace / "tests"
    if tests_dir.exists() and tests_dir.is_dir():
        return ["python -m unittest discover -s tests -q"]
    return []


def _print_execution_follow_up(
    *,
    args: argparse.Namespace,
    execution_task_id: str,
    merge_back_requested: bool,
    merge_back_status: str,
    merge_back_files: list[str],
) -> None:
    workspace_arg = _render_cli_arg(str(getattr(args, "workspace", ".") or "."))
    if merge_back_requested:
        if merge_back_status == "ok" and merge_back_files:
            print(f"[merge-back-files] {', '.join(merge_back_files)}")
            return
        if merge_back_status in {"conflict", "failed", "skipped"}:
            print(
                "[execution-next] review diff: "
                f"python -m mini_claw workspace diff {execution_task_id} "
                f"--workspace {workspace_arg}"
            )
            print(
                "[execution-next] retry merge: "
                f"python -m mini_claw workspace merge {execution_task_id} "
                f"--workspace {workspace_arg}"
            )
        return
    print(
        "[execution-next] review diff: "
        f"python -m mini_claw workspace diff {execution_task_id} "
        f"--workspace {workspace_arg}"
    )
    print(
        "[execution-next] merge approved changes: "
        f"python -m mini_claw workspace merge {execution_task_id} "
        f"--workspace {workspace_arg}"
    )


def _render_cli_arg(value: str) -> str:
    if not value or any(char.isspace() for char in value) or '"' in value:
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _prepare_run_execution_workspace(
    *,
    args: argparse.Namespace,
    workspace: Path,
    turn_id: str,
) -> tuple[str, str, Path]:
    mode = str(getattr(args, "execution_mode", "copy") or "copy").strip()
    if mode == "main":
        return "main", "", workspace

    if mode not in {"copy", "git-worktree"}:
        raise ValueError(f"Unknown execution mode: {mode}")

    task_id = str(getattr(args, "execution_id", "") or "").strip()
    if not task_id:
        task_id = turn_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"

    manager = TaskWorkspaceManager(workspace)
    existing = next((entry for entry in manager.list() if entry.task_id == task_id), None)
    if existing is not None:
        if existing.mode != mode:
            raise ValueError(
                f"Execution workspace {task_id} already exists with mode={existing.mode}; "
                f"requested mode={mode}."
            )
        return existing.mode, task_id, Path(existing.path).resolve()

    created = manager.create(task_id, mode=mode)
    return created.mode, task_id, Path(created.path).resolve()


def _read_execution_diff_if_needed(
    *,
    args: argparse.Namespace,
    workspace: Path,
    execution_mode: str,
    execution_task_id: str,
    memory: MemoryStore,
) -> list[object]:
    if execution_mode == "main" or not bool(getattr(args, "show_execution_diff", False)):
        return []
    manager = TaskWorkspaceManager(workspace)
    summaries = manager.diff(execution_task_id)
    memory.append_event(
        RuntimeEvent(
            "execution_workspace_diff",
            {
                "task_id": execution_task_id,
                "changed_files": len(summaries),
                "paths": [summary.path for summary in summaries[:20]],
            },
        )
    )
    if not summaries:
        print("[execution-diff] (no changes)")
        return summaries
    for summary in summaries:
        print(
            f"[execution-diff] {summary.path} [{summary.status}] "
            f"+{summary.added_lines}/-{summary.removed_lines}"
        )
    return summaries


def _smoke_tool_calls(decision: dict[str, object]) -> list[dict[str, object]]:
    raw_calls = decision.get("tool_calls")
    if isinstance(raw_calls, list):
        normalized: list[dict[str, object]] = []
        for item in raw_calls:
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool", "")).strip()
            args = item.get("args", {})
            if tool and isinstance(args, dict):
                normalized.append(
                    {
                        "id": str(item.get("id", "")).strip(),
                        "tool": tool,
                        "args": args,
                    }
                )
        if normalized:
            return normalized
    action = decision.get("action")
    if isinstance(action, dict):
        tool = str(action.get("tool", "")).strip()
        args = action.get("args", {})
        if tool and isinstance(args, dict):
            return [
                {
                    "id": str(action.get("id", "")).strip(),
                    "tool": tool,
                    "args": args,
                }
            ]
    return []


def _build_smoke_assistant_tool_message(tool_calls: list[dict[str, object]]) -> dict[str, object]:
    rendered_calls: list[dict[str, object]] = []
    for index, call in enumerate(tool_calls, start=1):
        call_id = str(call.get("id", "")).strip() or f"smoke-call-{index}"
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
        "content": "",
        "tool_calls": rendered_calls,
    }


def _merge_execution_workspace(
    *,
    args: argparse.Namespace,
    workspace: Path,
    execution_task_id: str,
    memory: MemoryStore,
) -> tuple[str, str, list[str]]:
    manager = TaskWorkspaceManager(workspace)
    result = manager.merge(
        execution_task_id,
        verification_commands=list(getattr(args, "merge_verify", [])),
        rollback_on_verification_failure=bool(
            getattr(args, "rollback_on_merge_verification_failure", False)
        ),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    payload = {
        "task_id": execution_task_id,
        "status": "ok" if result.ok else ("conflict" if result.conflicts else "failed"),
        "output": result.output,
        "merged_files": list(result.merged_files),
        "conflict_count": len(result.conflicts),
        "transaction_id": result.transaction_id,
        "journal_path": result.journal_path,
    }
    if result.conflicts:
        payload["conflicts"] = [conflict.to_dict() for conflict in result.conflicts]
    memory.append_event(RuntimeEvent("execution_workspace_merge", payload))
    if result.conflicts:
        conflict_preview = ", ".join(conflict.path for conflict in result.conflicts[:5])
        output = f"{result.output}; conflicts={conflict_preview}"
        return "conflict", output, []
    if not result.ok:
        return "failed", result.output, []
    return "ok", result.output, list(result.merged_files)


def cmd_eval(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    report = run_eval_file(
        Path(args.file),
        workspace=workspace,
        provider=args.provider,
        routing_policy=args.routing_policy,
    )
    print(report.to_markdown())
    return 0 if report.failed == 0 else 1


def cmd_bench(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    report = run_bench_file(
        Path(args.file),
        workspace=workspace,
        routing_policy=args.routing_policy,
    )
    print(report.to_markdown())
    return 0 if report.failed == 0 else 1


def cmd_bench_routing(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    report = compare_bench_routing_policies(
        Path(args.file),
        workspace=workspace,
        policies=args.policies,
    )
    print(report.to_markdown())
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    memory = MemoryStore(workspace / ".mini_claw" / "memory")
    client = create_model_client(args.provider, workspace=workspace)
    if not isinstance(client, NativeToolCallingClient):
        print(
            "Smoke requires a provider that supports native tool calling.",
            file=sys.stderr,
        )
        return 1

    tool_names = ["shell", "tool_output_lookup"]
    tools = build_runtime_tools(
        workspace=workspace,
        memory=memory,
        timeout_seconds=args.timeout,
        dry_run=False,
        require_read_snapshot=False,
    )
    selected_tools = {name: tools[name] for name in tool_names}
    tool_specs = build_tool_specs(tool_names)
    prompt = (
        "Use the shell tool to run `python -S -c \"print('NATIVE_SMOKE_READY')\"` in the current workspace. "
        "If the output contains NATIVE_SMOKE_READY, answer exactly with NATIVE_SMOKE_OK. "
        "If the shell output is truncated, use tool_output_lookup before answering. "
        "Do not call any unrelated tool."
    )
    messages: list[dict[str, object]] = [{"role": "user", "content": prompt}]
    transcript: list[dict[str, object]] = []
    total_tool_calls = 0

    for round_index in range(1, args.max_rounds + 1):
        decision = client.complete_with_tools(
            model=args.model,
            messages=messages,
            tools=tool_specs,
        )
        tool_calls = _smoke_tool_calls(decision)
        final = str(decision.get("final", "") or "").strip()
        transcript.append(
            {
                "round": round_index,
                "tool_calls": [
                    {"id": str(call.get("id", "")), "tool": str(call.get("tool", ""))}
                    for call in tool_calls
                ],
                "final": final,
            }
        )
        if tool_calls:
            total_tool_calls += len(tool_calls)
            messages.append(_build_smoke_assistant_tool_message(tool_calls))
            for index, tool_call in enumerate(tool_calls, start=1):
                tool_name = str(tool_call.get("tool", "")).strip()
                tool = selected_tools.get(tool_name)
                if tool is None:
                    if args.json:
                        print(
                            json.dumps(
                                {
                                    "status": "error",
                                    "reason": "unknown_tool",
                                    "tool": tool_name,
                                    "rounds": round_index,
                                },
                                ensure_ascii=False,
                            )
                        )
                    else:
                        print(f"SMOKE_ERROR unknown tool: {tool_name}", file=sys.stderr)
                    return 1
                result = tool.run(dict(tool_call.get("args", {})))
                output_handle = memory.store_tool_result(
                    tool_name,
                    dict(tool_call.get("args", {})),
                    result,
                    task="native-tool-calling-smoke",
                )
                tool_call_id = str(tool_call.get("id", "")).strip() or f"smoke-call-{round_index}-{index}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": output_handle.render_for_model(),
                    }
                )
            continue
        if final:
            ok = final == args.expected_final
            payload = {
                "status": "ok" if ok else "mismatch",
                "expected_final": args.expected_final,
                "actual_final": final,
                "rounds": round_index,
                "tool_calls": total_tool_calls,
                "transcript": transcript,
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(final)
            return 0 if ok else 1

    payload = {
        "status": "timeout",
        "expected_final": args.expected_final,
        "rounds": args.max_rounds,
        "tool_calls": total_tool_calls,
        "transcript": transcript,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("SMOKE_TIMEOUT native tool-calling smoke did not produce a final answer.", file=sys.stderr)
    return 1


def cmd_replay(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    trace_path = Path(args.trace) if args.trace else workspace / ".mini_claw" / "memory" / "task_trace.jsonl"
    if not trace_path.is_absolute():
        trace_path = workspace / trace_path
    report = replay_trace(trace_path)
    print(report.to_markdown())
    return 0


def cmd_session(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    manager = SessionManager(workspace)
    if args.session_command == "create":
        session = manager.create(name=args.name)
        if args.json:
            print(json.dumps(session.to_dict(), ensure_ascii=False, indent=2))
            return 0
        print(f"created {session.session_id}\tname={session.name or '-'}")
        return 0
    if args.session_command == "list":
        sessions = manager.list_sessions(limit=args.limit)
        if args.json:
            print(
                json.dumps(
                    [session.to_dict() for session in sessions],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if not sessions:
            print("(no sessions)")
            return 0
        for index, session in enumerate(sessions, start=1):
            print(
                f"{index}\t{session.session_id}\tturns={session.turn_count}\t"
                f"name={session.name or '-'}\tupdated_at={session.updated_at}"
            )
        return 0
    if args.session_command == "show":
        session = manager.read_session(args.ref)
        turns = list(reversed(manager.list_turns(session.session_id, limit=args.turn_limit)))
        if args.json:
            print(
                json.dumps(
                    {
                        "session": session.to_dict(),
                        "session_context_preview": manager.build_context(
                            session.session_id,
                            max_turns=args.turn_limit,
                            max_chars=args.max_chars,
                        ),
                        "turns": [turn.to_dict() for turn in turns],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        print(f"session_id: {session.session_id}")
        print(f"name: {session.name or '-'}")
        print(f"workspace: {session.workspace}")
        print(f"created_at: {session.created_at}")
        print(f"updated_at: {session.updated_at}")
        print(f"turn_count: {session.turn_count}")
        print(f"last_turn_id: {session.last_turn_id or '-'}")
        print("session_context_preview:")
        print(manager.build_context(session.session_id, max_turns=args.turn_limit, max_chars=args.max_chars))
        print("turns:")
        if not turns:
            print("(none)")
            return 0
        for turn in turns:
            status = turn.status if turn.status != "completed" else ("success" if turn.success else "failed")
            print(
                f"- turn={turn.turn_index}\tid={turn.turn_id}\tstatus={status}\t"
                f"events={turn.trace_event_count}\ttask={turn.task}"
            )
        return 0
    if args.session_command == "replay":
        report = replay_session(manager, args.ref, turn_limit=args.turn_limit)
        if args.json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
            return 0
        print(report.to_markdown())
        return 0
    if args.session_command == "turn-show":
        turn = replay_session_turn(manager, args.session_ref, args.turn_ref)
        if args.json:
            print(json.dumps(turn.to_dict(), ensure_ascii=False, indent=2))
            return 0
        print(turn.to_markdown())
        return 0
    raise ValueError(f"Unknown session command: {args.session_command}")


def cmd_dashboard(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    output_path = _resolve_output_path(workspace, args.output_file)
    if not args.watch:
        dashboard = _render_dashboard_snapshot(args, workspace)
        if args.json:
            text = json.dumps(dashboard.to_dict(), ensure_ascii=False, indent=2)
            print(text)
            _write_output_file(output_path, text, append=False)
            return 0
        print(dashboard.to_markdown())
        return 0

    iteration = 0
    max_iterations = max(int(args.iterations), 0)
    previous_dashboard = None
    try:
        while True:
            iteration += 1
            dashboard = _render_dashboard_snapshot(args, workspace)
            changes: list[str] = []
            payload = None
            if args.json:
                if previous_dashboard is not None:
                    changes = summarize_dashboard_changes(previous_dashboard, dashboard)
                payload = {
                    "iteration": iteration,
                    "changes": changes,
                    "dashboard": dashboard.to_dict(),
                }
                text = json.dumps(payload, ensure_ascii=False)
                print(text)
                _write_output_file(output_path, text, append=True)
                previous_dashboard = dashboard
                if max_iterations and iteration >= max_iterations:
                    break
                time.sleep(max(float(args.interval), 0.0))
                continue
            if not args.no_clear:
                print("\x1bc", end="")
            if iteration > 1:
                print()
            print(f"# Dashboard Watch {iteration}")
            print()
            if previous_dashboard is not None:
                print("## Changes Since Last Refresh")
                changes = summarize_dashboard_changes(previous_dashboard, dashboard)
                if changes:
                    for line in changes:
                        print(line)
                else:
                    print("- no runtime state changes detected")
                print()
            if not args.changes_only or previous_dashboard is None:
                print(dashboard.to_markdown())
            elif changes:
                print("(full dashboard hidden by --changes-only)")
            else:
                print("(no dashboard changes to display)")
            previous_dashboard = dashboard
            if max_iterations and iteration >= max_iterations:
                break
            time.sleep(max(float(args.interval), 0.0))
    except KeyboardInterrupt:
        return 130
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    output_path = _resolve_output_path(workspace, args.output_file)
    fail_on_codes = _parse_doctor_codes(args.fail_on)
    ignore_codes = _parse_doctor_codes(args.ignore)
    category_codes = _parse_doctor_codes(args.category)
    min_severity = str(args.severity_at_least).strip().lower()
    sort_by = str(args.sort_by).strip().lower()
    if not args.watch:
        report = _filter_doctor_report(
            _render_doctor_snapshot(args, workspace),
            ignore_codes,
            category_codes=category_codes,
            min_severity=min_severity,
            sort_by=sort_by,
        )
        if args.json:
            text = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
            print(text)
            _write_output_file(output_path, text, append=False)
        elif args.summary_only:
            print(report.summary)
        else:
            print(report.to_markdown())
        return _doctor_exit_code(report, strict_warnings=args.strict_warnings, fail_on_codes=fail_on_codes)

    iteration = 0
    max_iterations = max(int(args.iterations), 0)
    previous_report = None
    latest_exit_code = 0
    try:
        while True:
            iteration += 1
            report = _filter_doctor_report(
                _render_doctor_snapshot(args, workspace),
                ignore_codes,
                category_codes=category_codes,
                min_severity=min_severity,
                sort_by=sort_by,
            )
            latest_exit_code = _doctor_exit_code(
                report,
                strict_warnings=args.strict_warnings,
                fail_on_codes=fail_on_codes,
            )
            changes: list[str] = []
            if args.json:
                category_delta = {}
                if previous_report is not None:
                    changes = summarize_doctor_changes(previous_report, report)
                    category_delta = summarize_doctor_category_delta(previous_report, report)
                payload = {
                    "iteration": iteration,
                    "changes": changes,
                    "summary_by_category_delta": category_delta,
                    "report": report.to_dict(),
                    "exit_code": latest_exit_code,
                }
                text = json.dumps(payload, ensure_ascii=False)
                print(text)
                _write_output_file(output_path, text, append=True)
                previous_report = report
                if max_iterations and iteration >= max_iterations:
                    break
                time.sleep(max(float(args.interval), 0.0))
                continue

            if not args.no_clear:
                print("\x1bc", end="")
            if iteration > 1:
                print()
            print(f"# Doctor Watch {iteration}")
            print()
            if previous_report is not None:
                print("## Changes Since Last Refresh")
                changes = summarize_doctor_changes(previous_report, report)
                if changes:
                    for line in changes:
                        print(line)
                else:
                    print("- no doctor state changes detected")
                print()
            if not args.changes_only or previous_report is None:
                if args.summary_only:
                    print(report.summary)
                else:
                    print(report.to_markdown())
            elif changes:
                if args.summary_only:
                    print(report.summary)
                else:
                    print("(full doctor report hidden by --changes-only)")
            else:
                print("(no doctor changes to display)")
            previous_report = report
            if max_iterations and iteration >= max_iterations:
                break
            time.sleep(max(float(args.interval), 0.0))
    except KeyboardInterrupt:
        return 130
    return latest_exit_code


def cmd_home(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    output_path = _resolve_output_path(workspace, args.output_file)
    if not args.watch:
        home = _render_home_snapshot(args, workspace)
        if args.json:
            text = json.dumps(home, ensure_ascii=False, indent=2)
            print(text)
            _write_output_file(output_path, text, append=False)
        else:
            print(_render_home_text(args, home))
        return 0

    iteration = 0
    max_iterations = max(int(args.iterations), 0)
    previous_home = None
    resolved_changes_only = _resolve_home_watch_changes_only(args)
    try:
        while True:
            iteration += 1
            home = _render_home_snapshot(args, workspace)
            changes: list[str] = []
            changes_by_section: dict[str, list[str]] = _empty_export_changes_by_section("bundle")
            changes_by_section_delta: dict[str, object] = _empty_export_changes_by_section_delta("bundle")
            if previous_home is not None:
                previous_bundle = dict(previous_home.get("bundle") or {})
                current_bundle = dict(home.get("bundle") or {})
                changes = _summarize_export_changes("bundle", previous_bundle, current_bundle)
                changes_by_section = _summarize_export_changes_by_section(
                    "bundle",
                    previous_bundle,
                    current_bundle,
                )
                changes_by_section_delta = _summarize_export_changes_by_section_delta(
                    "bundle",
                    previous_bundle,
                    current_bundle,
                )
            if args.json:
                payload = {
                    "iteration": iteration,
                    "changes": changes,
                    "changes_by_section": changes_by_section,
                    "changes_by_section_delta": changes_by_section_delta,
                    "home": home,
                }
                text = json.dumps(payload, ensure_ascii=False)
                print(text)
                _write_output_file(output_path, text + "\n", append=iteration > 1)
                previous_home = home
                if max_iterations and iteration >= max_iterations:
                    break
                time.sleep(max(float(args.interval), 0.0))
                continue

            if not args.no_clear:
                print("\x1bc", end="")
            if iteration > 1:
                print(f"# Home Watch {iteration}")
                print()
                if str(getattr(args, "style", "plain") or "plain").strip().lower() != "tui":
                    print("## Changes Since Last Refresh")
                    if changes:
                        for item in changes:
                            print(item)
                    else:
                        print("- no home state changes detected")
                    print()
            if not resolved_changes_only or previous_home is None:
                print(
                    _render_home_text_with_deltas(
                        args,
                        home,
                        changes=changes if iteration > 1 else None,
                        changes_by_section=changes_by_section if iteration > 1 else None,
                        changes_by_section_delta=changes_by_section_delta if iteration > 1 else None,
                        changes_only=False,
                    )
                )
            elif str(getattr(args, "style", "plain") or "plain").strip().lower() == "tui":
                print(
                    _render_home_text_with_deltas(
                        args,
                        home,
                        changes=changes,
                        changes_by_section=changes_by_section,
                        changes_by_section_delta=changes_by_section_delta,
                        changes_only=True,
                    )
                )
            elif changes:
                print("(full home hidden by --changes-only)")
            else:
                print("(no home changes to display)")
            previous_home = home
            if max_iterations and iteration >= max_iterations:
                break
            time.sleep(max(float(args.interval), 0.0))
    except KeyboardInterrupt:
        return 130
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    output_path = _resolve_output_path(workspace, args.output_file)
    if not args.watch:
        payload = _render_export_payload(args, workspace)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        print(text)
        _write_output_file(output_path, text, append=False)
        return 0

    iteration = 0
    max_iterations = max(int(args.iterations), 0)
    previous_snapshot: dict[str, object] | None = None
    try:
        while True:
            iteration += 1
            snapshot = _render_export_payload(args, workspace)
            changes: list[str] = []
            changes_by_section: dict[str, list[str]] = _empty_export_changes_by_section(args.export_target)
            changes_by_section_delta: dict[str, object] = _empty_export_changes_by_section_delta(args.export_target)
            doctor_category_delta: dict[str, dict[str, int]] = {}
            if previous_snapshot is not None:
                changes = _summarize_export_changes(args.export_target, previous_snapshot, snapshot)
                changes_by_section = _summarize_export_changes_by_section(
                    args.export_target,
                    previous_snapshot,
                    snapshot,
                )
                changes_by_section_delta = _summarize_export_changes_by_section_delta(
                    args.export_target,
                    previous_snapshot,
                    snapshot,
                )
                if args.export_target == "bundle":
                    doctor_category_delta = _summarize_export_bundle_doctor_delta(previous_snapshot, snapshot)
            payload = {
                "iteration": iteration,
                "export_target": args.export_target,
                "changes": changes,
                "changes_by_section": changes_by_section,
                "changes_by_section_delta": changes_by_section_delta,
                "snapshot": snapshot if (not args.changes_only or previous_snapshot is None) else None,
            }
            if doctor_category_delta:
                payload["doctor_summary_by_category_delta"] = doctor_category_delta
            text = json.dumps(payload, ensure_ascii=False)
            print(text)
            _write_output_file(output_path, text, append=True)
            previous_snapshot = snapshot
            if max_iterations and iteration >= max_iterations:
                break
            time.sleep(max(float(args.interval), 0.0))
    except KeyboardInterrupt:
        return 130
    return 0


def cmd_viewer(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    output_path = _resolve_output_path(workspace, args.output_file)
    if output_path is None:
        output_path = (workspace / ".mini_claw" / "runtime_viewer.html").resolve()
    if args.from_workspace:
        export_args = argparse.Namespace(
            export_target=args.source_target,
            session=args.session,
            session_turn_limit=args.session_turn_limit,
            background_limit=args.background_limit,
            tool_output_limit=args.tool_output_limit,
            ignore=args.ignore,
            category=args.category,
            severity_at_least=args.severity_at_least,
            sort_by=args.sort_by,
        )
        document = {
            "mode": "snapshot",
            "source_path": f"workspace:{workspace}",
            "snapshot": _render_export_payload(export_args, workspace),
        }
    else:
        input_path = _resolve_viewer_input(workspace, args.input_file, args.source_target)
        document = load_viewer_source(input_path)
    html = render_viewer_html(
        document,
        title=args.title,
        refresh_seconds=args.refresh_seconds,
        demo_mode=args.demo_mode,
        demo_language=args.demo_language,
        demo_focus=getattr(args, "demo_focus", "auto"),
        demo_script=getattr(args, "demo_script", "full"),
    )
    _write_output_file(output_path, html, append=False)
    print(f"wrote {output_path}")
    return 0


def _render_export_payload(args: argparse.Namespace, workspace: Path) -> dict[str, object]:
    if args.export_target == "dashboard":
        return _render_dashboard_snapshot(args, workspace).to_dict()
    if args.export_target == "doctor":
        report = _filter_doctor_report(
            _render_doctor_snapshot(args, workspace),
            _parse_doctor_codes(args.ignore),
            category_codes=_parse_doctor_codes(args.category),
            min_severity=str(args.severity_at_least).strip().lower(),
            sort_by=str(args.sort_by).strip().lower(),
        )
        return report.to_dict()
    if args.export_target == "team-board":
        return _render_team_board_snapshot(args, workspace)
    if args.export_target == "bundle":
        return {
            "dashboard": _render_dashboard_snapshot(args, workspace).to_dict(),
            "doctor": _filter_doctor_report(
                _render_doctor_snapshot(args, workspace),
                _parse_doctor_codes(args.ignore),
                category_codes=_parse_doctor_codes(args.category),
                min_severity=str(args.severity_at_least).strip().lower(),
                sort_by=str(args.sort_by).strip().lower(),
            ).to_dict(),
            "team_board": _render_team_board_snapshot(args, workspace),
            "session_replay": _render_session_replay_snapshot(args, workspace),
        }
    raise ValueError(f"Unknown export target: {args.export_target}")


def _resolve_viewer_input(workspace: Path, input_file: str, source_target: str = "bundle") -> Path:
    raw = str(input_file).strip()
    candidates: list[Path] = []
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = workspace / path
        candidates.append(path.resolve())
    else:
        if str(source_target).strip().lower() == "team-board":
            candidates.extend(
                [
                    (workspace / ".mini_claw" / "team_board.ndjson").resolve(),
                    (workspace / ".mini_claw" / "team_board.json").resolve(),
                ]
            )
        else:
            candidates.extend(
                [
                    (workspace / ".mini_claw" / "runtime_bundle.ndjson").resolve(),
                    (workspace / ".mini_claw" / "runtime_bundle.json").resolve(),
                    (workspace / ".mini_claw" / "bundle.ndjson").resolve(),
                    (workspace / ".mini_claw" / "bundle.json").resolve(),
                ]
            )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ValueError(
        "Viewer input file was not found. Provide --input-file or generate one with "
        "`python -m mini_claw export bundle --output-file ...`."
    )


def _render_dashboard_snapshot(args: argparse.Namespace, workspace: Path):
    return build_runtime_dashboard(
        workspace,
        session_ref=args.session,
        session_turn_limit=args.session_turn_limit,
        background_limit=args.background_limit,
        tool_output_limit=args.tool_output_limit,
    )


def _render_home_snapshot(args: argparse.Namespace, workspace: Path) -> dict[str, object]:
    bundle_args = argparse.Namespace(**vars(args), export_target="bundle")
    bundle = _render_export_payload(bundle_args, workspace)
    return build_terminal_home(str(workspace), bundle)


def _render_home_text(args: argparse.Namespace, home: dict[str, object]) -> str:
    return _render_home_text_with_deltas(
        args,
        home,
        changes=None,
        changes_by_section=None,
        changes_by_section_delta=None,
        changes_only=False,
    )


def _render_home_text_with_deltas(
    args: argparse.Namespace,
    home: dict[str, object],
    *,
    changes: list[str] | None,
    changes_by_section: dict[str, list[str]] | None,
    changes_by_section_delta: dict[str, object] | None,
    changes_only: bool,
) -> str:
    style = str(getattr(args, "style", "plain") or "plain").strip().lower()
    if style == "tui":
        tui_options = _resolve_home_tui_options(args)
        collapsed_sections = set(tui_options.get("collapsed_sections") or set())
        if changes is not None:
            collapsed_sections |= _resolve_home_watch_collapsed_sections(args)
        return render_terminal_home_tui(
            home,
            width=int(tui_options.get("width", 108) or 108),
            focus=str(tui_options.get("focus", "auto") or "auto"),
            preset=str(tui_options.get("preset", "default") or "default"),
            demo_mode=bool(getattr(args, "demo_mode", False)),
            demo_language=str(getattr(args, "demo_language", "en") or "en"),
            demo_focus=str(getattr(args, "demo_focus", "auto") or "auto"),
            demo_script=str(getattr(args, "demo_script", "full") or "full"),
            changes=changes,
            changes_by_section=changes_by_section,
            changes_by_section_delta=changes_by_section_delta,
            changes_only=changes_only,
            collapsed_sections=collapsed_sections,
        )
    return render_terminal_home_markdown(home)


def _render_doctor_snapshot(args: argparse.Namespace, workspace: Path):
    dashboard = build_runtime_dashboard(
        workspace,
        session_ref=args.session,
        session_turn_limit=args.session_turn_limit,
        background_limit=args.background_limit,
        tool_output_limit=args.tool_output_limit,
    )
    return run_runtime_doctor(dashboard)


def _render_team_board_snapshot(args: argparse.Namespace, workspace: Path) -> dict[str, object]:
    graph_path = workspace / ".mini_claw" / "task_graph.json"
    graph = TaskGraph.load(graph_path)
    return _build_team_board_payload(args, workspace, graph)


def _render_session_replay_snapshot(args: argparse.Namespace, workspace: Path):
    session_ref = str(getattr(args, "session", "")).strip()
    if not session_ref:
        return None
    manager = SessionManager(workspace)
    return replay_session(
        manager,
        session_ref,
        turn_limit=args.session_turn_limit,
    ).to_dict()


def _summarize_export_changes(
    export_target: str,
    previous: dict[str, object],
    current: dict[str, object],
) -> list[str]:
    changes_by_section = _summarize_export_changes_by_section(export_target, previous, current)
    if export_target == "bundle":
        changes: list[str] = []
        for section in ["dashboard", "doctor", "team_board", "session_replay"]:
            changes.extend(
                f"- {section}{line[1:]}" if line.startswith("-") else f"{section}: {line}"
                for line in changes_by_section.get(section, [])
            )
        return changes
    if export_target in changes_by_section:
        return list(changes_by_section[export_target])
    return []


def _summarize_export_changes_by_section(
    export_target: str,
    previous: dict[str, object],
    current: dict[str, object],
) -> dict[str, list[str]]:
    if export_target == "dashboard":
        return {
            "dashboard": summarize_dashboard_changes(
                _dashboard_from_snapshot(previous),
                _dashboard_from_snapshot(current),
            )
        }
    if export_target == "doctor":
        return {
            "doctor": summarize_doctor_changes(
                _doctor_from_snapshot(previous),
                _doctor_from_snapshot(current),
            )
        }
    if export_target == "team-board":
        return {
            "team-board": summarize_team_board_changes(previous, current),
        }
    if export_target == "bundle":
        return {
            "dashboard": summarize_dashboard_changes(
                _dashboard_from_snapshot(dict(previous.get("dashboard") or {})),
                _dashboard_from_snapshot(dict(current.get("dashboard") or {})),
            ),
            "doctor": summarize_doctor_changes(
                _doctor_from_snapshot(dict(previous.get("doctor") or {})),
                _doctor_from_snapshot(dict(current.get("doctor") or {})),
            ),
            "team_board": summarize_team_board_changes(
                dict(previous.get("team_board") or {}),
                dict(current.get("team_board") or {}),
            ),
            "session_replay": _summarize_session_replay_changes(
                previous.get("session_replay"),
                current.get("session_replay"),
            ),
        }
    return {}


def _empty_export_changes_by_section(export_target: str) -> dict[str, list[str]]:
    if export_target == "bundle":
        return {
            "dashboard": [],
            "doctor": [],
            "team_board": [],
            "session_replay": [],
        }
    if export_target == "dashboard":
        return {"dashboard": []}
    if export_target == "doctor":
        return {"doctor": []}
    if export_target == "team-board":
        return {"team-board": []}
    return {}


def _summarize_export_changes_by_section_delta(
    export_target: str,
    previous: dict[str, object],
    current: dict[str, object],
) -> dict[str, object]:
    if export_target == "dashboard":
        return {
            "dashboard": _dashboard_delta(
                _dashboard_from_snapshot(previous),
                _dashboard_from_snapshot(current),
            )
        }
    if export_target == "doctor":
        return {
            "doctor": _doctor_delta(
                _doctor_from_snapshot(previous),
                _doctor_from_snapshot(current),
            )
        }
    if export_target == "team-board":
        return {
            "team-board": summarize_team_board_changes_by_section_delta(previous, current),
        }
    if export_target == "bundle":
        return {
            "dashboard": _dashboard_delta(
                _dashboard_from_snapshot(dict(previous.get("dashboard") or {})),
                _dashboard_from_snapshot(dict(current.get("dashboard") or {})),
            ),
            "doctor": _doctor_delta(
                _doctor_from_snapshot(dict(previous.get("doctor") or {})),
                _doctor_from_snapshot(dict(current.get("doctor") or {})),
            ),
            "team_board": summarize_team_board_changes_by_section_delta(
                dict(previous.get("team_board") or {}),
                dict(current.get("team_board") or {}),
            ),
            "session_replay": _session_replay_delta(
                previous.get("session_replay"),
                current.get("session_replay"),
            ),
        }
    return {}


def _empty_export_changes_by_section_delta(export_target: str) -> dict[str, object]:
    if export_target == "bundle":
        return {
            "dashboard": _empty_dashboard_delta(),
            "doctor": _empty_doctor_delta(),
            "team_board": _empty_team_board_changes_by_section_delta(),
            "session_replay": _empty_session_replay_delta(),
        }
    if export_target == "dashboard":
        return {"dashboard": _empty_dashboard_delta()}
    if export_target == "doctor":
        return {"doctor": _empty_doctor_delta()}
    if export_target == "team-board":
        return {"team-board": _empty_team_board_changes_by_section_delta()}
    return {}


def _summarize_export_bundle_doctor_delta(
    previous: dict[str, object],
    current: dict[str, object],
) -> dict[str, dict[str, int]]:
    previous_doctor = previous.get("doctor")
    current_doctor = current.get("doctor")
    if not isinstance(previous_doctor, dict) or not isinstance(current_doctor, dict):
        return {}
    return summarize_doctor_category_delta(
        _doctor_from_snapshot(previous_doctor),
        _doctor_from_snapshot(current_doctor),
    )


def _dashboard_delta(previous, current) -> dict[str, object]:
    previous_ready = [node.task_id for node in previous.ready_tasks]
    current_ready = [node.task_id for node in current.ready_tasks]
    previous_runs = [run.run_id for run in previous.latest_background_runs]
    current_runs = [run.run_id for run in current.latest_background_runs]
    return {
        "trace": {
            "total_events": _int_delta(_trace_metric(previous.trace_summary, "total_events"), _trace_metric(current.trace_summary, "total_events")),
            "tool_calls": _int_delta(_trace_metric(previous.trace_summary, "tool_calls"), _trace_metric(current.trace_summary, "tool_calls")),
            "failed_tool_calls": _int_delta(_trace_metric(previous.trace_summary, "failed_tool_calls"), _trace_metric(current.trace_summary, "failed_tool_calls")),
        },
        "sessions": {
            "total": _int_delta(previous.session_count, current.session_count),
            "latest_turns": _int_delta(previous.latest_session_turns, current.latest_session_turns),
            "latest_session_changed": previous.latest_session_id != current.latest_session_id,
            "latest_session_previous": previous.latest_session_id or "",
            "latest_session_current": current.latest_session_id or "",
        },
        "tasks": {
            "status_counts": _count_delta(previous.task_status_counts, current.task_status_counts),
            "ready_changed": previous_ready != current_ready,
            "ready_previous": previous_ready,
            "ready_current": current_ready,
        },
        "background": {
            "status_counts": _count_delta(previous.background_status_counts, current.background_status_counts),
            "latest_runs_changed": previous_runs != current_runs,
            "latest_runs_previous": previous_runs,
            "latest_runs_current": current_runs,
        },
        "tool_outputs": {
            "total": _int_delta(previous.tool_output_count, current.tool_output_count),
            "truncated": _int_delta(previous.truncated_tool_output_count, current.truncated_tool_output_count),
        },
        "memory": {
            "candidates": _count_delta(previous.memory_candidate_status_counts, current.memory_candidate_status_counts),
            "skill_patch_eval": _count_delta(previous.skill_patch_eval_counts, current.skill_patch_eval_counts),
        },
    }


def _doctor_delta(previous, current) -> dict[str, object]:
    previous_codes = {finding.code: finding for finding in previous.findings}
    current_codes = {finding.code: finding for finding in current.findings}
    changed_codes = []
    for code in sorted(set(previous_codes) & set(current_codes)):
        prev = previous_codes[code]
        curr = current_codes[code]
        if prev.severity != curr.severity or prev.summary != curr.summary or prev.detail != curr.detail:
            changed_codes.append(code)
    return {
        "status_changed": previous.status != current.status,
        "status_previous": previous.status,
        "status_current": current.status,
        "summary_by_category": summarize_doctor_category_delta(previous, current),
        "finding_codes_added": sorted(set(current_codes) - set(previous_codes)),
        "finding_codes_removed": sorted(set(previous_codes) - set(current_codes)),
        "finding_codes_changed": changed_codes,
    }


def _session_replay_delta(previous: object, current: object) -> dict[str, object]:
    prev = dict(previous) if isinstance(previous, dict) else None
    curr = dict(current) if isinstance(current, dict) else None
    if prev is None and curr is None:
        return _empty_session_replay_delta()
    if prev is None:
        return {
            "enabled_changed": True,
            "previous_present": False,
            "current_present": True,
            "session_id_previous": "",
            "session_id_current": str(curr.get("session_id", "") or ""),
            "total_turns": int(curr.get("total_turns", 0) or 0),
            "completed_turns": int(curr.get("completed_turns", 0) or 0),
            "successful_turns": int(curr.get("successful_turns", 0) or 0),
            "failed_turns": int(curr.get("failed_turns", 0) or 0),
            "tool_calls": int(curr.get("tool_calls", 0) or 0),
        }
    if curr is None:
        return {
            "enabled_changed": True,
            "previous_present": True,
            "current_present": False,
            "session_id_previous": str(prev.get("session_id", "") or ""),
            "session_id_current": "",
            "total_turns": -int(prev.get("total_turns", 0) or 0),
            "completed_turns": -int(prev.get("completed_turns", 0) or 0),
            "successful_turns": -int(prev.get("successful_turns", 0) or 0),
            "failed_turns": -int(prev.get("failed_turns", 0) or 0),
            "tool_calls": -int(prev.get("tool_calls", 0) or 0),
        }
    return {
        "enabled_changed": False,
        "previous_present": True,
        "current_present": True,
        "session_id_previous": str(prev.get("session_id", "") or ""),
        "session_id_current": str(curr.get("session_id", "") or ""),
        "session_id_changed": prev.get("session_id") != curr.get("session_id"),
        "total_turns": _int_delta(prev.get("total_turns", 0), curr.get("total_turns", 0)),
        "completed_turns": _int_delta(prev.get("completed_turns", 0), curr.get("completed_turns", 0)),
        "successful_turns": _int_delta(prev.get("successful_turns", 0), curr.get("successful_turns", 0)),
        "failed_turns": _int_delta(prev.get("failed_turns", 0), curr.get("failed_turns", 0)),
        "tool_calls": _int_delta(prev.get("tool_calls", 0), curr.get("tool_calls", 0)),
    }


def _empty_dashboard_delta() -> dict[str, object]:
    return {
        "trace": {"total_events": 0, "tool_calls": 0, "failed_tool_calls": 0},
        "sessions": {
            "total": 0,
            "latest_turns": 0,
            "latest_session_changed": False,
            "latest_session_previous": "",
            "latest_session_current": "",
        },
        "tasks": {
            "status_counts": {},
            "ready_changed": False,
            "ready_previous": [],
            "ready_current": [],
        },
        "background": {
            "status_counts": {},
            "latest_runs_changed": False,
            "latest_runs_previous": [],
            "latest_runs_current": [],
        },
        "tool_outputs": {"total": 0, "truncated": 0},
        "memory": {"candidates": {}, "skill_patch_eval": {}},
    }


def _empty_doctor_delta() -> dict[str, object]:
    return {
        "status_changed": False,
        "status_previous": "",
        "status_current": "",
        "summary_by_category": {},
        "finding_codes_added": [],
        "finding_codes_removed": [],
        "finding_codes_changed": [],
    }


def _empty_session_replay_delta() -> dict[str, object]:
    return {
        "enabled_changed": False,
        "previous_present": False,
        "current_present": False,
        "session_id_previous": "",
        "session_id_current": "",
        "total_turns": 0,
        "completed_turns": 0,
        "successful_turns": 0,
        "failed_turns": 0,
        "tool_calls": 0,
    }


def _int_delta(previous: object, current: object) -> int:
    return int(current or 0) - int(previous or 0)


def _count_delta(previous: dict[str, int], current: dict[str, int]) -> dict[str, int]:
    keys = sorted(set(previous) | set(current))
    return {
        key: int(current.get(key, 0) or 0) - int(previous.get(key, 0) or 0)
        for key in keys
        if int(current.get(key, 0) or 0) - int(previous.get(key, 0) or 0)
    }


def _trace_metric(summary: object, name: str) -> int:
    if summary is None:
        return 0
    return int(getattr(summary, name, 0) or 0)


def _dashboard_from_snapshot(snapshot: dict[str, object]):
    class _DashboardAdapter:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        @property
        def session_count(self) -> int:
            return int(self.payload.get("session_count", 0) or 0)

        @property
        def latest_session_id(self) -> str:
            return str(self.payload.get("latest_session_id", "") or "")

        @property
        def latest_session_turns(self) -> int:
            return int(self.payload.get("latest_session_turns", 0) or 0)

        @property
        def task_status_counts(self) -> dict[str, int]:
            return {str(k): int(v) for k, v in dict(self.payload.get("task_status_counts") or {}).items()}

        @property
        def ready_tasks(self) -> list[object]:
            nodes = []
            for node in list(self.payload.get("ready_tasks") or []):
                task_id = str(dict(node).get("task_id", "") or "")
                nodes.append(type("ReadyTask", (), {"task_id": task_id})())
            return nodes

        @property
        def background_status_counts(self) -> dict[str, int]:
            return {str(k): int(v) for k, v in dict(self.payload.get("background_status_counts") or {}).items()}

        @property
        def latest_background_runs(self) -> list[object]:
            runs = []
            for run in list(self.payload.get("latest_background_runs") or []):
                run_id = str(dict(run).get("run_id", "") or "")
                runs.append(type("BackgroundRun", (), {"run_id": run_id})())
            return runs

        @property
        def tool_output_count(self) -> int:
            return int(self.payload.get("tool_output_count", 0) or 0)

        @property
        def truncated_tool_output_count(self) -> int:
            return int(self.payload.get("truncated_tool_output_count", 0) or 0)

        @property
        def memory_candidate_status_counts(self) -> dict[str, int]:
            return {
                str(k): int(v)
                for k, v in dict(self.payload.get("memory_candidate_status_counts") or {}).items()
            }

        @property
        def skill_patch_eval_counts(self) -> dict[str, int]:
            return {str(k): int(v) for k, v in dict(self.payload.get("skill_patch_eval_counts") or {}).items()}

        @property
        def trace_summary(self):
            payload = self.payload.get("trace_summary")
            if not isinstance(payload, dict):
                return None
            return type(
                "TraceSummary",
                (),
                {
                    "total_events": int(payload.get("total_events", 0) or 0),
                    "tool_calls": int(payload.get("tool_calls", 0) or 0),
                    "failed_tool_calls": int(payload.get("failed_tool_calls", 0) or 0),
                },
            )()

    return _DashboardAdapter(snapshot)


def _doctor_from_snapshot(snapshot: dict[str, object]):
    class _FindingAdapter:
        def __init__(self, payload: dict[str, object]) -> None:
            self.code = str(payload.get("code", "") or "")
            self.severity = str(payload.get("severity", "") or "")
            self.category = str(payload.get("category", "") or "")
            self.summary = str(payload.get("summary", "") or "")
            self.detail = str(payload.get("detail", "") or "")

    class _DoctorAdapter:
        def __init__(self, payload: dict[str, object]) -> None:
            self.status = str(payload.get("status", "") or "")
            self.summary = str(payload.get("summary", "") or "")
            self.summary_by_category = {
                str(category): {str(level): int(count) for level, count in dict(counts).items()}
                for category, counts in dict(payload.get("summary_by_category") or {}).items()
            }
            self.findings = [_FindingAdapter(dict(item)) for item in list(payload.get("findings") or [])]

    return _DoctorAdapter(snapshot)


def _summarize_session_replay_changes(
    previous: object,
    current: object,
) -> list[str]:
    prev = dict(previous) if isinstance(previous, dict) else None
    curr = dict(current) if isinstance(current, dict) else None
    changes: list[str] = []
    if prev is None and curr is None:
        return changes
    if prev is None and curr is not None:
        changes.append(f"- session_replay: enabled ({curr.get('session_id', '(unknown)')})")
        return changes
    if prev is not None and curr is None:
        changes.append(f"- session_replay: removed ({prev.get('session_id', '(unknown)')})")
        return changes
    assert prev is not None and curr is not None
    for key in ["session_id", "total_turns", "completed_turns", "successful_turns", "failed_turns", "tool_calls"]:
        if prev.get(key) != curr.get(key):
            changes.append(f"- session_replay.{key}: {prev.get(key)} -> {curr.get(key)}")
    return changes


def _parse_doctor_codes(raw: str) -> set[str]:
    return {item.strip() for item in str(raw).split(",") if item.strip()}


def _parse_home_sections(raw: str) -> set[str]:
    values = {item.strip().lower() for item in str(raw).split(",") if item.strip()}
    return {item for item in values if item in HOME_TUI_SECTION_IDS}


def _resolve_home_tui_options(args: argparse.Namespace) -> dict[str, object]:
    preset = str(getattr(args, "preset", "default") or "default").strip().lower() or "default"
    resolved = resolve_home_tui_preset(preset)
    raw_focus = str(getattr(args, "focus", "") or "").strip().lower()
    if preset == "default":
        resolved["focus"] = raw_focus or str(resolved.get("focus", "auto") or "auto")
    elif raw_focus and raw_focus != "auto":
        resolved["focus"] = raw_focus
    raw_width = int(getattr(args, "width", 0) or 0)
    if preset == "default":
        if raw_width > 0:
            resolved["width"] = raw_width
    elif raw_width > 0 and raw_width != 108:
        resolved["width"] = raw_width
    raw_collapse = _parse_home_sections(getattr(args, "collapse", ""))
    if raw_collapse:
        resolved["collapsed_sections"] = raw_collapse
    return resolved


def _resolve_home_watch_changes_only(args: argparse.Namespace) -> bool:
    if bool(getattr(args, "changes_only", False)):
        return True
    style = str(getattr(args, "style", "plain") or "plain").strip().lower()
    if style != "tui":
        return False
    watch_layout = str(getattr(args, "watch_layout", "default") or "default").strip().lower()
    if watch_layout == "delta":
        return True
    if watch_layout == "full":
        return False
    tui_options = _resolve_home_tui_options(args)
    return str(tui_options.get("watch_layout", "full") or "full") == "delta"


def _resolve_home_watch_collapsed_sections(args: argparse.Namespace) -> set[str]:
    style = str(getattr(args, "style", "plain") or "plain").strip().lower()
    if style != "tui":
        return set()
    watch_layout = str(getattr(args, "watch_layout", "default") or "default").strip().lower()
    if watch_layout in {"full", "delta"}:
        return set()
    tui_options = _resolve_home_tui_options(args)
    return set(tui_options.get("watch_collapsed_sections") or set())


def _resolve_output_path(workspace: Path, output_file: str) -> Path | None:
    text = str(output_file).strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = workspace / path
    return path.resolve()


def _write_output_file(path: Path | None, text: str, *, append: bool) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.write("\n")


def _filter_doctor_report(
    report,
    ignore_codes: set[str],
    *,
    category_codes: set[str],
    min_severity: str,
    sort_by: str,
):
    if not ignore_codes and not category_codes and min_severity == "info" and sort_by == "default":
        return report
    severity_rank = {"info": 0, "warn": 1, "fail": 2}
    threshold = severity_rank.get(min_severity, 0)
    findings = [
        finding
        for finding in report.findings
        if finding.code not in ignore_codes
        and (not category_codes or finding.category in category_codes)
        and severity_rank.get(finding.severity, 0) >= threshold
    ]
    findings = _sort_doctor_findings(findings, sort_by=sort_by)
    status = "ok"
    if any(finding.severity == "fail" for finding in findings):
        status = "fail"
    elif any(finding.severity == "warn" for finding in findings):
        status = "warn"
    summary = (
        f"{status.upper()} with "
        f"{sum(1 for finding in findings if finding.severity == 'fail')} fail, "
        f"{sum(1 for finding in findings if finding.severity == 'warn')} warn, "
        f"and {sum(1 for finding in findings if finding.severity == 'info')} info finding(s)."
    )
    return report.__class__(
        workspace=report.workspace,
        status=status,
        summary=summary,
        summary_by_category=_summarize_findings_by_category(findings),
        findings=findings,
    )


def _sort_doctor_findings(findings, *, sort_by: str):
    if sort_by == "default":
        return findings
    severity_order = {"fail": 0, "warn": 1, "info": 2}
    if sort_by == "severity":
        return sorted(
            findings,
            key=lambda finding: (
                severity_order.get(finding.severity, 99),
                finding.category,
                finding.code,
            ),
        )
    if sort_by == "category":
        return sorted(
            findings,
            key=lambda finding: (
                finding.category,
                severity_order.get(finding.severity, 99),
                finding.code,
            ),
        )
    if sort_by == "code":
        return sorted(
            findings,
            key=lambda finding: (
                finding.code,
                severity_order.get(finding.severity, 99),
                finding.category,
            ),
        )
    return findings


def _summarize_findings_by_category(findings) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for finding in findings:
        bucket = summary.setdefault(finding.category, {"fail": 0, "warn": 0, "info": 0})
        bucket[finding.severity] = bucket.get(finding.severity, 0) + 1
    return summary


def _doctor_exit_code(
    report,
    *,
    strict_warnings: bool,
    fail_on_codes: set[str],
) -> int:
    if report.exit_code(strict_warnings=strict_warnings) != 0:
        return 1
    if not fail_on_codes:
        return 0
    report_codes = {finding.code for finding in report.findings}
    return 1 if report_codes & fail_on_codes else 0


def cmd_index(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    print(
        render_file_index(
            workspace=workspace,
            query=args.query,
            limit=args.limit,
            preview_lines=args.preview_lines,
        )
    )
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    roots = [workspace / ".mini_claw" / "skills"]
    if args.include_examples:
        roots.append(workspace / "examples")
    skills = SkillLoader(roots).load()
    if args.skills_command == "list":
        for skill in skills:
            triggers = ", ".join(skill.contract.triggers) or "-"
            tools = ", ".join(skill.contract.allowed_tools) or "-"
            print(f"{skill.name}\ttriggers={triggers}\tallowed_tools={tools}\tpath={skill.path}")
        return 0
    if args.skills_command == "match":
        for skill in select_relevant_skills(skills, query=args.query, limit=args.limit):
            print(skill.to_prompt())
            print()
        return 0
    raise ValueError(f"Unknown skills command: {args.skills_command}")


def cmd_memory(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    memory = MemoryStore(workspace / ".mini_claw" / "memory")
    if args.memory_command == "candidates":
        candidates = memory.read_memory_candidates(
            kind_filter=args.kind,
            status_filter=args.status,
            query=args.query,
            limit=args.limit,
        )
        if not candidates:
            print("(no memory candidates)")
            return 0
        for index, candidate in enumerate(candidates, start=1):
            print(f"## Candidate {index}: {candidate.get('candidate_id')}")
            print(f"status: {candidate.get('status')}")
            print(f"kind: {candidate.get('kind')}")
            print(f"source: {candidate.get('source')}")
            print(f"confidence: {candidate.get('confidence')}")
            if candidate.get("decision_reason"):
                print(f"decision_reason: {candidate.get('decision_reason')}")
            print(f"tags: {', '.join(candidate.get('tags', []))}")
            print(candidate.get("content", "").strip())
            print()
        return 0
    if args.memory_command == "promote":
        candidate = memory.promote_memory_candidate(args.ref, reason=args.reason)
        print(f"promoted {candidate['candidate_id']}")
        if candidate.get("artifact_path"):
            print(f"skill_patch_artifact: {candidate.get('artifact_path')}")
        return 0
    if args.memory_command == "reject":
        candidate = memory.reject_memory_candidate(args.ref, reason=args.reason)
        print(f"rejected {candidate['candidate_id']}")
        return 0
    if args.memory_command == "skill-patches":
        artifacts = memory.read_skill_patch_artifacts(query=args.query, limit=args.limit)
        if not artifacts:
            print("(no skill patch artifacts)")
            return 0
        for index, artifact in enumerate(artifacts, start=1):
            print(
                f"{index}\t{artifact.get('artifact_id')}\t"
                f"candidate={artifact.get('candidate_id')}\t"
                f"target_skill={artifact.get('target_skill')}\t"
                f"eval_status={artifact.get('eval_status') or 'pending'}\t"
                f"path={artifact.get('artifact_path')}"
            )
        return 0
    if args.memory_command == "skill-patch-show":
        artifact = memory.read_skill_patch_artifact(args.ref)
        print(artifact.get("content", "").rstrip())
        return 0
    if args.memory_command == "skill-patch-verify":
        artifact = memory.read_skill_patch_artifact(args.ref)
        command = str(args.command).strip()
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=workspace,
                text=True,
                capture_output=True,
                timeout=args.timeout,
            )
            output = "\n".join(
                part
                for part in [
                    f"$ {command}",
                    completed.stdout.strip(),
                    completed.stderr.strip(),
                    f"exit_code={completed.returncode}",
                ]
                if part
            )
            exit_code = completed.returncode
            ok = completed.returncode == 0
        except subprocess.TimeoutExpired:
            output = f"$ {command}\nCommand timed out after {args.timeout}s."
            exit_code = 124
            ok = False
        result = memory.record_skill_patch_eval_result(
            str(artifact.get("artifact_id", args.ref)),
            command=command,
            ok=ok,
            exit_code=exit_code,
            output=output,
        )
        print(
            f"skill_patch_eval {result.get('eval_id')} "
            f"status={result.get('status')} exit_code={result.get('exit_code')}"
        )
        return 0 if ok else 1
    if args.memory_command == "skill-patch-preview":
        artifact = memory.read_skill_patch_artifact(args.ref)
        skill_path_text = str(artifact.get("skill_path", "")).strip()
        if not skill_path_text or skill_path_text == "(unknown)":
            raise ValueError("Skill patch artifact does not include a usable skill_path.")
        skill_path = (workspace / skill_path_text).resolve()
        if not _is_relative_to(skill_path, workspace):
            raise ValueError(f"Skill path escapes workspace: {skill_path_text}")
        if not skill_path.exists():
            raise ValueError(f"Skill file does not exist: {skill_path_text}")
        preview = build_skill_patch_apply_preview(
            current_content=skill_path.read_text(encoding="utf-8"),
            artifact=artifact,
        )
        memory.append_event(
            RuntimeEvent(
                "skill_patch_apply_previewed",
                {
                    "artifact_id": artifact.get("artifact_id", ""),
                    "candidate_id": artifact.get("candidate_id", ""),
                    "skill_path": skill_path_text,
                    "target_skill": preview.target_skill,
                },
            )
        )
        print(preview.diff.rstrip())
        return 0
    raise ValueError(f"Unknown memory command: {args.memory_command}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def cmd_tool_output(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    memory = MemoryStore(workspace / ".mini_claw" / "memory")
    if args.tool_output_command == "list":
        records = memory.list_tool_outputs(limit=args.limit)
        if not records:
            print("(no tool outputs)")
            return 0
        for index, record in enumerate(records, start=1):
            truncated = bool(record.get("truncated")) or bool(record.get("store_truncated"))
            print(
                f"{index}\t{record.get('output_id')}\ttool={record.get('tool')}\t"
                f"ok={record.get('ok')}\tchars={record.get('output_chars')}\t"
                f"truncated={truncated}"
            )
        return 0
    if args.tool_output_command == "show":
        record = memory.read_tool_output(args.ref)
        print(f"## {record.get('output_id')} [{record.get('tool')}] ok={record.get('ok')}")
        print(
            f"chars: {record.get('output_chars')} "
            f"stored_chars: {record.get('stored_output_chars')} "
            f"truncated: {record.get('truncated')} "
            f"store_truncated: {record.get('store_truncated')}"
        )
        modified_files = record.get("modified_files", [])
        if modified_files:
            print(f"modified_files: {', '.join(str(item) for item in modified_files)}")
        print(f"lookup_hint: {record.get('lookup_hint')}")
        lookup_plan = record.get("lookup_plan", {})
        if isinstance(lookup_plan, dict):
            hints = lookup_plan.get("hints", [])
            if isinstance(hints, list) and hints:
                print("lookup_plan:")
                for index, hint in enumerate(hints, start=1):
                    if not isinstance(hint, dict):
                        continue
                    print(
                        "  "
                        f"{index}. kind={hint.get('kind', '')} "
                        f"query={hint.get('query', '')} "
                        f"line_range={hint.get('line_start', 1)}:{hint.get('line_end', 'end')} "
                        f"reason={hint.get('reason', '')} "
                        f"score={hint.get('score', '')}"
                    )
        print("args:")
        print(json.dumps(record.get("args", {}), ensure_ascii=False, indent=2))
        metadata = record.get("metadata", {})
        if metadata:
            print("metadata:")
            print(json.dumps(metadata, ensure_ascii=False, indent=2))
        print("output:")
        print(record.get("output", ""))
        return 0
    raise ValueError(f"Unknown tool output command: {args.tool_output_command}")


def cmd_todo(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    graph_path = workspace / ".mini_claw" / "task_graph.json"
    graph = TaskGraph.load(graph_path)
    if args.todo_command == "add":
        task_id = args.task_id or f"task-{len(graph.nodes) + 1}"
        graph.add(
            TaskNode(
                task_id=task_id,
                objective=args.objective,
                owner_role=args.owner_role,
                dependencies=args.depends_on,
                context_refs=args.context_ref,
                verification_command=args.verify,
            )
        )
        graph.save(graph_path)
        print(f"added {task_id}")
        return 0
    if args.todo_command == "list":
        for node in graph.nodes.values():
            deps = ",".join(node.dependencies) or "-"
            workspace_ref = node.workspace_path or "-"
            background_runs = len(node.background_run_ids)
            print(
                f"{node.task_id}\t{node.status}\t{node.owner_role}\t"
                f"deps={deps}\tworkspace={workspace_ref}\tbg={background_runs}\t{node.objective}"
            )
        return 0
    if args.todo_command == "ready":
        for node in graph.ready():
            print(f"{node.task_id}\t{node.owner_role}\t{node.objective}")
        return 0
    if args.todo_command == "show":
        node = graph.nodes[args.task_id]
        print(f"task_id: {node.task_id}")
        print(f"objective: {node.objective}")
        print(f"status: {node.status}")
        print(f"owner_role: {node.owner_role}")
        print(f"dependencies: {', '.join(node.dependencies) or '-'}")
        print(f"context_refs: {', '.join(node.context_refs) or '-'}")
        print(f"verification_command: {node.verification_command or '-'}")
        print(f"workspace_path: {node.workspace_path or '-'}")
        print(f"background_runs: {', '.join(node.background_run_ids) or '-'}")
        print("notes:")
        print(node.notes.strip() or "(none)")
        return 0
    if args.todo_command == "note":
        graph.append_note(args.task_id, args.note)
        graph.save(graph_path)
        print(f"noted {args.task_id}")
        return 0
    if args.todo_command == "status":
        graph.set_status(args.task_id, args.status)
        graph.save(graph_path)
        print(f"{args.task_id} -> {args.status}")
        return 0
    raise ValueError(f"Unknown todo command: {args.todo_command}")


def cmd_background(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    memory = MemoryStore(workspace / ".mini_claw" / "memory")
    manager = BackgroundRunManager(workspace, memory=memory)
    if args.background_command == "start":
        task_id = str(args.task_id).strip()
        if task_id:
            graph_path = workspace / ".mini_claw" / "task_graph.json"
            graph = TaskGraph.load(graph_path)
            if task_id not in graph.nodes:
                raise ValueError(f"Unknown task_id for background run: {task_id}")
            run = manager.start(args.command, label=args.label, task_id=task_id)
            graph.attach_background_run(task_id, run.run_id)
            note = f"background run started: {run.run_id}"
            if args.label:
                note += f" label={args.label}"
            note += f" command={args.command}"
            graph.append_note(task_id, note)
            graph.save(graph_path)
        else:
            run = manager.start(args.command, label=args.label, task_id="")
        print(
            f"started {run.run_id}\tstatus={run.status}\t"
            f"task={run.task_id or '-'}\tlabel={run.label or '-'}"
        )
        return 0
    if args.background_command == "list":
        records = manager.list_runs(limit=args.limit, status_filter=args.status)
        if not records:
            print("(no background runs)")
            return 0
        for index, run in enumerate(records, start=1):
            print(
                f"{index}\t{run.run_id}\tstatus={run.status}\t"
                f"task={run.task_id or '-'}\tlabel={run.label or '-'}\t{run.command}"
            )
        return 0
    if args.background_command == "show":
        run = manager.read_run(args.ref)
        _print_background_run(manager, run, tail_chars=args.tail_chars)
        return 0
    if args.background_command == "wait":
        try:
            run = manager.wait(
                args.ref,
                timeout_seconds=float(args.timeout),
                poll_interval=float(args.poll_interval),
            )
        except TimeoutError as exc:
            print(str(exc))
            return 1
        _print_background_run(manager, run, tail_chars=args.tail_chars)
        return 0 if run.status == "succeeded" else 1
    raise ValueError(f"Unknown background command: {args.background_command}")


def _print_background_run(
    manager: BackgroundRunManager,
    run,
    *,
    tail_chars: int,
) -> None:
    tails = manager.output_tail(run.run_id, max_chars=tail_chars)
    print(f"run_id: {run.run_id}")
    print(f"status: {run.status}")
    print(f"command: {run.command}")
    print(f"task_id: {run.task_id or '-'}")
    print(f"label: {run.label or '-'}")
    print(f"created_at: {run.created_at}")
    print(f"started_at: {run.started_at or '-'}")
    print(f"finished_at: {run.finished_at or '-'}")
    print(f"exit_code: {run.exit_code if run.exit_code is not None else '-'}")
    print(f"runner_pid: {run.runner_pid if run.runner_pid is not None else '-'}")
    print("stdout:")
    print(tails["stdout"].rstrip() or "(empty)")
    print("stderr:")
    print(tails["stderr"].rstrip() or "(empty)")


def cmd_workspace(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    manager = TaskWorkspaceManager(workspace)
    graph_path = workspace / ".mini_claw" / "task_graph.json"
    graph = TaskGraph.load(graph_path)
    if args.workspace_command == "create":
        mode = getattr(args, "mode", "copy")
        task_workspace = manager.create(args.task_id, mode=mode)
        if args.task_id in graph.nodes:
            graph.attach_workspace(args.task_id, task_workspace.path)
            graph.save(graph_path)
        print(f"created {task_workspace.task_id}: {task_workspace.path} mode={task_workspace.mode}")
        return 0
    if args.workspace_command == "list":
        entries = manager.list()
        if not entries:
            print("(no task workspaces)")
            return 0
        for entry in entries:
            linked = "yes" if entry.task_id in graph.nodes and graph.nodes[entry.task_id].workspace_path else "no"
            print(f"{entry.task_id}\tmode={entry.mode}\tlinked={linked}\t{entry.path}")
        return 0
    if args.workspace_command == "diff":
        summaries = manager.diff(args.task_id)
        if not summaries:
            print("(no changes)")
            return 0
        for summary in summaries:
            print(
                f"## {summary.path} [{summary.status}] "
                f"+{summary.added_lines}/-{summary.removed_lines}"
            )
            if args.show_diff:
                print(summary.unified_diff)
        return 0
    if args.workspace_command == "merge":
        verification_commands = list(args.verify)
        task_node = graph.nodes.get(args.task_id)
        if not args.skip_task_verify and task_node and task_node.verification_command:
            verification_commands.insert(0, task_node.verification_command)
        result = manager.merge(
            args.task_id,
            verification_commands=verification_commands,
            rollback_on_verification_failure=args.rollback_on_verification_failure,
            dry_run=args.dry_run,
        )
        print(result.output)
        if result.conflicts:
            for conflict in result.conflicts:
                print(f"conflict\t{conflict.path}\t{conflict.reason}")
        if args.show_diff and result.diff_summary:
            for summary in result.diff_summary:
                print(
                    f"## {summary.path} [{summary.status}] "
                    f"+{summary.added_lines}/-{summary.removed_lines}"
                )
                print(summary.unified_diff)
        return 0 if result.ok else 1
    raise ValueError(f"Unknown workspace command: {args.workspace_command}")


def cmd_orchestrate(args: argparse.Namespace) -> int:
    return _run_team_orchestration(args, output_style="orchestrate")


def cmd_team(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    graph_path = workspace / ".mini_claw" / "task_graph.json"
    graph = TaskGraph.load(graph_path)
    if args.team_command == "board":
        output_path = _resolve_output_path(workspace, getattr(args, "output_file", ""))
        if not getattr(args, "watch", False):
            board = _build_team_board_payload(args, workspace, graph)
            if args.json:
                text = json.dumps(board, ensure_ascii=False, indent=2)
                print(text)
                _write_output_file(output_path, text, append=False)
                return 0
            print(_render_team_board_markdown(board))
            return 0
        iteration = 0
        max_iterations = max(int(args.iterations), 0)
        previous_board = None
        try:
            while True:
                iteration += 1
                graph = TaskGraph.load(graph_path)
                board = _build_team_board_payload(args, workspace, graph)
                changes: list[str] = []
                changes_by_section = _empty_team_board_changes_by_section()
                if args.json:
                    if previous_board is not None:
                        changes = summarize_team_board_changes(previous_board, board)
                        changes_by_section = summarize_team_board_changes_by_section(previous_board, board)
                        changes_by_section_delta = summarize_team_board_changes_by_section_delta(
                            previous_board,
                            board,
                        )
                    else:
                        changes_by_section_delta = _empty_team_board_changes_by_section_delta()
                    payload = {
                        "iteration": iteration,
                        "changes": changes,
                        "changes_by_section": changes_by_section,
                        "changes_by_section_delta": changes_by_section_delta,
                        "board": board,
                    }
                    text = json.dumps(payload, ensure_ascii=False)
                    print(text)
                    _write_output_file(output_path, text, append=True)
                    previous_board = board
                    if max_iterations and iteration >= max_iterations:
                        break
                    time.sleep(max(float(args.interval), 0.0))
                    continue
                if not args.no_clear:
                    print("\x1bc", end="")
                if iteration > 1:
                    print()
                print(f"# Team Board Watch {iteration}")
                print()
                if previous_board is not None:
                    print("## Changes Since Last Refresh")
                    changes = summarize_team_board_changes(previous_board, board)
                    if changes:
                        for line in changes:
                            print(line)
                    else:
                        print("- no team-board state changes detected")
                    print()
                if not args.changes_only or previous_board is None:
                    print(_render_team_board_markdown(board))
                elif changes:
                    print("(full team board hidden by --changes-only)")
                else:
                    print("(no team board changes to display)")
                previous_board = board
                if max_iterations and iteration >= max_iterations:
                    break
                time.sleep(max(float(args.interval), 0.0))
        except KeyboardInterrupt:
            return 130
        return 0
    if args.team_command == "status":
        if args.json:
            print(
                json.dumps(
                    _build_team_status_payload(workspace, graph),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        print(_render_team_status_markdown(workspace, graph))
        return 0
    if args.team_command == "run":
        return _run_team_orchestration(args, output_style="team")
    raise ValueError(f"Unknown team command: {args.team_command}")


def _run_team_orchestration(args: argparse.Namespace, *, output_style: str) -> int:
    workspace = Path(args.workspace).resolve()
    graph_path = workspace / ".mini_claw" / "task_graph.json"
    graph = TaskGraph.load(graph_path)
    ready_before = [node.task_id for node in graph.ready()]
    memory = MemoryStore(workspace / ".mini_claw" / "memory")
    manager = TaskWorkspaceManager(workspace)
    coder_runner = _build_orchestrator_coder_runner(args, memory) if args.run_coder_agent else None
    report = run_task_graph_orchestration(
        workspace=workspace,
        graph=graph,
        workspace_manager=manager,
        memory=memory,
        mode=args.mode,
        limit=args.limit,
        dry_run=args.dry_run,
        rollback_on_verification_failure=args.rollback_on_verification_failure,
        coder_runner=coder_runner,
    )
    graph.save(graph_path)
    if output_style == "team":
        if getattr(args, "json", False):
            print(
                json.dumps(
                    _build_team_run_payload(
                        workspace=workspace,
                        graph=graph,
                        report=report,
                        mode=args.mode,
                        limit=args.limit,
                        ready_before=ready_before,
                        dry_run=args.dry_run,
                        run_coder_agent=args.run_coder_agent,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(
                _render_team_run_markdown(
                    workspace=workspace,
                    graph=graph,
                    report=report,
                    mode=args.mode,
                    limit=args.limit,
                    ready_before=ready_before,
                    dry_run=args.dry_run,
                    run_coder_agent=args.run_coder_agent,
                )
            )
    else:
        print(report.to_markdown())
    return 0 if report.failed == 0 else 1


def _build_team_status_payload(workspace: Path, graph: TaskGraph) -> dict[str, object]:
    status_counts: dict[str, int] = {}
    for node in graph.nodes.values():
        status_counts[node.status] = status_counts.get(node.status, 0) + 1
    return {
        "workspace": str(workspace),
        "task_count": len(graph.nodes),
        "status_counts": status_counts,
        "ready_tasks": [
            {
                "task_id": node.task_id,
                "objective": node.objective,
                "owner_role": node.owner_role,
                "verification_command": node.verification_command,
            }
            for node in graph.ready()
        ],
        "blocked_tasks": [
            {
                "task_id": node.task_id,
                "dependencies": node.dependencies,
                "notes": node.notes,
            }
            for node in graph.nodes.values()
            if node.status == "blocked"
        ],
        "active_tasks": [
            {
                "task_id": node.task_id,
                "status": node.status,
                "owner_role": node.owner_role,
                "workspace_path": node.workspace_path,
            }
            for node in graph.nodes.values()
            if node.status in {"pending", "in_progress", "blocked"}
        ],
    }


def _render_team_status_markdown(workspace: Path, graph: TaskGraph) -> str:
    payload = _build_team_status_payload(workspace, graph)
    status_counts = dict(payload["status_counts"])
    lines = [
        "# Mini Claw Team Status",
        "",
        f"- workspace: {payload['workspace']}",
        f"- task_count: {payload['task_count']}",
        f"- pending: {status_counts.get('pending', 0)}",
        f"- in_progress: {status_counts.get('in_progress', 0)}",
        f"- blocked: {status_counts.get('blocked', 0)}",
        f"- done: {status_counts.get('done', 0)}",
        f"- failed: {status_counts.get('failed', 0)}",
        "",
        "## Ready Tasks",
    ]
    ready_tasks = list(payload["ready_tasks"])
    if not ready_tasks:
        lines.append("(none)")
    else:
        for item in ready_tasks:
            detail = f"- {item['task_id']}: {item['objective']}"
            if item["verification_command"]:
                detail += f" verify={item['verification_command']}"
            lines.append(detail)
    lines.extend(["", "## Active Tasks"])
    active_tasks = list(payload["active_tasks"])
    if not active_tasks:
        lines.append("(none)")
    else:
        for item in active_tasks:
            lines.append(
                f"- {item['task_id']} [{item['status']}] owner={item['owner_role']} "
                f"workspace={item['workspace_path'] or '-'}"
            )
    lines.extend(["", "## Blocked Tasks"])
    blocked_tasks = list(payload["blocked_tasks"])
    if not blocked_tasks:
        lines.append("(none)")
    else:
        for item in blocked_tasks:
            lines.append(
                f"- {item['task_id']} deps={','.join(item['dependencies']) or '-'} "
                f"notes={item['notes'] or '-'}"
            )
    return "\n".join(lines)


def _build_team_run_payload(
    *,
    workspace: Path,
    graph: TaskGraph,
    report,
    mode: str,
    limit: int,
    ready_before: list[str],
    dry_run: bool,
    run_coder_agent: bool,
) -> dict[str, object]:
    return {
        "workspace": str(workspace),
        "mode": mode,
        "limit": limit,
        "dry_run": dry_run,
        "run_coder_agent": run_coder_agent,
        "ready_before": ready_before,
        "ready_after": [node.task_id for node in graph.ready()],
        "processed": report.processed,
        "passed": report.passed,
        "failed": report.failed,
        "steps": [step.to_dict() for step in report.steps],
        "task_status_counts": _build_team_status_payload(workspace, graph)["status_counts"],
    }


def _render_team_run_markdown(
    *,
    workspace: Path,
    graph: TaskGraph,
    report,
    mode: str,
    limit: int,
    ready_before: list[str],
    dry_run: bool,
    run_coder_agent: bool,
) -> str:
    payload = _build_team_run_payload(
        workspace=workspace,
        graph=graph,
        report=report,
        mode=mode,
        limit=limit,
        ready_before=ready_before,
        dry_run=dry_run,
        run_coder_agent=run_coder_agent,
    )
    status_counts = dict(payload["task_status_counts"])
    lines = [
        "# Mini Claw Team Run",
        "",
        f"- workspace: {payload['workspace']}",
        f"- mode: {payload['mode']}",
        f"- limit: {payload['limit']}",
        f"- dry_run: {payload['dry_run']}",
        f"- run_coder_agent: {payload['run_coder_agent']}",
        f"- ready_before: {', '.join(payload['ready_before']) or '(none)'}",
        f"- ready_after: {', '.join(payload['ready_after']) or '(none)'}",
        f"- processed: {payload['processed']}",
        f"- passed: {payload['passed']}",
        f"- failed: {payload['failed']}",
        "",
        "## Handoff Flow",
    ]
    for step in report.steps:
        lines.append(f"- {step.task_id} [{step.role}] {step.status}: {step.detail}")
    lines.extend(
        [
            "",
            "## Task Status Counts",
            f"- pending: {status_counts.get('pending', 0)}",
            f"- in_progress: {status_counts.get('in_progress', 0)}",
            f"- blocked: {status_counts.get('blocked', 0)}",
            f"- done: {status_counts.get('done', 0)}",
            f"- failed: {status_counts.get('failed', 0)}",
        ]
    )
    return "\n".join(lines)


def _build_team_board_payload(
    args: argparse.Namespace,
    workspace: Path,
    graph: TaskGraph,
) -> dict[str, object]:
    team_status = _build_team_status_payload(workspace, graph)
    dashboard = build_runtime_dashboard(
        workspace,
        session_ref=getattr(args, "session", ""),
        session_turn_limit=getattr(args, "session_turn_limit", 20),
        background_limit=getattr(args, "background_limit", 5),
        tool_output_limit=getattr(args, "tool_output_limit", 5),
    )
    doctor = run_runtime_doctor(dashboard)
    trace_summary = dashboard.trace_summary
    latest_session = None
    if dashboard.latest_session_id:
        latest_session = {
            "session_id": dashboard.latest_session_id,
            "name": dashboard.latest_session_name,
            "turn_count": dashboard.latest_session_turns,
        }
    latest_replay = None
    if dashboard.latest_session_replay is not None:
        latest_replay = {
            "completed_turns": dashboard.latest_session_replay.completed_turns,
            "successful_turns": dashboard.latest_session_replay.successful_turns,
            "failed_turns": dashboard.latest_session_replay.failed_turns,
            "tool_calls": dashboard.latest_session_replay.tool_calls,
            "route_reason_counts": dashboard.latest_session_replay.route_reason_counts,
        }
    return {
        "workspace": str(workspace),
        "team_status": team_status,
        "runtime_health": {
            "status": doctor.status,
            "summary": doctor.summary,
            "finding_count": len(doctor.findings),
            "summary_by_category": doctor.summary_by_category,
        },
        "runtime_counts": {
            "trace_events": trace_summary.total_events if trace_summary is not None else 0,
            "tool_calls": trace_summary.tool_calls if trace_summary is not None else 0,
            "failed_tool_calls": trace_summary.failed_tool_calls if trace_summary is not None else 0,
            "context_builds": trace_summary.context_builds if trace_summary is not None else 0,
            "background_status_counts": dashboard.background_status_counts,
            "task_status_counts": dashboard.task_status_counts,
            "memory_candidate_status_counts": dashboard.memory_candidate_status_counts,
        },
        "latest_session": latest_session,
        "latest_session_replay": latest_replay,
        "background_runs": {
            "total": sum(int(value or 0) for value in dashboard.background_status_counts.values()),
            "recent": [run.to_dict() for run in dashboard.latest_background_runs],
        },
    }


def _render_team_board_markdown(board: dict[str, object]) -> str:
    team_status = dict(board["team_status"])
    runtime_health = dict(board["runtime_health"])
    runtime_counts = dict(board["runtime_counts"])
    background_runs = dict(board["background_runs"])
    status_counts = dict(team_status["status_counts"])
    lines = [
        "# Mini Claw Team Board",
        "",
        f"- workspace: {board['workspace']}",
        f"- team_health: {runtime_health['status']}",
        f"- team_summary: {runtime_health['summary']}",
        f"- task_count: {team_status['task_count']}",
        f"- ready_tasks: {len(team_status['ready_tasks'])}",
        f"- background_runs: {background_runs['total']}",
        f"- trace_events: {runtime_counts['trace_events']}",
        f"- tool_calls: {runtime_counts['tool_calls']}",
        "",
        "## Team Queue",
        f"- pending: {status_counts.get('pending', 0)}",
        f"- in_progress: {status_counts.get('in_progress', 0)}",
        f"- blocked: {status_counts.get('blocked', 0)}",
        f"- done: {status_counts.get('done', 0)}",
        f"- failed: {status_counts.get('failed', 0)}",
    ]
    lines.extend(["", "## Ready Tasks"])
    ready_tasks = list(team_status["ready_tasks"])
    if not ready_tasks:
        lines.append("(none)")
    else:
        for item in ready_tasks:
            lines.append(f"- {item['task_id']}: {item['objective']}")
    lines.extend(["", "## Runtime Health"])
    summary_by_category = dict(runtime_health["summary_by_category"])
    if not summary_by_category:
        lines.append("(none)")
    else:
        for category, counts in sorted(summary_by_category.items()):
            lines.append(
                f"- {category}: fail={counts.get('fail', 0)} "
                f"warn={counts.get('warn', 0)} info={counts.get('info', 0)}"
            )
    lines.extend(["", "## Latest Session"])
    latest_session = board["latest_session"]
    latest_replay = board["latest_session_replay"]
    if latest_session is None:
        lines.append("(none)")
    else:
        lines.append(
            f"- {latest_session['session_id']} name={latest_session['name'] or '-'} "
            f"turns={latest_session['turn_count']}"
        )
        if latest_replay is not None:
            lines.append(
                f"- replay: completed={latest_replay['completed_turns']} "
                f"success={latest_replay['successful_turns']} failed={latest_replay['failed_turns']} "
                f"tool_calls={latest_replay['tool_calls']}"
            )
    lines.extend(["", "## Recent Background Runs"])
    recent_runs = list(background_runs["recent"])
    if not recent_runs:
        lines.append("(none)")
    else:
        for item in recent_runs:
            lines.append(
                f"- {item['run_id']} [{item['status']}] label={item['label'] or '-'} "
                f"task_id={item['task_id'] or '-'}"
            )
    return "\n".join(lines)


def summarize_team_board_changes(
    previous: dict[str, object],
    current: dict[str, object],
) -> list[str]:
    changes: list[str] = []
    previous_team_status = dict(previous.get("team_status") or {})
    current_team_status = dict(current.get("team_status") or {})
    previous_runtime_health = dict(previous.get("runtime_health") or {})
    current_runtime_health = dict(current.get("runtime_health") or {})
    previous_runtime_counts = dict(previous.get("runtime_counts") or {})
    current_runtime_counts = dict(current.get("runtime_counts") or {})
    previous_background = dict(previous.get("background_runs") or {})
    current_background = dict(current.get("background_runs") or {})
    previous_session = previous.get("latest_session")
    current_session = current.get("latest_session")

    changes.extend(
        _team_diff_scalar(
            "team_health.status",
            previous_runtime_health.get("status"),
            current_runtime_health.get("status"),
        )
    )
    changes.extend(
        _team_diff_scalar(
            "team_health.finding_count",
            previous_runtime_health.get("finding_count"),
            current_runtime_health.get("finding_count"),
        )
    )
    changes.extend(
        _team_diff_scalar(
            "team.ready_tasks",
            len(list(previous_team_status.get("ready_tasks") or [])),
            len(list(current_team_status.get("ready_tasks") or [])),
        )
    )
    changes.extend(
        _team_diff_scalar(
            "runtime.trace_events",
            previous_runtime_counts.get("trace_events"),
            current_runtime_counts.get("trace_events"),
        )
    )
    changes.extend(
        _team_diff_scalar(
            "runtime.tool_calls",
            previous_runtime_counts.get("tool_calls"),
            current_runtime_counts.get("tool_calls"),
        )
    )
    changes.extend(
        _team_diff_scalar(
            "background.total",
            previous_background.get("total"),
            current_background.get("total"),
        )
    )
    previous_status_counts = dict(previous_team_status.get("status_counts") or {})
    current_status_counts = dict(current_team_status.get("status_counts") or {})
    for key in sorted(set(previous_status_counts) | set(current_status_counts)):
        changes.extend(
            _team_diff_scalar(
                f"team.status.{key}",
                previous_status_counts.get(key, 0),
                current_status_counts.get(key, 0),
            )
        )
    previous_session_id = (
        dict(previous_session).get("session_id")
        if isinstance(previous_session, dict)
        else None
    )
    current_session_id = (
        dict(current_session).get("session_id")
        if isinstance(current_session, dict)
        else None
    )
    changes.extend(
        _team_diff_scalar("sessions.latest", previous_session_id, current_session_id)
    )
    return changes


def summarize_team_board_changes_by_section(
    previous: dict[str, object],
    current: dict[str, object],
) -> dict[str, list[str]]:
    previous_team_status = dict(previous.get("team_status") or {})
    current_team_status = dict(current.get("team_status") or {})
    previous_runtime_health = dict(previous.get("runtime_health") or {})
    current_runtime_health = dict(current.get("runtime_health") or {})
    previous_runtime_counts = dict(previous.get("runtime_counts") or {})
    current_runtime_counts = dict(current.get("runtime_counts") or {})
    previous_background = dict(previous.get("background_runs") or {})
    current_background = dict(current.get("background_runs") or {})
    previous_session = previous.get("latest_session")
    current_session = current.get("latest_session")

    team_status_changes: list[str] = []
    team_status_changes.extend(
        _team_diff_scalar(
            "ready_tasks",
            len(list(previous_team_status.get("ready_tasks") or [])),
            len(list(current_team_status.get("ready_tasks") or [])),
        )
    )
    previous_status_counts = dict(previous_team_status.get("status_counts") or {})
    current_status_counts = dict(current_team_status.get("status_counts") or {})
    for key in sorted(set(previous_status_counts) | set(current_status_counts)):
        team_status_changes.extend(
            _team_diff_scalar(
                f"status.{key}",
                previous_status_counts.get(key, 0),
                current_status_counts.get(key, 0),
            )
        )

    runtime_health_changes: list[str] = []
    runtime_health_changes.extend(
        _team_diff_scalar(
            "status",
            previous_runtime_health.get("status"),
            current_runtime_health.get("status"),
        )
    )
    runtime_health_changes.extend(
        _team_diff_scalar(
            "finding_count",
            previous_runtime_health.get("finding_count"),
            current_runtime_health.get("finding_count"),
        )
    )

    runtime_count_changes: list[str] = []
    runtime_count_changes.extend(
        _team_diff_scalar(
            "trace_events",
            previous_runtime_counts.get("trace_events"),
            current_runtime_counts.get("trace_events"),
        )
    )
    runtime_count_changes.extend(
        _team_diff_scalar(
            "tool_calls",
            previous_runtime_counts.get("tool_calls"),
            current_runtime_counts.get("tool_calls"),
        )
    )
    runtime_count_changes.extend(
        _team_diff_scalar(
            "failed_tool_calls",
            previous_runtime_counts.get("failed_tool_calls"),
            current_runtime_counts.get("failed_tool_calls"),
        )
    )
    runtime_count_changes.extend(
        _team_diff_scalar(
            "context_builds",
            previous_runtime_counts.get("context_builds"),
            current_runtime_counts.get("context_builds"),
        )
    )

    previous_session_id = (
        dict(previous_session).get("session_id")
        if isinstance(previous_session, dict)
        else None
    )
    current_session_id = (
        dict(current_session).get("session_id")
        if isinstance(current_session, dict)
        else None
    )
    latest_session_changes = _team_diff_scalar(
        "session_id",
        previous_session_id,
        current_session_id,
    )

    background_changes: list[str] = []
    background_changes.extend(
        _team_diff_scalar(
            "total",
            previous_background.get("total"),
            current_background.get("total"),
        )
    )
    background_changes.extend(
        _team_diff_scalar(
            "recent_count",
            len(list(previous_background.get("recent") or [])),
            len(list(current_background.get("recent") or [])),
        )
    )

    return {
        "team_status": team_status_changes,
        "runtime_health": runtime_health_changes,
        "runtime_counts": runtime_count_changes,
        "latest_session": latest_session_changes,
        "background_runs": background_changes,
    }


def _empty_team_board_changes_by_section() -> dict[str, list[str]]:
    return {
        "team_status": [],
        "runtime_health": [],
        "runtime_counts": [],
        "latest_session": [],
        "background_runs": [],
    }


def summarize_team_board_changes_by_section_delta(
    previous: dict[str, object],
    current: dict[str, object],
) -> dict[str, dict[str, object]]:
    previous_team_status = dict(previous.get("team_status") or {})
    current_team_status = dict(current.get("team_status") or {})
    previous_runtime_health = dict(previous.get("runtime_health") or {})
    current_runtime_health = dict(current.get("runtime_health") or {})
    previous_runtime_counts = dict(previous.get("runtime_counts") or {})
    current_runtime_counts = dict(current.get("runtime_counts") or {})
    previous_background = dict(previous.get("background_runs") or {})
    current_background = dict(current.get("background_runs") or {})
    previous_session = dict(previous.get("latest_session") or {})
    current_session = dict(current.get("latest_session") or {})

    previous_status_counts = dict(previous_team_status.get("status_counts") or {})
    current_status_counts = dict(current_team_status.get("status_counts") or {})
    team_status_delta = {
        "ready_tasks": _team_delta_number(
            len(list(previous_team_status.get("ready_tasks") or [])),
            len(list(current_team_status.get("ready_tasks") or [])),
        ),
        "task_count": _team_delta_number(
            int(previous_team_status.get("task_count", 0) or 0),
            int(current_team_status.get("task_count", 0) or 0),
        ),
        "status_counts": {
            key: _team_delta_number(
                int(previous_status_counts.get(key, 0) or 0),
                int(current_status_counts.get(key, 0) or 0),
            )
            for key in sorted(set(previous_status_counts) | set(current_status_counts))
        },
    }

    runtime_health_delta = {
        "status_changed": previous_runtime_health.get("status") != current_runtime_health.get("status"),
        "finding_count": _team_delta_number(
            int(previous_runtime_health.get("finding_count", 0) or 0),
            int(current_runtime_health.get("finding_count", 0) or 0),
        ),
    }

    runtime_counts_delta = {
        "trace_events": _team_delta_number(
            int(previous_runtime_counts.get("trace_events", 0) or 0),
            int(current_runtime_counts.get("trace_events", 0) or 0),
        ),
        "tool_calls": _team_delta_number(
            int(previous_runtime_counts.get("tool_calls", 0) or 0),
            int(current_runtime_counts.get("tool_calls", 0) or 0),
        ),
        "failed_tool_calls": _team_delta_number(
            int(previous_runtime_counts.get("failed_tool_calls", 0) or 0),
            int(current_runtime_counts.get("failed_tool_calls", 0) or 0),
        ),
        "context_builds": _team_delta_number(
            int(previous_runtime_counts.get("context_builds", 0) or 0),
            int(current_runtime_counts.get("context_builds", 0) or 0),
        ),
    }

    latest_session_delta = {
        "session_changed": previous_session.get("session_id") != current_session.get("session_id"),
        "turn_count": _team_delta_number(
            int(previous_session.get("turn_count", 0) or 0),
            int(current_session.get("turn_count", 0) or 0),
        ),
    }

    background_runs_delta = {
        "total": _team_delta_number(
            int(previous_background.get("total", 0) or 0),
            int(current_background.get("total", 0) or 0),
        ),
        "recent_count": _team_delta_number(
            len(list(previous_background.get("recent") or [])),
            len(list(current_background.get("recent") or [])),
        ),
    }

    return {
        "team_status": team_status_delta,
        "runtime_health": runtime_health_delta,
        "runtime_counts": runtime_counts_delta,
        "latest_session": latest_session_delta,
        "background_runs": background_runs_delta,
    }


def _empty_team_board_changes_by_section_delta() -> dict[str, dict[str, object]]:
    return {
        "team_status": {
            "ready_tasks": _team_delta_number(0, 0),
            "task_count": _team_delta_number(0, 0),
            "status_counts": {},
        },
        "runtime_health": {
            "status_changed": False,
            "finding_count": _team_delta_number(0, 0),
        },
        "runtime_counts": {
            "trace_events": _team_delta_number(0, 0),
            "tool_calls": _team_delta_number(0, 0),
            "failed_tool_calls": _team_delta_number(0, 0),
            "context_builds": _team_delta_number(0, 0),
        },
        "latest_session": {
            "session_changed": False,
            "turn_count": _team_delta_number(0, 0),
        },
        "background_runs": {
            "total": _team_delta_number(0, 0),
            "recent_count": _team_delta_number(0, 0),
        },
    }


def _team_delta_number(previous: int, current: int) -> dict[str, int]:
    return {
        "previous": previous,
        "current": current,
        "delta": current - previous,
    }


def _team_diff_scalar(label: str, previous: object, current: object) -> list[str]:
    if previous == current:
        return []
    return [f"- {label}: {previous if previous not in (None, '') else '(none)'} -> {current if current not in (None, '') else '(none)'}"]


def _build_orchestrator_coder_runner(
    args: argparse.Namespace,
    memory: MemoryStore,
):
    main_workspace = Path(args.workspace).resolve()

    def run_coder(node: TaskNode, task_workspace: Path) -> CoderRunResult:
        runtime = RuntimeConfig(
            workspace=task_workspace,
            max_steps=args.max_steps,
            command_timeout_seconds=args.timeout,
            dry_run=args.dry_run,
        )
        models = ModelConfig(provider=args.provider, default_model=args.model)
        config = AppConfig(runtime=runtime, models=models)
        skills = SkillLoader(
            [
                task_workspace / ".mini_claw" / "skills",
                main_workspace / ".mini_claw" / "skills",
            ]
        ).load()
        router = ModelRouter(models, policy=args.routing_policy)
        client = create_model_client(models.provider, workspace=task_workspace)
        tools = build_runtime_tools(
            workspace=task_workspace,
            memory=memory,
            timeout_seconds=runtime.command_timeout_seconds,
            dry_run=runtime.dry_run,
            require_read_snapshot=args.enforce_read_before_write,
        )
        result = AgentLoop(
            config=config,
            client=client,
            router=router,
            tools=tools,
            memory=memory,
            skills=skills,
        ).run(node.objective)
        return CoderRunResult(
            ok=result.success,
            detail=result.final_answer[:500],
            modified_files=result.modified_files,
        )

    return run_coder


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mini-claw")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run a coding-agent task.")
    run.add_argument("task", help="Natural-language coding task.")
    run.add_argument("--workspace", default=".", help="Repository or project directory.")
    run.add_argument("--provider", default="mock", choices=["mock", "openai-compatible"])
    run.add_argument("--model", default="mock-coder")
    run.add_argument("--routing-policy", default="signal-aware", choices=["basic", "signal-aware"])
    run.add_argument("--max-steps", type=int, default=8)
    run.add_argument("--timeout", type=int, default=30)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--enforce-read-before-write", action="store_true")
    run.add_argument("--session", default="", help="Resume a persistent session by id or 1-based index.")
    run.add_argument(
        "--execution-mode",
        default="copy",
        choices=["main", "copy", "git-worktree"],
        help="Where the agent executes file changes and commands. Defaults to isolated copy mode.",
    )
    run.add_argument(
        "--execution-id",
        default="",
        help="Reuse or name an isolated execution workspace when execution-mode is copy or git-worktree.",
    )
    run.add_argument(
        "--show-execution-diff",
        action="store_true",
        help="Show the pending diff inside the isolated execution workspace after the run.",
    )
    run.add_argument(
        "--merge-back",
        action="store_true",
        help="Merge isolated execution workspace changes back into the main workspace after a successful run.",
    )
    run.add_argument(
        "--merge-verify",
        action="append",
        default=[],
        help="Additional verification command to run during merge-back. Can be provided multiple times.",
    )
    run.add_argument(
        "--rollback-on-merge-verification-failure",
        action="store_true",
        help="Roll back merge-back changes if merge verification fails.",
    )
    run.set_defaults(func=cmd_run)

    chat = sub.add_parser("chat", help="Start an interactive coding-agent chat session.")
    chat.add_argument("--workspace", default=".", help="Repository or project directory.")
    chat.add_argument("--provider", default="mock", choices=["mock", "openai-compatible"])
    chat.add_argument("--model", default="mock-coder")
    chat.add_argument("--routing-policy", default="signal-aware", choices=["basic", "signal-aware"])
    chat.add_argument("--max-steps", type=int, default=12)
    chat.add_argument("--timeout", type=int, default=30)
    chat.add_argument("--dry-run", action="store_true")
    chat.add_argument("--enforce-read-before-write", action="store_true")
    chat.add_argument("--session", default="", help="Resume a persistent chat session by id or 1-based index.")
    chat.add_argument("--session-name", default="chat", help="Name for a newly created chat session.")
    chat.add_argument("--turn-limit", type=int, default=10, help="Turn limit used by the /replay command.")
    chat.add_argument(
        "--execution-mode",
        default="copy",
        choices=["main", "copy", "git-worktree"],
        help="Where the agent executes file changes and commands. Defaults to isolated copy mode.",
    )
    chat.add_argument(
        "--show-execution-diff",
        action="store_true",
        help="Show the pending diff inside the isolated execution workspace after each turn.",
    )
    chat.add_argument(
        "--merge-back",
        dest="merge_back",
        action="store_true",
        default=True,
        help="Merge isolated execution workspace changes back into the main workspace after successful turns.",
    )
    chat.add_argument(
        "--no-merge-back",
        dest="merge_back",
        action="store_false",
        help="Keep changes inside the isolated execution workspace instead of merging them back.",
    )
    chat.add_argument(
        "--merge-verify",
        action="append",
        default=[],
        help="Additional verification command to run during merge-back. Defaults to unittest discover when tests/ exists.",
    )
    chat.add_argument(
        "--rollback-on-merge-verification-failure",
        dest="rollback_on_merge_verification_failure",
        action="store_true",
        default=True,
        help="Roll back merge-back changes if merge verification fails.",
    )
    chat.add_argument(
        "--no-rollback-on-merge-verification-failure",
        dest="rollback_on_merge_verification_failure",
        action="store_false",
        help="Keep merge-back changes even when merge verification fails.",
    )
    chat.set_defaults(func=cmd_chat)

    smoke = sub.add_parser("smoke", help="Run a minimal native tool-calling smoke test.")
    smoke.add_argument("--workspace", default=".")
    smoke.add_argument("--provider", default="openai-compatible", choices=["mock", "openai-compatible"])
    smoke.add_argument("--model", default="mock-coder")
    smoke.add_argument("--timeout", type=int, default=30)
    smoke.add_argument("--max-rounds", type=int, default=4)
    smoke.add_argument("--expected-final", default="NATIVE_SMOKE_OK")
    smoke.add_argument("--json", action="store_true")
    smoke.set_defaults(func=cmd_smoke)

    ev = sub.add_parser("eval", help="Run a JSONL eval file.")
    ev.add_argument("file", help="JSONL file with task objects.")
    ev.add_argument("--workspace", default=".")
    ev.add_argument("--provider", default="mock", choices=["mock", "openai-compatible"])
    ev.add_argument("--routing-policy", default="signal-aware", choices=["basic", "signal-aware"])
    ev.set_defaults(func=cmd_eval)

    bench = sub.add_parser("bench", help="Run an offline EvalBench suite.")
    bench.add_argument("file", help="Bench JSON/JSONL file.")
    bench.add_argument("--workspace", default=".")
    bench.add_argument("--routing-policy", default="signal-aware", choices=["basic", "signal-aware"])
    bench.set_defaults(func=cmd_bench)

    bench_routing = sub.add_parser("bench-routing", help="Compare routing policies on an offline EvalBench suite.")
    bench_routing.add_argument("file", help="Bench JSON/JSONL file.")
    bench_routing.add_argument("--workspace", default=".")
    bench_routing.add_argument("--policies", nargs="+", default=["basic", "signal-aware"])
    bench_routing.set_defaults(func=cmd_bench_routing)

    replay = sub.add_parser("replay", help="Replay and summarize the runtime trace.")
    replay.add_argument("--workspace", default=".")
    replay.add_argument("--trace", default="", help="Trace JSONL path. Defaults to .mini_claw memory.")
    replay.set_defaults(func=cmd_replay)

    session = sub.add_parser("session", help="Manage persistent runtime sessions.")
    session_sub = session.add_subparsers(dest="session_command", required=True)

    session_create = session_sub.add_parser("create", help="Create a persistent session.")
    session_create.add_argument("--workspace", default=".")
    session_create.add_argument("--name", default="")
    session_create.add_argument("--json", action="store_true")
    session_create.set_defaults(func=cmd_session)

    session_list = session_sub.add_parser("list", help="List persistent sessions.")
    session_list.add_argument("--workspace", default=".")
    session_list.add_argument("--limit", type=int, default=20)
    session_list.add_argument("--json", action="store_true")
    session_list.set_defaults(func=cmd_session)

    session_show = session_sub.add_parser("show", help="Show a persistent session.")
    session_show.add_argument("ref", help="Session id or 1-based index.")
    session_show.add_argument("--workspace", default=".")
    session_show.add_argument("--turn-limit", type=int, default=5)
    session_show.add_argument("--max-chars", type=int, default=3_500)
    session_show.add_argument("--json", action="store_true")
    session_show.set_defaults(func=cmd_session)

    session_replay = session_sub.add_parser("replay", help="Replay all completed turns in a session.")
    session_replay.add_argument("ref", help="Session id or 1-based index.")
    session_replay.add_argument("--workspace", default=".")
    session_replay.add_argument("--turn-limit", type=int, default=20)
    session_replay.add_argument("--json", action="store_true")
    session_replay.set_defaults(func=cmd_session)

    session_turn_show = session_sub.add_parser("turn-show", help="Show one session turn with replay stats.")
    session_turn_show.add_argument("session_ref", help="Session id or 1-based index.")
    session_turn_show.add_argument("turn_ref", help="Turn id or 1-based index within the session.")
    session_turn_show.add_argument("--workspace", default=".")
    session_turn_show.add_argument("--json", action="store_true")
    session_turn_show.set_defaults(func=cmd_session)

    home = sub.add_parser("home", help="Show a terminal-first home screen for the current workspace.")
    home.add_argument("--workspace", default=".")
    home.add_argument("--session", default="", help="Session id or 1-based index to spotlight.")
    home.add_argument("--session-turn-limit", type=int, default=20)
    home.add_argument("--background-limit", type=int, default=5)
    home.add_argument("--tool-output-limit", type=int, default=5)
    home.add_argument("--watch", action="store_true", help="Refresh the home screen continuously.")
    home.add_argument("--interval", type=float, default=2.0, help="Seconds between refreshes in watch mode.")
    home.add_argument("--iterations", type=int, default=0, help="Stop after N refreshes in watch mode. 0 means forever.")
    home.add_argument("--no-clear", action="store_true", help="Do not clear the screen between home refreshes.")
    home.add_argument("--changes-only", action="store_true", help="In watch mode, hide the full home screen after the first refresh and show only deltas.")
    home.add_argument("--style", default="plain", choices=["plain", "tui"], help="Choose whether the terminal home should render as plain markdown or a denser TUI-style layout.")
    home.add_argument("--preset", default="default", choices=["default", "compact", "ops", "interview"], help="When using TUI style, apply a ready-made layout preset before any explicit focus/width/collapse overrides.")
    home.add_argument("--watch-layout", default="default", choices=["default", "full", "delta"], help="When using TUI style in watch mode, choose whether refreshes should follow the preset default, always keep the full layout, or switch to delta-only after the first refresh.")
    home.add_argument("--focus", default="auto", choices=["auto", "team", "runtime", "sessions"], help="When using TUI style, choose which area should be emphasized first.")
    home.add_argument("--width", type=int, default=108, help="Target character width for TUI-style rendering.")
    home.add_argument("--collapse", default="", help="When using TUI style, comma-separated section ids to collapse. Supported ids: team,runtime_health,runtime_counts,sessions,background,session_replay,changes.")
    home.add_argument("--demo-mode", action="store_true", help="When using TUI style, add a terminal demo talk-track panel above the main board.")
    home.add_argument("--demo-language", default="en", choices=["bilingual", "en", "zh"], help="When using TUI style with --demo-mode, choose the terminal talk-track language.")
    home.add_argument("--demo-focus", default="auto", choices=["auto", "team", "runtime", "sessions"], help="When using TUI style with --demo-mode, choose whether the talk-track should prefer team, runtime, or session framing.")
    home.add_argument("--demo-script", default="full", choices=["short", "full"], help="When using TUI style with --demo-mode, choose whether the terminal talk-track should be shorter or fuller.")
    home.add_argument("--ignore", default="", help="Comma-separated doctor finding codes to hide.")
    home.add_argument("--category", default="", help="Comma-separated doctor finding categories to keep.")
    home.add_argument("--severity-at-least", default="info", choices=["info", "warn", "fail"], help="Hide doctor findings below this severity.")
    home.add_argument("--sort-by", default="default", choices=["default", "severity", "category", "code"], help="Sort doctor findings for stable ordering.")
    home.add_argument("--output-file", default="", help="Write JSON output to a file. In watch mode this appends NDJSON.")
    home.add_argument("--json", action="store_true", help="Emit machine-readable JSON. In watch mode this prints one JSON object per refresh.")
    home.set_defaults(func=cmd_home)

    dashboard = sub.add_parser("dashboard", help="Show a unified runtime dashboard.")
    dashboard.add_argument("--workspace", default=".")
    dashboard.add_argument("--session", default="", help="Session id or 1-based index to spotlight.")
    dashboard.add_argument("--session-turn-limit", type=int, default=20)
    dashboard.add_argument("--background-limit", type=int, default=5)
    dashboard.add_argument("--tool-output-limit", type=int, default=5)
    dashboard.add_argument("--watch", action="store_true", help="Refresh the dashboard continuously.")
    dashboard.add_argument("--interval", type=float, default=2.0, help="Seconds between refreshes in watch mode.")
    dashboard.add_argument("--iterations", type=int, default=0, help="Stop after N refreshes in watch mode. 0 means forever.")
    dashboard.add_argument("--no-clear", action="store_true", help="Do not clear the screen between dashboard refreshes.")
    dashboard.add_argument("--changes-only", action="store_true", help="In watch mode, hide the full dashboard after the first refresh and show only deltas.")
    dashboard.add_argument("--output-file", default="", help="Write JSON output to a file. In watch mode this appends NDJSON.")
    dashboard.add_argument("--json", action="store_true", help="Emit machine-readable JSON. In watch mode this prints one JSON object per refresh.")
    dashboard.set_defaults(func=cmd_dashboard)

    doctor = sub.add_parser("doctor", help="Diagnose runtime health from the current dashboard snapshot.")
    doctor.add_argument("--workspace", default=".")
    doctor.add_argument("--session", default="", help="Session id or 1-based index to spotlight.")
    doctor.add_argument("--session-turn-limit", type=int, default=20)
    doctor.add_argument("--background-limit", type=int, default=5)
    doctor.add_argument("--tool-output-limit", type=int, default=5)
    doctor.add_argument("--strict-warnings", action="store_true", help="Return a failing exit code when warnings are present.")
    doctor.add_argument("--watch", action="store_true", help="Refresh the doctor report continuously.")
    doctor.add_argument("--interval", type=float, default=2.0, help="Seconds between refreshes in watch mode.")
    doctor.add_argument("--iterations", type=int, default=0, help="Stop after N refreshes in watch mode. 0 means forever.")
    doctor.add_argument("--no-clear", action="store_true", help="Do not clear the screen between doctor refreshes.")
    doctor.add_argument("--changes-only", action="store_true", help="In watch mode, hide the full doctor report after the first refresh and show only deltas.")
    doctor.add_argument("--summary-only", action="store_true", help="Print only the top-level summary instead of the full doctor report.")
    doctor.add_argument("--fail-on", default="", help="Comma-separated finding codes that should return a failing exit code.")
    doctor.add_argument("--ignore", default="", help="Comma-separated finding codes to hide and exclude from exit-code evaluation.")
    doctor.add_argument("--category", default="", help="Comma-separated finding categories to keep, such as trace,sessions,memory.")
    doctor.add_argument("--severity-at-least", default="info", choices=["info", "warn", "fail"], help="Hide findings below this severity.")
    doctor.add_argument("--sort-by", default="default", choices=["default", "severity", "category", "code"], help="Sort findings for stable output ordering.")
    doctor.add_argument("--output-file", default="", help="Write JSON output to a file. In watch mode this appends NDJSON.")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    export = sub.add_parser("export", help="Export one runtime snapshot as machine-readable JSON.")
    export.add_argument("export_target", choices=["dashboard", "doctor", "team-board", "bundle"])
    export.add_argument("--workspace", default=".")
    export.add_argument("--output-file", default="", help="Write the exported JSON to a file.")
    export.add_argument("--session", default="", help="Session id or 1-based index to spotlight.")
    export.add_argument("--session-turn-limit", type=int, default=20)
    export.add_argument("--background-limit", type=int, default=5)
    export.add_argument("--tool-output-limit", type=int, default=5)
    export.add_argument("--watch", action="store_true", help="Continuously export snapshots as NDJSON.")
    export.add_argument("--interval", type=float, default=2.0, help="Seconds between export refreshes in watch mode.")
    export.add_argument("--iterations", type=int, default=0, help="Stop after N refreshes in watch mode. 0 means forever.")
    export.add_argument("--changes-only", action="store_true", help="In watch mode, emit only change metadata after the first snapshot.")
    export.add_argument("--ignore", default="", help="Doctor-only: comma-separated finding codes to hide.")
    export.add_argument("--category", default="", help="Doctor-only: comma-separated finding categories to keep.")
    export.add_argument("--severity-at-least", default="info", choices=["info", "warn", "fail"], help="Doctor-only: hide findings below this severity.")
    export.add_argument("--sort-by", default="default", choices=["default", "severity", "category", "code"], help="Doctor-only: sort findings for stable output ordering.")
    export.set_defaults(func=cmd_export)

    viewer = sub.add_parser("viewer", help="Build a local HTML viewer from exported runtime JSON or NDJSON.")
    viewer.add_argument("--workspace", default=".")
    viewer.add_argument("--from-workspace", action="store_true", help="Render directly from the current workspace snapshot instead of reading an export file.")
    viewer.add_argument("--source-target", default="bundle", choices=["dashboard", "doctor", "team-board", "bundle"], help="When using --from-workspace, choose which snapshot to render.")
    viewer.add_argument("--input-file", default="", help="Path to a JSON or NDJSON export file. Defaults to .mini_claw/runtime_bundle.ndjson or bundle.json.")
    viewer.add_argument("--output-file", default=".mini_claw/runtime_viewer.html", help="Where to write the generated HTML viewer.")
    viewer.add_argument("--title", default="Mini Claw Runtime Viewer")
    viewer.add_argument("--refresh-seconds", type=float, default=0.0, help="When greater than 0, add an HTML meta refresh for lightweight auto-reload.")
    viewer.add_argument("--demo-mode", action="store_true", help="Tune the first screen for a tighter interview/demo summary.")
    viewer.add_argument("--demo-language", default="bilingual", choices=["bilingual", "en", "zh"], help="Choose the talk-track language used in demo mode.")
    viewer.add_argument("--demo-focus", default="auto", choices=["auto", "team", "runtime"], help="Choose whether demo mode should prefer team-first or runtime-first summary cards.")
    viewer.add_argument("--demo-script", default="full", choices=["short", "full"], help="Choose whether demo mode should use a shorter or fuller talk-track.")
    viewer.add_argument("--session", default="", help="Session id or 1-based index to spotlight in workspace mode.")
    viewer.add_argument("--session-turn-limit", type=int, default=20)
    viewer.add_argument("--background-limit", type=int, default=5)
    viewer.add_argument("--tool-output-limit", type=int, default=5)
    viewer.add_argument("--ignore", default="", help="Workspace doctor/bundle mode: comma-separated finding codes to hide.")
    viewer.add_argument("--category", default="", help="Workspace doctor/bundle mode: comma-separated finding categories to keep.")
    viewer.add_argument("--severity-at-least", default="info", choices=["info", "warn", "fail"], help="Workspace doctor/bundle mode: hide findings below this severity.")
    viewer.add_argument("--sort-by", default="default", choices=["default", "severity", "category", "code"], help="Workspace doctor/bundle mode: sort findings for stable output ordering.")
    viewer.set_defaults(func=cmd_viewer)

    team = sub.add_parser("team", help="Run or inspect the lightweight multi-role team workflow.")
    team_sub = team.add_subparsers(dest="team_command", required=True)

    team_board = team_sub.add_parser("board", help="Show a one-screen team control surface.")
    team_board.add_argument("--workspace", default=".")
    team_board.add_argument("--session", default="", help="Session id or 1-based index to spotlight.")
    team_board.add_argument("--session-turn-limit", type=int, default=20)
    team_board.add_argument("--background-limit", type=int, default=5)
    team_board.add_argument("--tool-output-limit", type=int, default=5)
    team_board.add_argument("--watch", action="store_true", help="Refresh the team board continuously.")
    team_board.add_argument("--interval", type=float, default=2.0, help="Seconds between refreshes in watch mode.")
    team_board.add_argument("--iterations", type=int, default=0, help="Stop after N refreshes in watch mode. 0 means forever.")
    team_board.add_argument("--no-clear", action="store_true", help="Do not clear the screen between team-board refreshes.")
    team_board.add_argument("--changes-only", action="store_true", help="In watch mode, hide the full team board after the first refresh and show only deltas.")
    team_board.add_argument("--output-file", default="", help="Write JSON output to a file. In watch mode this appends NDJSON.")
    team_board.add_argument("--json", action="store_true")
    team_board.set_defaults(func=cmd_team)

    team_status = team_sub.add_parser("status", help="Show the current task-team status.")
    team_status.add_argument("--workspace", default=".")
    team_status.add_argument("--json", action="store_true")
    team_status.set_defaults(func=cmd_team)

    team_run = team_sub.add_parser("run", help="Run planner/coder/tester/integrator on ready tasks.")
    team_run.add_argument("--workspace", default=".")
    team_run.add_argument("--mode", default="copy", choices=["copy", "git-worktree"])
    team_run.add_argument("--limit", type=int, default=1)
    team_run.add_argument("--dry-run", action="store_true")
    team_run.add_argument("--rollback-on-verification-failure", action="store_true")
    team_run.add_argument("--run-coder-agent", action="store_true")
    team_run.add_argument("--provider", default="mock", choices=["mock", "openai-compatible"])
    team_run.add_argument("--model", default="mock-coder")
    team_run.add_argument("--routing-policy", default="signal-aware", choices=["basic", "signal-aware"])
    team_run.add_argument("--max-steps", type=int, default=8)
    team_run.add_argument("--timeout", type=int, default=30)
    team_run.add_argument("--enforce-read-before-write", action="store_true")
    team_run.add_argument("--json", action="store_true")
    team_run.set_defaults(func=cmd_team)

    index = sub.add_parser("index", help="Render the progressive file preview index.")
    index.add_argument("--workspace", default=".")
    index.add_argument("--query", default="")
    index.add_argument("--limit", type=int, default=40)
    index.add_argument("--preview-lines", type=int, default=2)
    index.set_defaults(func=cmd_index)

    skills = sub.add_parser("skills", help="Inspect skill contracts and relevance.")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)

    skills_list = skills_sub.add_parser("list", help="List available skill contracts.")
    skills_list.add_argument("--workspace", default=".")
    skills_list.add_argument("--include-examples", action="store_true")
    skills_list.set_defaults(func=cmd_skills)

    skills_match = skills_sub.add_parser("match", help="Show skills relevant to a query.")
    skills_match.add_argument("query")
    skills_match.add_argument("--workspace", default=".")
    skills_match.add_argument("--include-examples", action="store_true")
    skills_match.add_argument("--limit", type=int, default=3)
    skills_match.set_defaults(func=cmd_skills)

    memory = sub.add_parser("memory", help="Inspect memory store artifacts.")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)
    memory_candidates = memory_sub.add_parser("candidates", help="List memory candidates.")
    memory_candidates.add_argument("--workspace", default=".")
    memory_candidates.add_argument("--kind", default="")
    memory_candidates.add_argument("--status", default="")
    memory_candidates.add_argument("--query", default="")
    memory_candidates.add_argument("--limit", type=int, default=50)
    memory_candidates.set_defaults(func=cmd_memory)

    memory_promote = memory_sub.add_parser("promote", help="Promote a memory candidate.")
    memory_promote.add_argument("ref", help="Candidate id or 1-based index.")
    memory_promote.add_argument("--workspace", default=".")
    memory_promote.add_argument("--reason", default="manual promote")
    memory_promote.set_defaults(func=cmd_memory)

    memory_reject = memory_sub.add_parser("reject", help="Reject a memory candidate.")
    memory_reject.add_argument("ref", help="Candidate id or 1-based index.")
    memory_reject.add_argument("--workspace", default=".")
    memory_reject.add_argument("--reason", default="manual reject")
    memory_reject.set_defaults(func=cmd_memory)

    memory_skill_patches = memory_sub.add_parser(
        "skill-patches",
        help="List promoted skill patch artifacts.",
    )
    memory_skill_patches.add_argument("--workspace", default=".")
    memory_skill_patches.add_argument("--query", default="")
    memory_skill_patches.add_argument("--limit", type=int, default=20)
    memory_skill_patches.set_defaults(func=cmd_memory)

    memory_skill_patch_show = memory_sub.add_parser(
        "skill-patch-show",
        help="Show a promoted skill patch artifact.",
    )
    memory_skill_patch_show.add_argument("ref", help="Artifact id, candidate id, or 1-based index.")
    memory_skill_patch_show.add_argument("--workspace", default=".")
    memory_skill_patch_show.set_defaults(func=cmd_memory)

    memory_skill_patch_verify = memory_sub.add_parser(
        "skill-patch-verify",
        help="Run a verification command and attach the result to a skill patch artifact.",
    )
    memory_skill_patch_verify.add_argument("ref", help="Artifact id, candidate id, or 1-based index.")
    memory_skill_patch_verify.add_argument("--workspace", default=".")
    memory_skill_patch_verify.add_argument("--command", required=True)
    memory_skill_patch_verify.add_argument("--timeout", type=int, default=30)
    memory_skill_patch_verify.set_defaults(func=cmd_memory)

    memory_skill_patch_preview = memory_sub.add_parser(
        "skill-patch-preview",
        help="Preview a dry-run diff for applying a skill patch artifact.",
    )
    memory_skill_patch_preview.add_argument("ref", help="Artifact id, candidate id, or 1-based index.")
    memory_skill_patch_preview.add_argument("--workspace", default=".")
    memory_skill_patch_preview.set_defaults(func=cmd_memory)

    tool_output = sub.add_parser("tool-output", help="Inspect stored tool outputs.")
    tool_output_sub = tool_output.add_subparsers(dest="tool_output_command", required=True)

    tool_output_list = tool_output_sub.add_parser("list", help="List stored tool outputs.")
    tool_output_list.add_argument("--workspace", default=".")
    tool_output_list.add_argument("--limit", type=int, default=20)
    tool_output_list.set_defaults(func=cmd_tool_output)

    tool_output_show = tool_output_sub.add_parser("show", help="Show a stored tool output.")
    tool_output_show.add_argument("ref", help="Tool output id or 1-based index.")
    tool_output_show.add_argument("--workspace", default=".")
    tool_output_show.set_defaults(func=cmd_tool_output)

    todo = sub.add_parser("todo", help="Manage the persistent task graph.")
    todo_sub = todo.add_subparsers(dest="todo_command", required=True)

    todo_add = todo_sub.add_parser("add", help="Add a task node.")
    todo_add.add_argument("objective")
    todo_add.add_argument("--workspace", default=".")
    todo_add.add_argument("--task-id", default="")
    todo_add.add_argument("--owner-role", default="planner")
    todo_add.add_argument("--depends-on", action="append", default=[])
    todo_add.add_argument("--context-ref", action="append", default=[])
    todo_add.add_argument("--verify", default="")
    todo_add.set_defaults(func=cmd_todo)

    todo_list = todo_sub.add_parser("list", help="List task nodes.")
    todo_list.add_argument("--workspace", default=".")
    todo_list.set_defaults(func=cmd_todo)

    todo_ready = todo_sub.add_parser("ready", help="List ready task nodes.")
    todo_ready.add_argument("--workspace", default=".")
    todo_ready.set_defaults(func=cmd_todo)

    todo_show = todo_sub.add_parser("show", help="Show a task node in detail.")
    todo_show.add_argument("task_id")
    todo_show.add_argument("--workspace", default=".")
    todo_show.set_defaults(func=cmd_todo)

    todo_note = todo_sub.add_parser("note", help="Append a timestamped note to a task node.")
    todo_note.add_argument("task_id")
    todo_note.add_argument("note")
    todo_note.add_argument("--workspace", default=".")
    todo_note.set_defaults(func=cmd_todo)

    todo_status = todo_sub.add_parser("status", help="Set task node status.")
    todo_status.add_argument("task_id")
    todo_status.add_argument("status")
    todo_status.add_argument("--workspace", default=".")
    todo_status.set_defaults(func=cmd_todo)

    background = sub.add_parser("background", help="Run and inspect persistent background commands.")
    background_sub = background.add_subparsers(dest="background_command", required=True)

    background_start = background_sub.add_parser("start", help="Start a background command.")
    background_start.add_argument("--workspace", default=".")
    background_start.add_argument("--command", required=True)
    background_start.add_argument("--label", default="")
    background_start.add_argument("--task-id", default="")
    background_start.set_defaults(func=cmd_background)

    background_list = background_sub.add_parser("list", help="List background commands.")
    background_list.add_argument("--workspace", default=".")
    background_list.add_argument("--status", default="")
    background_list.add_argument("--limit", type=int, default=20)
    background_list.set_defaults(func=cmd_background)

    background_show = background_sub.add_parser("show", help="Show a background command.")
    background_show.add_argument("ref", help="Background run id or 1-based index.")
    background_show.add_argument("--workspace", default=".")
    background_show.add_argument("--tail-chars", type=int, default=2_000)
    background_show.set_defaults(func=cmd_background)

    background_wait = background_sub.add_parser("wait", help="Wait for a background command to finish.")
    background_wait.add_argument("ref", help="Background run id or 1-based index.")
    background_wait.add_argument("--workspace", default=".")
    background_wait.add_argument("--timeout", type=float, default=30.0)
    background_wait.add_argument("--poll-interval", type=float, default=0.2)
    background_wait.add_argument("--tail-chars", type=int, default=2_000)
    background_wait.set_defaults(func=cmd_background)

    task_ws = sub.add_parser("workspace", help="Manage isolated task workspaces.")
    task_ws_sub = task_ws.add_subparsers(dest="workspace_command", required=True)

    task_ws_create = task_ws_sub.add_parser("create", help="Create/update an isolated task workspace.")
    task_ws_create.add_argument("task_id")
    task_ws_create.add_argument("--workspace", default=".")
    task_ws_create.add_argument("--mode", default="copy", choices=["copy", "git-worktree"])
    task_ws_create.set_defaults(func=cmd_workspace)

    task_ws_list = task_ws_sub.add_parser("list", help="List isolated task workspaces.")
    task_ws_list.add_argument("--workspace", default=".")
    task_ws_list.set_defaults(func=cmd_workspace)

    task_ws_diff = task_ws_sub.add_parser("diff", help="Diff an isolated task workspace against the main workspace.")
    task_ws_diff.add_argument("task_id")
    task_ws_diff.add_argument("--workspace", default=".")
    task_ws_diff.add_argument("--show-diff", action="store_true")
    task_ws_diff.set_defaults(func=cmd_workspace)

    task_ws_merge = task_ws_sub.add_parser("merge", help="Merge an isolated task workspace back into the main workspace.")
    task_ws_merge.add_argument("task_id")
    task_ws_merge.add_argument("--workspace", default=".")
    task_ws_merge.add_argument("--verify", action="append", default=[], help="Additional verification command. Can be provided multiple times.")
    task_ws_merge.add_argument("--skip-task-verify", action="store_true", help="Do not use the task node verification command.")
    task_ws_merge.add_argument("--rollback-on-verification-failure", action="store_true")
    task_ws_merge.add_argument("--dry-run", action="store_true")
    task_ws_merge.add_argument("--show-diff", action="store_true")
    task_ws_merge.set_defaults(func=cmd_workspace)

    orchestrate = sub.add_parser(
        "orchestrate",
        help="Run a minimal planner->coder->tester->integrator task-graph flow.",
    )
    orchestrate.add_argument("--workspace", default=".")
    orchestrate.add_argument("--mode", default="copy", choices=["copy", "git-worktree"])
    orchestrate.add_argument("--limit", type=int, default=1)
    orchestrate.add_argument("--dry-run", action="store_true")
    orchestrate.add_argument("--rollback-on-verification-failure", action="store_true")
    orchestrate.add_argument("--run-coder-agent", action="store_true")
    orchestrate.add_argument("--provider", default="mock", choices=["mock", "openai-compatible"])
    orchestrate.add_argument("--model", default="mock-coder")
    orchestrate.add_argument("--routing-policy", default="signal-aware", choices=["basic", "signal-aware"])
    orchestrate.add_argument("--max-steps", type=int, default=8)
    orchestrate.add_argument("--timeout", type=int, default=30)
    orchestrate.add_argument("--enforce-read-before-write", action="store_true")
    orchestrate.set_defaults(func=cmd_orchestrate)
    return parser


def main() -> None:
    parser = make_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))
