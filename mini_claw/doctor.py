from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mini_claw.dashboard import RuntimeDashboard


VALID_SEVERITIES = {"info", "warn", "fail"}
VALID_CATEGORIES = {"trace", "background", "tasks", "sessions", "tool_output", "memory", "runtime"}


@dataclass(frozen=True)
class DoctorFinding:
    severity: str
    category: str
    code: str
    summary: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(f"Invalid finding severity: {self.severity}")
        if self.category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid finding category: {self.category}")

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "category": self.category,
            "code": self.code,
            "summary": self.summary,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DoctorReport:
    workspace: str
    status: str
    summary: str
    summary_by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    findings: list[DoctorFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "status": self.status,
            "summary": self.summary,
            "summary_by_category": self.summary_by_category,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def to_markdown(self) -> str:
        lines = [
            "# Mini Claw Runtime Doctor",
            "",
            f"- workspace: {self.workspace}",
            f"- status: {self.status}",
            f"- summary: {self.summary}",
            "",
            "## Category Summary",
        ]
        if self.summary_by_category:
            for category, counts in sorted(self.summary_by_category.items()):
                lines.append(
                    f"- {category}: fail={counts.get('fail', 0)} warn={counts.get('warn', 0)} info={counts.get('info', 0)}"
                )
        else:
            lines.append("- none")
        lines.extend([
            "",
            "## Findings",
        ])
        if not self.findings:
            lines.append("- none")
            return "\n".join(lines)
        for finding in self.findings:
            line = f"- [{finding.severity}] {finding.category}/{finding.code}: {finding.summary}"
            if finding.detail:
                line = f"{line} ({finding.detail})"
            lines.append(line)
        return "\n".join(lines)

    def exit_code(self, *, strict_warnings: bool = False) -> int:
        if any(finding.severity == "fail" for finding in self.findings):
            return 1
        if strict_warnings and any(finding.severity == "warn" for finding in self.findings):
            return 1
        return 0


def summarize_doctor_changes(previous: DoctorReport, current: DoctorReport) -> list[str]:
    changes: list[str] = []
    if previous.status != current.status:
        changes.append(f"- status: {previous.status} -> {current.status}")
    if previous.summary != current.summary:
        changes.append(f"- summary: {previous.summary} -> {current.summary}")

    previous_map = {finding.code: finding for finding in previous.findings}
    current_map = {finding.code: finding for finding in current.findings}

    for code in sorted(set(previous_map) | set(current_map)):
        prev = previous_map.get(code)
        curr = current_map.get(code)
        if prev is None and curr is not None:
            changes.append(f"- finding_added[{code}]: [{curr.severity}] {curr.category} {curr.summary}")
            continue
        if prev is not None and curr is None:
            changes.append(f"- finding_removed[{code}]: [{prev.severity}] {prev.category} {prev.summary}")
            continue
        assert prev is not None and curr is not None
        if prev.severity != curr.severity or prev.summary != curr.summary or prev.detail != curr.detail:
            changes.append(
                f"- finding_changed[{code}]: "
                f"[{prev.severity}] {prev.category} {prev.summary} -> "
                f"[{curr.severity}] {curr.category} {curr.summary}"
            )
    return changes


def summarize_doctor_category_delta(
    previous: DoctorReport,
    current: DoctorReport,
) -> dict[str, dict[str, int]]:
    categories = sorted(set(previous.summary_by_category) | set(current.summary_by_category))
    delta: dict[str, dict[str, int]] = {}
    for category in categories:
        previous_counts = previous.summary_by_category.get(category, {})
        current_counts = current.summary_by_category.get(category, {})
        values = {
            "fail": int(current_counts.get("fail", 0)) - int(previous_counts.get("fail", 0)),
            "warn": int(current_counts.get("warn", 0)) - int(previous_counts.get("warn", 0)),
            "info": int(current_counts.get("info", 0)) - int(previous_counts.get("info", 0)),
        }
        if any(values.values()):
            delta[category] = values
    return delta


def run_runtime_doctor(dashboard: RuntimeDashboard) -> DoctorReport:
    findings: list[DoctorFinding] = []

    trace = dashboard.trace_summary
    if trace is None or trace.total_events == 0:
        findings.append(
            DoctorFinding(
                "warn",
                "trace",
                "trace_missing",
                "No runtime trace events were found.",
                "Run a task or replay-backed workflow to populate .mini_claw/memory/task_trace.jsonl.",
            )
        )
    elif trace.failed_tool_calls > 0:
        findings.append(
            DoctorFinding(
                "fail",
                "trace",
                "tool_failures",
                f"{trace.failed_tool_calls} tool call(s) failed in the current runtime trace.",
                "Inspect replay or tool-output records before trusting the latest run.",
            )
        )

    failed_background = int(dashboard.background_status_counts.get("failed", 0) or 0)
    if failed_background > 0:
        findings.append(
            DoctorFinding(
                "fail",
                "background",
                "background_failed",
                f"{failed_background} background run(s) failed.",
                "Review background logs before continuing orchestration.",
            )
        )

    blocked_tasks = int(dashboard.task_status_counts.get("blocked", 0) or 0)
    if blocked_tasks > 0:
        findings.append(
            DoctorFinding(
                "warn",
                "tasks",
                "tasks_blocked",
                f"{blocked_tasks} task(s) are blocked.",
                "The task graph has waiting work that may need manual intervention.",
            )
        )

    if dashboard.latest_session_replay is not None and dashboard.latest_session_replay.failed_turns > 0:
        findings.append(
            DoctorFinding(
                "warn",
                "sessions",
                "session_failed_turns",
                f"Latest session contains {dashboard.latest_session_replay.failed_turns} failed turn(s).",
                "Use session replay or turn-show to inspect the failing turn root cause.",
            )
        )

    if dashboard.truncated_tool_output_count > 0:
        findings.append(
            DoctorFinding(
                "warn",
                "tool_output",
                "tool_output_truncated",
                f"{dashboard.truncated_tool_output_count} tool output record(s) were truncated.",
                "Use tool-output show or lookup to inspect the full stored result when needed.",
            )
        )

    pending_memory = int(dashboard.memory_candidate_status_counts.get("pending", 0) or 0)
    if pending_memory > 0:
        findings.append(
            DoctorFinding(
                "info",
                "memory",
                "memory_pending",
                f"{pending_memory} memory candidate(s) are still pending review.",
                "You can promote or reject them to keep project memory tidy.",
            )
        )

    if dashboard.session_count == 0:
        findings.append(
            DoctorFinding(
                "info",
                "sessions",
                "session_missing",
                "No persistent sessions exist yet.",
                "Create a session if you want resumable multi-turn history.",
            )
        )

    if not findings:
        findings.append(
            DoctorFinding(
                "info",
                "runtime",
                "runtime_clean",
                "No obvious runtime issues detected in the current dashboard snapshot.",
                "The current trace, tasks, sessions, and background runs look healthy.",
            )
        )

    status = "ok"
    if any(finding.severity == "fail" for finding in findings):
        status = "fail"
    elif any(finding.severity == "warn" for finding in findings):
        status = "warn"

    summary = _build_summary(status, findings)
    return DoctorReport(
        workspace=dashboard.workspace,
        status=status,
        summary=summary,
        summary_by_category=_build_category_summary(findings),
        findings=findings,
    )


def _build_summary(status: str, findings: list[DoctorFinding]) -> str:
    fail_count = sum(1 for finding in findings if finding.severity == "fail")
    warn_count = sum(1 for finding in findings if finding.severity == "warn")
    info_count = sum(1 for finding in findings if finding.severity == "info")
    return (
        f"{status.upper()} with {fail_count} fail, {warn_count} warn, "
        f"and {info_count} info finding(s)."
    )


def _build_category_summary(findings: list[DoctorFinding]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for finding in findings:
        bucket = summary.setdefault(finding.category, {"fail": 0, "warn": 0, "info": 0})
        bucket[finding.severity] = bucket.get(finding.severity, 0) + 1
    return summary
