from __future__ import annotations

import json
from pathlib import Path
from textwrap import wrap

HOME_TUI_SECTION_IDS = (
    "team",
    "runtime_health",
    "runtime_counts",
    "sessions",
    "background",
    "session_replay",
    "changes",
)

HOME_TUI_PRESETS: dict[str, dict[str, object]] = {
    "default": {
        "focus": "auto",
        "width": 108,
        "collapsed_sections": set(),
        "watch_layout": "full",
        "watch_collapsed_sections": set(),
    },
    "compact": {
        "focus": "runtime",
        "width": 96,
        "collapsed_sections": {"team", "background", "session_replay"},
        "watch_layout": "delta",
        "watch_collapsed_sections": set(),
    },
    "ops": {
        "focus": "runtime",
        "width": 108,
        "collapsed_sections": {"sessions", "session_replay"},
        "watch_layout": "full",
        "watch_collapsed_sections": set(),
    },
    "interview": {
        "focus": "team",
        "width": 108,
        "collapsed_sections": {"background", "session_replay"},
        "watch_layout": "full",
        "watch_collapsed_sections": {"changes"},
    },
}


def build_terminal_home(workspace: str, bundle: dict[str, object]) -> dict[str, object]:
    dashboard = dict(bundle.get("dashboard") or {})
    doctor = dict(bundle.get("doctor") or {})
    team_board = dict(bundle.get("team_board") or {})
    replay = bundle.get("session_replay")
    runtime_counts = dict(team_board.get("runtime_counts") or {})
    runtime_health = dict(team_board.get("runtime_health") or {})
    team_status = dict(team_board.get("team_status") or {})
    latest_session = team_board.get("latest_session")
    latest_replay = team_board.get("latest_session_replay")
    headline = {
        "team_health": runtime_health.get("status", "n/a"),
        "runtime_health": doctor.get("status", "n/a"),
        "trace_events": int(runtime_counts.get("trace_events", 0) or 0),
        "tool_calls": int(runtime_counts.get("tool_calls", 0) or 0),
        "failed_tool_calls": int(runtime_counts.get("failed_tool_calls", 0) or 0),
        "ready_tasks": len(team_status.get("ready_tasks") or []),
        "background_runs": int(dict(team_board.get("background_runs") or {}).get("total", 0) or 0),
        "sessions": int(dashboard.get("session_count", 0) or 0),
        "latest_session_id": (
            str(dict(latest_session).get("session_id", "") or "")
            if isinstance(latest_session, dict)
            else ""
        ),
        "replay_turns": (
            int(dict(replay).get("total_turns", 0) or 0)
            if isinstance(replay, dict)
            else 0
        ),
    }
    operator_guide = _build_operator_guide(workspace)
    return {
        "workspace": workspace,
        "generated_at": str(dashboard.get("generated_at") or doctor.get("generated_at") or ""),
        "headline": headline,
        "bundle": bundle,
        "latest_session": latest_session,
        "latest_session_replay": latest_replay,
        "operator_guide": operator_guide,
    }


