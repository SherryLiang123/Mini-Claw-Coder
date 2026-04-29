from __future__ import annotations

import re

from mini_claw.memory.candidates import MemoryCandidate
from mini_claw.skills.loader import Skill


def build_skill_patch_candidate(
    task: str,
    evidence_summary: dict[str, object],
    skill: Skill,
) -> MemoryCandidate | None:
    lookups = int(evidence_summary.get("lookups", 0) or 0)
    if lookups <= 0:
        return None
    if not _needs_lookup_patch(skill):
        return None

    refinements = int(evidence_summary.get("refinements", 0) or 0)
    queries = _unique_texts(evidence_summary.get("queries", []))
    intents = _unique_texts(evidence_summary.get("intents", []))
    hint_kinds = _unique_texts(evidence_summary.get("hint_kinds", []))
    trigger_additions = _derive_trigger_additions(task, queries, intents, skill)
    allowed_tool_additions = _derive_allowed_tool_additions(skill)
    verification_additions = _derive_verification_additions(skill)

    suggested_intents = " | ".join(f"'{intent}'" for intent in intents) or "'error' | 'path'"
    lines = [
        "## Skill Patch Candidate",
        f"- task: {task}",
        f"- target_skill: {skill.name}",
        f"- skill_path: {skill.path}",
        f"- evidence_lookups: {lookups}",
        f"- evidence_refinements: {refinements}",
        f"- evidence_queries: {', '.join(queries) or '(none)'}",
        f"- evidence_intents: {', '.join(intents) or '(none)'}",
        f"- evidence_hint_kinds: {', '.join(hint_kinds) or '(none)'}",
        (
            "- recommended_trigger_additions: "
            f"{', '.join(trigger_additions) or '(none)'}"
        ),
        (
            "- recommended_allowed_tools_addition: "
            f"{', '.join(allowed_tool_additions) or '(none)'}"
        ),
        (
            "- recommended_verification_addition: "
            f"{', '.join(verification_additions) or '(none)'}"
        ),
        "",
        "### Suggested Contract Patch",
        *[
            f"- triggers += {', '.join(trigger_additions)}"
            if trigger_additions
            else "- triggers += (none)"
        ],
        *[
            f"- allowed_tools += {', '.join(allowed_tool_additions)}"
            if allowed_tool_additions
            else "- allowed_tools += (none)"
        ],
        *[
            f"- verification += {', '.join(verification_additions)}"
            if verification_additions
            else "- verification += (none)"
        ],
        "",
        "### Suggested Instruction Patch",
        "1. When a shell result is truncated, call `tool_output_lookup` with `focus='auto'` before retrying a broad shell inspection.",
        (
            "2. If the first excerpt is not enough, refine it with "
            f"`intent={suggested_intents}` and `exclude_queries`."
        ),
        "3. In the final summary, cite the focused lookup evidence that resolved the issue.",
    ]
    confidence = 0.58
    if refinements > 0:
        confidence += 0.05
    if allowed_tool_additions:
        confidence += 0.03
    tags = [
        "skill",
        "patch",
        "candidate",
        f"skill:{skill.name}",
    ]
    if refinements > 0:
        tags.append("multi_hop")
    for intent in intents:
        tags.append(f"intent:{intent}")
    return MemoryCandidate(
        kind="skill_patch_candidate",
        content="\n".join(lines),
        source="agent_skill_evolution",
        confidence=min(confidence, 0.72),
        evidence=(
            "Successful task used runtime evidence lookup and exposed missing lookup guidance "
            f"in skill={skill.name}. lookups={lookups} refinements={refinements}"
        ),
        tags=tags,
    )


def _needs_lookup_patch(skill: Skill) -> bool:
    allowed = {tool.strip().lower() for tool in skill.contract.allowed_tools}
    body = "\n".join(
        [
            skill.contract.description,
            skill.body,
            " ".join(skill.contract.verification),
        ]
    ).lower()
    if "tool_output_lookup" not in allowed:
        return True
    return "truncated" not in body and "lookup" not in body and "focus='auto'" not in body


def _derive_trigger_additions(
    task: str,
    queries: list[str],
    intents: list[str],
    skill: Skill,
) -> list[str]:
    existing = {trigger.strip().lower() for trigger in skill.contract.triggers}
    candidates: list[str] = []
    for intent in intents:
        mapped = {
            "error": "traceback",
            "path": "path",
            "symbol": "symbol",
            "task": "lookup",
        }.get(intent, intent)
        if mapped:
            candidates.append(mapped)
    for query in queries:
        for token in re.split(r"[^A-Za-z0-9_]+", query):
            if 4 <= len(token) <= 20:
                candidates.append(token.lower())
    for token in re.split(r"[^A-Za-z0-9_]+", task):
        if 5 <= len(token) <= 20:
            candidates.append(token.lower())
    selected: list[str] = []
    for candidate in candidates:
        if candidate in existing or candidate in selected:
            continue
        selected.append(candidate)
        if len(selected) >= 4:
            break
    return selected


def _derive_allowed_tool_additions(skill: Skill) -> list[str]:
    allowed = {tool.strip().lower() for tool in skill.contract.allowed_tools}
    if "tool_output_lookup" in allowed:
        return []
    return ["tool_output_lookup"]


def _derive_verification_additions(skill: Skill) -> list[str]:
    existing = " ".join(skill.contract.verification).lower()
    if "focused lookup" in existing:
        return []
    return ["cite focused lookup excerpt before retrying broad shell inspection"]


def _unique_texts(values: object) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    if not isinstance(values, list):
        return items
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items