def _build_operator_guide(workspace: str) -> dict[str, object]:
    workspace_path = Path(workspace).resolve()
    runtime_root = workspace_path / ".mini_claw"
    local_config_path = runtime_root / "openai_compatible.local.json"
    config_payload: dict[str, object] = {}
    if local_config_path.exists():
        try:
            loaded = json.loads(local_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            config_payload = dict(loaded)
    base_url = str(config_payload.get("base_url", "") or "").strip()
    has_api_key = bool(str(config_payload.get("api_key", "") or "").strip())
    if has_api_key:
        profile = "real-model-ready (openai-compatible local config)"
    elif local_config_path.exists():
        profile = "local config present, api key missing"
    else:
        profile = "demo/mock friendly, model chosen at run time"
    workspace_arg = _quote_cli_arg(str(workspace_path))
    smoke_model = "glm-4.5-air" if has_api_key else "<model>"
    return {
        "profile": profile,
        "base_url": base_url,
        "commands": {
            "run": (
                "python -S -m mini_claw run "
                f"\"inspect this repository\" --workspace {workspace_arg} --show-execution-diff"
            ),
            "smoke": (
                "python -S -m mini_claw smoke --provider openai-compatible "
                f"--model {smoke_model} --workspace {workspace_arg}"
            ),
            "viewer": (
                "python -S -m mini_claw viewer --from-workspace --source-target bundle "
                "--output-file .mini_claw/runtime_viewer.html"
            ),
            "merge": (
                "python -m mini_claw workspace merge <task_id> "
                f"--workspace {workspace_arg}"
            ),
        },
        "artifacts": {
            "sessions": ".mini_claw/sessions",
            "trace": ".mini_claw/memory/task_trace.jsonl",
            "task_workspaces": ".mini_claw/task_workspaces",
            "viewer": ".mini_claw/runtime_viewer.html",
        },
    }


def _quote_cli_arg(value: str) -> str:
    if not value or any(char.isspace() for char in value) or '"' in value:
        return '"' + value.replace('"', '\\"') + '"'
    return value


def render_terminal_home_markdown(home: dict[str, object]) -> str:
    headline = dict(home.get("headline") or {})
    bundle = dict(home.get("bundle") or {})
    operator_guide = dict(home.get("operator_guide") or {})
    team_board = dict(bundle.get("team_board") or {})
    dashboard = dict(bundle.get("dashboard") or {})
    doctor = dict(bundle.get("doctor") or {})
    session_replay = bundle.get("session_replay")
    team_status = dict(team_board.get("team_status") or {})
    runtime_health = dict(team_board.get("runtime_health") or {})
    runtime_counts = dict(team_board.get("runtime_counts") or {})
    latest_session = home.get("latest_session")
    latest_session_replay = home.get("latest_session_replay")
    background_runs = dict(team_board.get("background_runs") or {})
    doctor_summary_by_category = dict(doctor.get("summary_by_category") or {})
    task_status_counts = dict(team_status.get("status_counts") or {})
    memory_counts = dict(dashboard.get("memory_candidate_status_counts") or {})
    lines = [
        "# Mini Claw Home",
        f"- workspace: {home.get('workspace', '')}",
        f"- generated_at: {home.get('generated_at', '')}",
        f"- team_health: {headline.get('team_health', 'n/a')}",
        f"- runtime_health: {headline.get('runtime_health', 'n/a')}",
        f"- trace_events: {headline.get('trace_events', 0)}",
        f"- ready_tasks: {headline.get('ready_tasks', 0)}",
        f"- failed_tool_calls: {headline.get('failed_tool_calls', 0)}",
        f"- background_runs: {headline.get('background_runs', 0)}",
        f"- latest_session: {headline.get('latest_session_id') or '(none)'}",
        "",
        "## Operator Guide",
        f"- profile: {operator_guide.get('profile', 'n/a')}",
    ]
    base_url = str(operator_guide.get("base_url", "") or "").strip()
    if base_url:
        lines.append(f"- base_url: {base_url}")
    commands = dict(operator_guide.get("commands") or {})
    if commands:
        for key in ["run", "smoke", "viewer", "merge"]:
            value = str(commands.get(key, "") or "").strip()
            if value:
                lines.append(f"- {key}: {value}")
    artifacts = dict(operator_guide.get("artifacts") or {})
    if artifacts:
        lines.append(
            "- artifacts: "
            + ", ".join(
                f"{name}={path}"
                for name, path in artifacts.items()
                if str(name).strip() and str(path).strip()
            )
        )
    lines.extend(
        [
            "",
            "## Team Queue",
            f"- pending: {task_status_counts.get('pending', 0)}",
            f"- in_progress: {task_status_counts.get('in_progress', 0)}",
            f"- blocked: {task_status_counts.get('blocked', 0)}",
            f"- done: {task_status_counts.get('done', 0)}",
            f"- failed: {task_status_counts.get('failed', 0)}",
        ]
    )
    ready_tasks = list(team_status.get("ready_tasks") or [])
    if ready_tasks:
        lines.append(
            "- ready_task_ids: "
            + ", ".join(str(dict(item).get("task_id", "")) for item in ready_tasks if dict(item).get("task_id"))
        )
    lines.extend(
        [
            "",
            "## Runtime Health",
            f"- summary: {runtime_health.get('summary', doctor.get('summary', 'n/a'))}",
            f"- findings: {runtime_health.get('finding_count', len(doctor.get('findings') or []))}",
        ]
    )
    if doctor_summary_by_category:
        for category, counts in sorted(doctor_summary_by_category.items()):
            counts_dict = dict(counts or {})
            lines.append(
                f"- {category}: fail={counts_dict.get('fail', 0)} "
                f"warn={counts_dict.get('warn', 0)} info={counts_dict.get('info', 0)}"
            )
    lines.extend(
        [
            "",
            "## Runtime Counts",
            f"- tool_calls: {headline.get('tool_calls', 0)}",
            f"- context_builds: {runtime_counts.get('context_builds', 0)}",
            f"- sessions: {headline.get('sessions', 0)}",
            f"- replay_turns: {headline.get('replay_turns', 0)}",
            f"- tool_outputs: {dashboard.get('tool_output_count', 0)}",
            f"- truncated_tool_outputs: {dashboard.get('truncated_tool_output_count', 0)}",
            f"- background_status_counts: {dict(dashboard.get('background_status_counts') or {})}",
            f"- memory_candidate_status_counts: {memory_counts}",
        ]
    )
    lines.extend(["", "## Latest Session"])
    if not isinstance(latest_session, dict) or not latest_session.get("session_id"):
        lines.append("(none)")
    else:
        lines.append(
            f"- {latest_session.get('session_id')} name={latest_session.get('name') or '-'} "
            f"turns={latest_session.get('turn_count', 0)}"
        )
        if isinstance(latest_session_replay, dict):
            lines.append(
                f"- replay: completed={latest_session_replay.get('completed_turns', 0)} "
                f"success={latest_session_replay.get('successful_turns', 0)} "
                f"failed={latest_session_replay.get('failed_turns', 0)} "
                f"tool_calls={latest_session_replay.get('tool_calls', 0)}"
            )
    recent_background = list(background_runs.get("recent") or [])
    lines.extend(["", "## Background Runs"])
    if not recent_background:
        lines.append("(none)")
    else:
        for record in recent_background:
            item = dict(record or {})
            lines.append(
                f"- {item.get('run_id', '-')}: status={item.get('status', '-')} "
                f"task={item.get('task_id') or '-'} label={item.get('label') or '-'}"
            )
    if isinstance(session_replay, dict):
        route_counts = dict(session_replay.get("route_reason_counts") or {})
        lines.extend(["", "## Session Replay"])
        lines.append(
            f"- turns={session_replay.get('total_turns', 0)} "
            f"success={session_replay.get('successful_turns', 0)} "
            f"failed={session_replay.get('failed_turns', 0)} "
            f"tool_calls={session_replay.get('tool_calls', 0)}"
        )
        if route_counts:
            lines.append(f"- route_reason_counts: {route_counts}")
    return "\n".join(lines)


def resolve_home_focus(home: dict[str, object], focus: str = "auto") -> str:
    normalized = str(focus or "auto").strip().lower()
    if normalized in {"team", "runtime", "sessions"}:
        return normalized
    headline = dict(home.get("headline") or {})
    latest_session = home.get("latest_session")
    if isinstance(latest_session, dict) and latest_session.get("session_id"):
        return "sessions"
    if int(headline.get("ready_tasks", 0) or 0) > 0:
        return "team"
    return "runtime"


def resolve_home_tui_preset(preset: str = "default") -> dict[str, object]:
    normalized = str(preset or "default").strip().lower() or "default"
    selected = dict(HOME_TUI_PRESETS.get(normalized) or HOME_TUI_PRESETS["default"])
    selected["preset"] = normalized if normalized in HOME_TUI_PRESETS else "default"
    selected["collapsed_sections"] = set(selected.get("collapsed_sections") or set())
    selected["watch_collapsed_sections"] = set(selected.get("watch_collapsed_sections") or set())
    return selected


def _delta_has_change(value: object) -> bool:
    if isinstance(value, dict):
        if {"previous", "current", "delta"}.issubset(value.keys()):
            return value.get("previous") != value.get("current")
        for key, item in value.items():
            if key.endswith("_changed") and bool(item):
                return True
            if _delta_has_change(item):
                return True
        return False
    if isinstance(value, list):
        return bool(value)
    return False


def _summarize_tui_changes(
    changes: list[str] | None,
    changes_by_section: dict[str, list[str]] | None,
) -> list[str]:
    if not changes:
        return ["(no home state changes detected)"]
    summary_lines: list[str] = []
    for section in ["dashboard", "doctor", "team_board", "session_replay"]:
        section_changes = list((changes_by_section or {}).get(section) or [])
        if not section_changes:
            continue
        summary_lines.append(f"{section}: {len(section_changes)} change(s)")
        summary_lines.append(f"  {section_changes[0].lstrip('- ').strip()}")
    return summary_lines or list(changes[:6])


def _title_with_marker(title: str, changed: bool) -> str:
    return f"{title} *" if changed else title


def _collapsed_title(title: str) -> str:
    return f"{title} [collapsed]"


def build_terminal_home_demo_track(
    home: dict[str, object],
    *,
    focus: str = "auto",
    language: str = "en",
    script: str = "full",
) -> list[str]:
    headline = dict(home.get("headline") or {})
    bundle = dict(home.get("bundle") or {})
    team_board = dict(bundle.get("team_board") or {})
    doctor = dict(bundle.get("doctor") or {})
    team_status = dict(team_board.get("team_status") or {})
    runtime_health = dict(team_board.get("runtime_health") or {})
    latest_session = home.get("latest_session")
    resolved_focus = resolve_home_focus(home, focus)
    ready_tasks = len(list(team_status.get("ready_tasks") or []))
    active_tasks = len(list(team_status.get("active_tasks") or []))
    doctor_status = str(doctor.get("status", "n/a") or "n/a")
    runtime_status = str(runtime_health.get("status", headline.get("runtime_health", "n/a")) or "n/a")
    english_lines: list[str]
    chinese_lines: list[str]
    if resolved_focus == "team":
        english_lines = [
            "This first screen is centered on the team control surface rather than only the raw runtime snapshot.",
            f"Right now the queue shows {ready_tasks} ready tasks and {active_tasks} active tasks, so the system state is easy to explain before drilling into execution details.",
            f"The team health is {headline.get('team_health', 'n/a')} and the runtime health is {runtime_status}, which lets me connect queue pressure, runtime health, and recent work in one screen.",
        ]
        chinese_lines = [
            "这个首页聚焦的是 team control surface，而不只是原始 runtime 快照。",
            f"当前队列里有 {ready_tasks} 个 ready task 和 {active_tasks} 个 active task，所以我可以先讲清系统状态，再下钻执行细节。",
            f"当前 team health 是 {headline.get('team_health', 'n/a')}，runtime health 是 {runtime_status}，这样我可以把队列压力、运行时健康和最近执行放到一屏里说明。",
        ]
    elif resolved_focus == "sessions":
        session_id = dict(latest_session or {}).get("session_id") if isinstance(latest_session, dict) else ""
        english_lines = [
            "This first screen is centered on session continuity instead of only the latest answer.",
            f"The current session is {session_id or '(none)'} with {headline.get('replay_turns', 0)} replay turns, so I can explain what happened across turns instead of showing a single response.",
            f"The runtime health is {doctor_status}, which means the session story is backed by trace and doctor signals rather than only user-visible output.",
        ]
        chinese_lines = [
            "这个首页聚焦的是 session continuity，而不只是最近一次回答。",
            f"当前 session 是 {session_id or '(none)'}，包含 {headline.get('replay_turns', 0)} 个 replay turn，所以我可以解释跨轮发生了什么，而不是只展示单次输出。",
            f"当前 runtime health 是 {doctor_status}，这意味着 session 叙事背后有 trace 和 doctor 信号，而不只是用户可见结果。",
        ]
    else:
        english_lines = [
            "This first screen is centered on the runtime system rather than just an agent shell.",
            f"Right now the runtime shows {headline.get('trace_events', 0)} trace events, {headline.get('failed_tool_calls', 0)} failed tool calls, and {headline.get('tool_calls', 0)} total tool calls.",
            f"The runtime health is {doctor_status}, so I can talk about health, evidence, and failure handling before I talk about final answers.",
        ]
        chinese_lines = [
            "这个首页聚焦的是 runtime system，而不只是一个 agent shell。",
            f"当前 runtime 里有 {headline.get('trace_events', 0)} 个 trace event、{headline.get('failed_tool_calls', 0)} 个 failed tool call，以及 {headline.get('tool_calls', 0)} 个 total tool call。",
            f"当前 runtime health 是 {doctor_status}，所以我可以先讲健康度、证据链和失败处理，再讲最终答案。",
        ]
    normalized_script = str(script or "full").strip().lower()
    normalized_language = str(language or "en").strip().lower()
    if normalized_script == "short":
        english_lines = english_lines[:2]
        chinese_lines = chinese_lines[:2]
    if normalized_language == "zh":
        return chinese_lines
    if normalized_language == "bilingual":
        return english_lines + ["---"] + chinese_lines
    return english_lines


def render_terminal_home_tui(
    home: dict[str, object],
    *,
    width: int = 108,
    focus: str = "auto",
    preset: str = "default",
    demo_mode: bool = False,
    demo_language: str = "en",
    demo_focus: str = "auto",
    demo_script: str = "full",
    changes: list[str] | None = None,
    changes_by_section: dict[str, list[str]] | None = None,
    changes_by_section_delta: dict[str, object] | None = None,
    changes_only: bool = False,
    collapsed_sections: set[str] | None = None,
) -> str:
    resolved_preset = resolve_home_tui_preset(preset)
    resolved_focus = resolve_home_focus(home, focus)
    width = max(int(width or 0), 80)
    gap = 2
    column_width = max((width - gap) // 2, 32)
    right_width = max(width - gap - column_width, 32)
    collapsed_lookup = {item.strip().lower() for item in (collapsed_sections or set()) if str(item).strip()}

    headline = dict(home.get("headline") or {})
    bundle = dict(home.get("bundle") or {})
    operator_guide = dict(home.get("operator_guide") or {})
    team_board = dict(bundle.get("team_board") or {})
    dashboard = dict(bundle.get("dashboard") or {})
    doctor = dict(bundle.get("doctor") or {})
    team_status = dict(team_board.get("team_status") or {})
    runtime_health = dict(team_board.get("runtime_health") or {})
    runtime_counts = dict(team_board.get("runtime_counts") or {})
    background_runs = dict(team_board.get("background_runs") or {})
    latest_session = home.get("latest_session")
    latest_session_replay = home.get("latest_session_replay")
    session_replay = bundle.get("session_replay")
    doctor_summary = dict(doctor.get("summary_by_category") or {})
    task_status_counts = dict(team_status.get("status_counts") or {})
    active_tasks = list(team_status.get("active_tasks") or [])
    ready_tasks = list(team_status.get("ready_tasks") or [])
    memory_counts = dict(dashboard.get("memory_candidate_status_counts") or {})
    dashboard_delta = dict((changes_by_section_delta or {}).get("dashboard") or {})
    doctor_delta = dict((changes_by_section_delta or {}).get("doctor") or {})
    team_board_delta = dict((changes_by_section_delta or {}).get("team_board") or {})
    session_replay_delta = dict((changes_by_section_delta or {}).get("session_replay") or {})
    team_changed = _delta_has_change(team_board_delta.get("team_status"))
    runtime_health_changed = _delta_has_change(team_board_delta.get("runtime_health")) or _delta_has_change(doctor_delta)
    runtime_counts_changed = (
        _delta_has_change(team_board_delta.get("runtime_counts"))
        or _delta_has_change(dashboard_delta.get("trace"))
        or _delta_has_change(dashboard_delta.get("tool_outputs"))
        or _delta_has_change(dashboard_delta.get("memory"))
    )
    sessions_changed = (
        _delta_has_change(team_board_delta.get("latest_session"))
        or _delta_has_change(dashboard_delta.get("sessions"))
        or _delta_has_change(session_replay_delta)
    )
    background_changed = _delta_has_change(team_board_delta.get("background_runs")) or _delta_has_change(
        dashboard_delta.get("background")
    )
    session_replay_changed = _delta_has_change(session_replay_delta)

    overview_lines = [
        f"workspace: {home.get('workspace', '')}",
        f"generated_at: {home.get('generated_at', '')}",
        f"preset: {resolved_preset.get('preset', 'default')}",
        f"focus: {resolved_focus}",
        f"profile: {operator_guide.get('profile', 'n/a')}",
        (
            f"team_health={headline.get('team_health', 'n/a')}  "
            f"runtime_health={headline.get('runtime_health', 'n/a')}  "
            f"trace_events={headline.get('trace_events', 0)}  "
            f"ready_tasks={headline.get('ready_tasks', 0)}"
        ),
        (
            f"tool_calls={headline.get('tool_calls', 0)}  "
            f"failed_tool_calls={headline.get('failed_tool_calls', 0)}  "
            f"background_runs={headline.get('background_runs', 0)}  "
            f"latest_session={headline.get('latest_session_id') or '(none)'}"
        ),
    ]
    if changes is not None:
        overview_lines.append(f"change_count: {len(changes)}")
    guide_lines = [f"profile: {operator_guide.get('profile', 'n/a')}"]
    guide_base_url = str(operator_guide.get("base_url", "") or "").strip()
    if guide_base_url:
        guide_lines.append(f"base_url: {guide_base_url}")
    commands = dict(operator_guide.get("commands") or {})
    for key in ["run", "smoke", "viewer", "merge"]:
        value = str(commands.get(key, "") or "").strip()
        if value:
            guide_lines.append(f"{key}: {value}")
    artifacts = dict(operator_guide.get("artifacts") or {})
    if artifacts:
        guide_lines.append(
            "artifacts: "
            + ", ".join(
                f"{name}={path}"
                for name, path in artifacts.items()
                if str(name).strip() and str(path).strip()
            )
        )
    sections = {
        "team": (
            _title_with_marker("Team Queue", team_changed),
            [
                f"pending: {task_status_counts.get('pending', 0)}",
                f"in_progress: {task_status_counts.get('in_progress', 0)}",
                f"blocked: {task_status_counts.get('blocked', 0)}",
                f"done: {task_status_counts.get('done', 0)}",
                f"failed: {task_status_counts.get('failed', 0)}",
                "ready_task_ids: "
                + (", ".join(str(dict(item).get("task_id", "")) for item in ready_tasks if dict(item).get("task_id")) or "(none)"),
                "active_task_ids: "
                + (", ".join(str(dict(item).get("task_id", "")) for item in active_tasks if dict(item).get("task_id")) or "(none)"),
            ],
        ),
        "runtime_health": (
            _title_with_marker("Runtime Health", runtime_health_changed),
            [
                f"status: {headline.get('runtime_health', 'n/a')}",
                f"summary: {runtime_health.get('summary', doctor.get('summary', 'n/a'))}",
                f"findings: {runtime_health.get('finding_count', len(doctor.get('findings') or []))}",
            ]
            + [
                f"{category}: fail={dict(counts or {}).get('fail', 0)} warn={dict(counts or {}).get('warn', 0)} info={dict(counts or {}).get('info', 0)}"
                for category, counts in sorted(doctor_summary.items())
            ],
        ),
        "runtime_counts": (
            _title_with_marker("Runtime Counts", runtime_counts_changed),
            [
                f"trace_events: {headline.get('trace_events', 0)}",
                f"tool_calls: {headline.get('tool_calls', 0)}",
                f"failed_tool_calls: {headline.get('failed_tool_calls', 0)}",
                f"context_builds: {runtime_counts.get('context_builds', 0)}",
                f"sessions: {headline.get('sessions', 0)}",
                f"replay_turns: {headline.get('replay_turns', 0)}",
                f"tool_outputs: {dashboard.get('tool_output_count', 0)}",
                f"truncated_tool_outputs: {dashboard.get('truncated_tool_output_count', 0)}",
                f"memory_candidate_status_counts: {memory_counts}",
            ],
        ),
        "sessions": (
            _title_with_marker("Latest Session", sessions_changed),
            ["(none)"]
            if not isinstance(latest_session, dict) or not latest_session.get("session_id")
            else [
                f"session_id: {latest_session.get('session_id')}",
                f"name: {latest_session.get('name') or '-'}",
                f"turn_count: {latest_session.get('turn_count', 0)}",
                (
                    "replay: completed={completed} success={success} failed={failed} tool_calls={tool_calls}".format(
                        completed=dict(latest_session_replay or {}).get("completed_turns", 0),
                        success=dict(latest_session_replay or {}).get("successful_turns", 0),
                        failed=dict(latest_session_replay or {}).get("failed_turns", 0),
                        tool_calls=dict(latest_session_replay or {}).get("tool_calls", 0),
                    )
                ),
            ],
        ),
        "background": (
            _title_with_marker("Background Runs", background_changed),
            ["(none)"]
            if not list(background_runs.get("recent") or [])
            else [
                f"{dict(record).get('run_id', '-')}: status={dict(record).get('status', '-')} task={dict(record).get('task_id') or '-'}"
                for record in list(background_runs.get("recent") or [])
            ],
        ),
        "session_replay": (
            _title_with_marker("Session Replay", session_replay_changed),
            ["(none)"]
            if not isinstance(session_replay, dict)
            else [
                f"turns: {session_replay.get('total_turns', 0)}",
                f"success: {session_replay.get('successful_turns', 0)}",
                f"failed: {session_replay.get('failed_turns', 0)}",
                f"tool_calls: {session_replay.get('tool_calls', 0)}",
                f"route_reason_counts: {dict(session_replay.get('route_reason_counts') or {})}",
            ],
        ),
    }
    collapsed_section_lines = {
        "team": [
            f"pending={task_status_counts.get('pending', 0)} in_progress={task_status_counts.get('in_progress', 0)}",
            f"blocked={task_status_counts.get('blocked', 0)} done={task_status_counts.get('done', 0)} failed={task_status_counts.get('failed', 0)}",
            f"ready={len(ready_tasks)} active={len(active_tasks)}",
        ],
        "runtime_health": [
            f"status={headline.get('runtime_health', 'n/a')}",
            f"findings={runtime_health.get('finding_count', len(doctor.get('findings') or []))}",
            runtime_health.get("summary", doctor.get("summary", "n/a")),
        ],
        "runtime_counts": [
            f"trace_events={headline.get('trace_events', 0)} tool_calls={headline.get('tool_calls', 0)}",
            f"failed_tool_calls={headline.get('failed_tool_calls', 0)} context_builds={runtime_counts.get('context_builds', 0)}",
            f"sessions={headline.get('sessions', 0)} replay_turns={headline.get('replay_turns', 0)}",
        ],
        "sessions": (
            ["latest_session=(none)", f"replay_turns={headline.get('replay_turns', 0)}"]
            if not isinstance(latest_session, dict) or not latest_session.get("session_id")
            else [
                f"latest_session={latest_session.get('session_id')}",
                f"turn_count={latest_session.get('turn_count', 0)}",
                f"replay_tool_calls={dict(latest_session_replay or {}).get('tool_calls', 0)}",
            ]
        ),
        "background": [
            f"total={background_runs.get('total', 0)}",
            f"recent={len(list(background_runs.get('recent') or []))}",
        ],
        "session_replay": (
            ["(none)"]
            if not isinstance(session_replay, dict)
            else [
                f"turns={session_replay.get('total_turns', 0)}",
                f"success={session_replay.get('successful_turns', 0)} failed={session_replay.get('failed_turns', 0)}",
                f"tool_calls={session_replay.get('tool_calls', 0)}",
            ]
        ),
        "changes": _summarize_tui_changes(changes, changes_by_section),
    }

    if resolved_focus == "team":
        primary_order = [("team", "runtime_health"), ("runtime_counts", "sessions")]
    elif resolved_focus == "sessions":
        primary_order = [("sessions", "session_replay"), ("team", "runtime_health")]
    else:
        primary_order = [("runtime_health", "runtime_counts"), ("team", "sessions")]

    lines = []
    lines.extend(_render_panel("Mini Claw TUI", overview_lines, width))
    lines.append("")
    lines.extend(_render_panel("Operator Guide", guide_lines, width))
    lines.append("")
    if demo_mode and not changes_only:
        lines.extend(
            _render_panel(
                "Demo Track",
                build_terminal_home_demo_track(
                    home,
                    focus=demo_focus if str(demo_focus or "auto").strip().lower() != "auto" else resolved_focus,
                    language=demo_language,
                    script=demo_script,
                ),
                width,
            )
        )
        lines.append("")
    if changes is not None:
        changes_panel_lines = collapsed_section_lines["changes"] if "changes" in collapsed_lookup else _summarize_tui_changes(changes, changes_by_section)
        lines.extend(
            _render_panel(
                _collapsed_title("Changes Since Last Refresh") if "changes" in collapsed_lookup else "Changes Since Last Refresh",
                changes_panel_lines,
                width,
            )
        )
        lines.append("")
    if changes_only:
        return "\n".join(lines).rstrip()
    for left_key, right_key in primary_order:
        left_title, left_lines = sections[left_key]
        right_title, right_lines = sections[right_key]
        if left_key in collapsed_lookup:
            left_title = _collapsed_title(left_title)
            left_lines = collapsed_section_lines[left_key]
        if right_key in collapsed_lookup:
            right_title = _collapsed_title(right_title)
            right_lines = collapsed_section_lines[right_key]
        left_panel = _render_panel(left_title, left_lines, column_width)
        right_panel = _render_panel(right_title, right_lines, right_width)
        lines.extend(_combine_panel_rows(left_panel, right_panel, gap))
        lines.append("")
    background_title, background_lines = sections["background"]
    if "background" in collapsed_lookup:
        background_title = _collapsed_title(background_title)
        background_lines = collapsed_section_lines["background"]
    lines.extend(_render_panel(background_title, background_lines, width))
    return "\n".join(lines).rstrip()


def _render_panel(title: str, lines: list[str], width: int) -> list[str]:
    width = max(int(width or 0), 24)
    inner_width = width - 4
    rendered = [
        "+" + "-" * (width - 2) + "+",
        f"| {title[:inner_width].ljust(inner_width)} |",
        "+" + "-" * (width - 2) + "+",
    ]
    body_lines: list[str] = []
    for raw_line in lines or [""]:
        text = str(raw_line)
        wrapped = wrap(text, width=inner_width) if text else [""]
        body_lines.extend(wrapped or [""])
    if not body_lines:
        body_lines = [""]
    for body_line in body_lines:
        rendered.append(f"| {body_line[:inner_width].ljust(inner_width)} |")
    rendered.append("+" + "-" * (width - 2) + "+")
    return rendered


def _combine_panel_rows(left: list[str], right: list[str], gap: int) -> list[str]:
    left_width = len(left[0]) if left else 0
    right_width = len(right[0]) if right else 0
    max_lines = max(len(left), len(right))
    left_pad = " " * left_width
    right_pad = " " * right_width
    output = []
    for index in range(max_lines):
        left_line = left[index] if index < len(left) else left_pad
        right_line = right[index] if index < len(right) else right_pad
        output.append(f"{left_line}{' ' * gap}{right_line}")
    return output
